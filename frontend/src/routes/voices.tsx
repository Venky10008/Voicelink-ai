import { createFileRoute, useNavigate, useRouterState } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Play, Square, Loader2, Sparkles, Check, RotateCcw,
  Mic, Mic2, Phone, Trash2, AlertTriangle, RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Checkbox } from "@/components/ui/checkbox";
import {
  AlertDialog, AlertDialogTrigger, AlertDialogContent,
  AlertDialogHeader, AlertDialogTitle, AlertDialogDescription,
  AlertDialogFooter, AlertDialogAction, AlertDialogCancel,
} from "@/components/ui/alert-dialog";
import { VOICE_KEY, isVoiceRoute, readSelection, writeSelection } from "@/lib/selection";
import { ActiveSelectionBanner } from "@/components/active-selection-banner";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/voices")({ component: VoicesPage });

export type Voice = { id: string; name: string; tags: string[] };

const defaultVoices: Voice[] = [
  { id: "aria",   name: "Aria",   tags: ["Female", "Warm", "Calm"] },
  { id: "kai",    name: "Kai",    tags: ["Male", "Deep", "Calm"] },
  { id: "luna",   name: "Luna",   tags: ["Female", "Soft", "Warm"] },
  { id: "rex",    name: "Rex",    tags: ["Male", "Energetic"] },
  { id: "nova",   name: "Nova",   tags: ["Female", "Energetic"] },
  { id: "orin",   name: "Orin",   tags: ["Male", "Warm"] },
  { id: "swara",  name: "Swara",  tags: ["Female", "Warm"] },
  { id: "madhur", name: "Madhur", tags: ["Male", "Deep"] },
  { id: "shruti", name: "Shruti", tags: ["Female", "Soft"] },
  { id: "mohan",  name: "Mohan",  tags: ["Male", "Warm"] },
];

const DEFAULT_SPEED = 1;
const DEFAULT_PITCH = 1;
const MAX_RECORD_SECONDS = 15;
const CONSENT_TEXT =
  "I consent to having my voice cloned and stored locally on this server (free, " +
  "no third-party service). I can delete my voice at any time.";

// ── Audio preview helpers ─────────────────────────────────────────────────────
let previewAudioRef: HTMLAudioElement | null = null;
let previewUrlRef: string | null = null;

function stopPreviewAudio() {
  previewAudioRef?.pause();
  previewAudioRef = null;
  if (previewUrlRef) { URL.revokeObjectURL(previewUrlRef); previewUrlRef = null; }
}

function playPreviewAudio(base64: string, mime: string, onEnded?: () => void) {
  try {
    stopPreviewAudio();
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: mime || "audio/mpeg" });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    previewAudioRef = audio;
    previewUrlRef = url;
    let settled = false;
    const finish = (errored: boolean) => {
      if (settled) return;
      settled = true;
      if (previewAudioRef === audio) previewAudioRef = null;
      if (previewUrlRef === url) previewUrlRef = null;
      URL.revokeObjectURL(url);
      onEnded?.();
      if (errored) toast.error("Could not play the voice preview.");
    };
    audio.onended = () => finish(false);
    audio.onerror = () => finish(true);
    audio.play().catch(() => finish(true));
  } catch {
    onEnded?.();
    toast.error("Could not decode the voice preview.");
  }
}

// ── Main component ────────────────────────────────────────────────────────────
function VoicesPage({ voices: initialVoices, loading: initialLoading = false }: {
  voices?: Voice[]; loading?: boolean;
}) {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { token } = useAuth();

  // Library voices
  const [voices, setVoices] = useState<Voice[]>(initialVoices ?? defaultVoices);
  const [loading, setLoading] = useState(initialLoading);
  const [selected, setSelected] = useState<string | null>(null);
  const [selecting, setSelecting] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const previewRequestRef = useRef<string | null>(null);
  const [speed, setSpeed] = useState([DEFAULT_SPEED]);
  const [pitch, setPitch] = useState([DEFAULT_PITCH]);
  const [banner, setBanner] = useState<{ name: string; redirecting: boolean } | null>(null);

  // ── Cloned voice state ──────────────────────────────────────────────────────
  type CloneStatus = { my_profile_id: number | null; clone_engine_available: boolean; clone_engine_message?: string };
  const [cloneStatus, setCloneStatus] = useState<CloneStatus | null>(null);
  const [cloneLoading, setCloneLoading] = useState(true);

  // Recording
  const [consent, setConsent] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<number | null>(null);

  // My Voice playback
  const [myPreviewing, setMyPreviewing] = useState(false);
  const [myPlaying, setMyPlaying] = useState(false);
  const [mySelecting, setMySelecting] = useState(false);

  // ── Fetch clone status ───────────────────────────────────────────────────────
  const refreshCloneStatus = useCallback(async () => {
    setCloneLoading(true);
    try {
      const d = await apiFetch<CloneStatus>("/voice/my-permissions", { token });
      setCloneStatus(d);
    } catch {
      setCloneStatus(null);
    } finally {
      setCloneLoading(false);
    }
  }, [token]);

  useEffect(() => { refreshCloneStatus(); }, [refreshCloneStatus]);

  // ── Auto-stop recording at cap ───────────────────────────────────────────────
  useEffect(() => {
    if (recording && recordSeconds >= MAX_RECORD_SECONDS) stopRecording();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordSeconds, recording]);

  // ── Cleanup on unmount ───────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      stopPreviewAudio();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  // ── Prefill speed/pitch & selected voice ────────────────────────────────────
  useEffect(() => {
    if (initialVoices) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch<{ voice_id: string | null; speed: number; pitch: number }>(
          "/profile/settings", { token }
        );
        if (!cancelled) {
          if (data.voice_id) setSelected(data.voice_id);
          setSpeed([data.speed]);
          setPitch([data.pitch]);
        }
      } catch { /* best-effort */ }
      const storedSel = readSelection(VOICE_KEY);
      if (!cancelled && storedSel?.voiceProfileId && storedSel.id) setSelected(storedSel.id);
    })();
    return () => { cancelled = true; };
  }, [initialVoices, token]);

  // ── Load library voices ──────────────────────────────────────────────────────
  useEffect(() => {
    if (initialVoices) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const data = await apiFetch<{ voices: Voice[] }>("/voices");
        if (!cancelled) setVoices(data.voices);
      } catch (err) {
        if (!cancelled) toast.error(err instanceof Error ? err.message : "Could not load voices.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [initialVoices]);

  // ── Recording helpers ────────────────────────────────────────────────────────
  const startRecording = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      toast.error("Microphone not supported in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus" : "audio/webm";
      const recorder = new MediaRecorder(stream, { mimeType });
      chunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeType });
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        recorderRef.current = null;
        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
        setRecording(false);
        setRecordSeconds(0);
        uploadSample(blob);
      };
      recorderRef.current = recorder;
      setRecordSeconds(0);
      recorder.start();
      setRecording(true);
      timerRef.current = window.setInterval(() => setRecordSeconds((s) => s + 1), 1000);
    } catch {
      toast.error("Microphone access denied or unavailable.");
    }
  };

  const stopRecording = () => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state === "recording") {
      recorder.stop();
    } else {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      recorderRef.current = null;
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
      setRecording(false);
      setRecordSeconds(0);
    }
  };

  const uploadSample = async (blob: Blob) => {
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", blob, "voice-sample.webm");
      formData.append("consent_confirmed", "true");
      await apiFetch<{ voice_profile_id: number; status: string }>("/voice/record-sample", {
        method: "POST", formData, token,
      });
      toast.success("Your voice has been cloned!", {
        description: "Select it below to use in calls.",
      });
      setConsent(false);
      await refreshCloneStatus();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not clone your voice. Try recording again.");
    } finally {
      setUploading(false);
    }
  };

  const onDeleteMyVoice = async () => {
    setDeleting(true);
    try {
      await apiFetch("/voice/delete-profile", { method: "DELETE", token });
      toast.success("Your cloned voice was deleted.");
      stopPreviewAudio();
      setMyPlaying(false);
      // If it was selected, clear the selection
      const storedSel = readSelection(VOICE_KEY);
      if (storedSel?.voiceProfileId) {
        localStorage.removeItem(VOICE_KEY);
        window.dispatchEvent(new CustomEvent("voicelink:selection"));
        setSelected(null);
      }
      await refreshCloneStatus();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete your voice.");
    } finally {
      setDeleting(false);
    }
  };

  // ── My Voice preview ─────────────────────────────────────────────────────────
  const onPreviewMyVoice = async () => {
    if (myPlaying) { stopPreviewAudio(); setMyPlaying(false); return; }
    if (!cloneStatus?.my_profile_id) return;
    stopPreviewAudio();
    setMyPreviewing(true);
    try {
      const data = await apiFetch<{ audio_base64: string; audio_mime_type: string }>(
        "/voice/preview-cloned",
        { method: "POST", body: { voice_profile_id: cloneStatus.my_profile_id }, token }
      );
      setMyPlaying(true);
      playPreviewAudio(data.audio_base64, data.audio_mime_type, () => setMyPlaying(false));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not preview your cloned voice.");
    } finally {
      setMyPreviewing(false);
    }
  };

  // ── My Voice → use in calls ──────────────────────────────────────────────────
  const onSelectMyVoice = async () => {
    if (!cloneStatus?.my_profile_id) return;
    setMySelecting(true);
    const id = `cloned-${cloneStatus.my_profile_id}`;
    try {
      writeSelection(VOICE_KEY, {
        id, name: "My Voice", speed: speed[0], pitch: pitch[0],
        voiceProfileId: cloneStatus.my_profile_id,
      });
      setSelected(id);
      toast.success("Your cloned voice is ready!", {
        description: "Opening Voice Call — the AI will reply in your voice.",
      });
      navigate({ to: "/call" });
    } finally {
      setMySelecting(false);
    }
  };

  // ── Library voice actions ─────────────────────────────────────────────────────
  const onPreviewVoice = async (voice: Voice) => {
    if (playingId === voice.id) { stopPreviewAudio(); setPlayingId(null); return; }
    stopPreviewAudio();
    previewRequestRef.current = voice.id;
    setPlayingId(voice.id);
    setPreviewing(voice.id);
    try {
      const data = await apiFetch<{ audio_base64: string; audio_mime_type: string }>(
        "/voices/preview",
        { method: "POST", body: { voice_id: voice.id, speed: speed[0], pitch: pitch[0] }, token }
      );
      if (previewRequestRef.current !== voice.id) return;
      playPreviewAudio(data.audio_base64, data.audio_mime_type, () => setPlayingId(null));
    } catch (err) {
      if (previewRequestRef.current === voice.id) {
        setPlayingId(null);
        toast.error(err instanceof Error ? err.message : "Could not preview this voice.");
      }
    } finally {
      if (previewRequestRef.current === voice.id) setPreviewing(null);
    }
  };

  const onSelectVoice = async (id: string, _speed: number, _pitch: number) => {
    setSelecting(id);
    try {
      await apiFetch("/profile/settings", {
        method: "PUT", body: { voice_id: id, speed: _speed, pitch: _pitch }, token,
      });
      setSelected(id);
      const name = voices.find((v) => v.id === id)?.name ?? "Voice";
      writeSelection(VOICE_KEY, { id, name, speed: _speed, pitch: _pitch });
      const goToCall = isVoiceRoute(pathname);
      setBanner({ name, redirecting: goToCall });
      toast.success(`${name} selected`, {
        description: goToCall
          ? "Opening Voice Call with this voice…"
          : "Saved as your active voice.",
      });
      if (goToCall) navigate({ to: "/call" });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save this voice.");
    } finally {
      setSelecting(null);
    }
  };

  const onResetCustomization = () => { setSpeed([DEFAULT_SPEED]); setPitch([DEFAULT_PITCH]); };
  const isCustomized = speed[0] !== DEFAULT_SPEED || pitch[0] !== DEFAULT_PITCH;

  const myProfileId = cloneStatus?.my_profile_id ?? null;
  const engineAvailable = cloneStatus?.clone_engine_available ?? false;

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <AppShell title="Voice Library">
      <div className="p-6 sm:p-8 max-w-6xl mx-auto space-y-10">
        {/* ── Header ── */}
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="font-display text-3xl font-bold">Voice Library</h1>
            <Badge variant="secondary" className="text-xs">Free · Edge TTS</Badge>
          </div>
          <p className="text-muted-foreground mt-1">
            Clone your own voice or pick a built-in voice for calls.
          </p>
          <ActiveSelectionBanner className="mt-4 justify-start" />
        </div>

        {banner && (
          <div className="flex items-center gap-3 rounded-xl border border-primary/40 bg-primary/10 px-4 py-3 text-sm animate-in fade-in slide-in-from-top-1">
            <Sparkles className="h-4 w-4 text-primary shrink-0" />
            <span>
              <span className="font-medium">{banner.name}</span> is now your active voice
              {banner.redirecting ? " — taking you to the Voice Call screen…" : " — you can keep browsing here."}
            </span>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════════════════
            MY CLONED VOICE SECTION — the main feature
            ════════════════════════════════════════════════════════════════════ */}
        <section className="space-y-4">
          <div className="flex items-center gap-2">
            <Mic2 className="h-5 w-5 text-primary" />
            <h2 className="font-display font-bold text-xl">My Cloned Voice</h2>
            <Badge className="bg-primary/20 text-primary border-primary/30 text-xs">AI · Free · Local</Badge>
          </div>

          <p className="text-xs text-muted-foreground rounded-lg border border-border/60 bg-muted/30 px-3 py-2">
            Cloning runs locally on this machine&apos;s GPU from your reference recording. For demo
            stability the call uses a lightweight built-in voice fallback behind the scenes, so
            selecting &quot;My Voice&quot; never fails live.
          </p>

          {cloneLoading ? (
            <Skeleton className="h-44 rounded-2xl" />
          ) : myProfileId != null ? (
            /* ── HAS CLONED VOICE ── */
            <div className="glass border-2 border-primary/40 rounded-2xl p-6 bg-gradient-to-br from-primary/10 via-transparent to-transparent space-y-4 shadow-glow">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex items-center gap-4">
                  <div className="h-14 w-14 rounded-full bg-gradient-primary shadow-glow flex items-center justify-center shrink-0">
                    <Mic2 className="h-7 w-7 text-primary-foreground" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2 font-display font-bold text-xl">
                      My Voice
                      <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">
                        <Check className="h-3 w-3 mr-1" /> Cloned
                      </Badge>
                    </div>
                    <p className="text-sm text-muted-foreground mt-0.5">
                      The AI will speak in your own voice. Select it to start a call.
                    </p>
                  </div>
                </div>

                {/* Action buttons */}
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    onClick={onPreviewMyVoice}
                    disabled={myPreviewing}
                    id="preview-my-voice-btn"
                  >
                    {myPreviewing ? (
                      <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                    ) : myPlaying ? (
                      <Square className="h-4 w-4 mr-1.5 fill-current" />
                    ) : (
                      <Play className="h-4 w-4 mr-1.5" />
                    )}
                    {myPreviewing ? "Preparing…" : myPlaying ? "Stop" : "Preview"}
                  </Button>

                  <Button
                    onClick={onSelectMyVoice}
                    disabled={mySelecting || selected === `cloned-${myProfileId}`}
                    className="bg-gradient-primary text-primary-foreground shadow-glow"
                    id="use-my-voice-btn"
                  >
                    {mySelecting ? (
                      <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                    ) : selected === `cloned-${myProfileId}` ? (
                      <><Check className="h-4 w-4 mr-1" /> Selected</>
                    ) : (
                      <><Phone className="h-4 w-4 mr-1.5" /> Use in Call</>
                    )}
                  </Button>

                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button variant="ghost" size="icon" disabled={deleting} className="text-destructive/70 hover:text-destructive" title="Delete cloned voice">
                        {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Delete your cloned voice?</AlertDialogTitle>
                        <AlertDialogDescription>
                          This permanently removes your voice clone. You can record a new sample anytime.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Keep it</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={onDeleteMyVoice}
                          className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        >
                          <Trash2 className="h-4 w-4 mr-1.5" /> Delete
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </div>

              {/* Already selected call-to-action */}
              {selected === `cloned-${myProfileId}` && (
                <div className="flex items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm">
                  <Phone className="h-4 w-4 text-emerald-400 shrink-0" />
                  <span className="text-emerald-300">
                    Your cloned voice is active.{" "}
                    <button
                      onClick={() => navigate({ to: "/call" })}
                      className="underline font-medium hover:text-emerald-200 transition-colors"
                    >
                      Go to Voice Call →
                    </button>
                  </span>
                </div>
              )}
            </div>
          ) : (
            /* ── NO CLONED VOICE — show recording UI ── */
            <div className="glass border rounded-2xl p-6 space-y-5">
              {/* Engine unavailable warning */}
              {!engineAvailable && (
                <div className="flex items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm">
                  <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                  <div>
                    <div className="font-medium text-amber-400">Voice cloning engine not ready</div>
                    <p className="text-muted-foreground mt-0.5 text-xs">
                      {cloneStatus?.clone_engine_message ??
                        "Install OmniVoice in the backend venv: pip install omnivoice"}
                    </p>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="mt-2 h-7 text-xs gap-1.5"
                      onClick={refreshCloneStatus}
                    >
                      <RefreshCw className="h-3 w-3" /> Check again
                    </Button>
                  </div>
                </div>
              )}

              <div className="flex items-start gap-4">
                <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center shrink-0">
                  <Mic2 className="h-6 w-6 text-muted-foreground" />
                </div>
                <div>
                  <div className="font-display font-semibold text-lg">Clone your voice</div>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    Record a 8–12 second sample. The AI will reply in your own voice during calls.
                    Free, local, no API key needed.
                  </p>
                </div>
              </div>

              {/* Sample text to read */}
              {engineAvailable && (
                <div className="rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 space-y-1">
                  <div className="text-xs font-semibold uppercase tracking-wider text-primary">
                    📝 Read this aloud when you click Record:
                  </div>
                  <p className="text-sm text-foreground/90 leading-relaxed">
                    "Hello, this is my voice. I love sharing ideas and helping people. Today is a
                    great day and I'm happy to talk with you. Let's have a wonderful conversation."
                  </p>
                  <p className="text-xs text-muted-foreground">Speak clearly and naturally for 8–12 seconds.</p>
                </div>
              )}

              {/* Consent checkbox */}
              <label className="flex items-start gap-3 cursor-pointer">
                <Checkbox
                  checked={consent}
                  onCheckedChange={(v) => setConsent(!!v)}
                  className="mt-0.5"
                  id="clone-consent"
                />
                <span className="text-xs text-muted-foreground leading-relaxed">
                  {CONSENT_TEXT}
                </span>
              </label>

              {/* Record button + status */}
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  onClick={recording ? stopRecording : startRecording}
                  disabled={!consent || uploading || !engineAvailable}
                  className={recording
                    ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
                    : "bg-gradient-primary text-primary-foreground shadow-glow"
                  }
                  id="record-voice-btn"
                >
                  {recording ? (
                    <><Square className="h-4 w-4 mr-2 fill-current" /> Stop ({recordSeconds}s)</>
                  ) : uploading ? (
                    <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Cloning…</>
                  ) : (
                    <><Mic className="h-4 w-4 mr-2" /> Record Sample</>
                  )}
                </Button>

                {recording && (
                  <div className="flex items-center gap-2">
                    <span className="relative flex h-2.5 w-2.5">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                      <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-red-500" />
                    </span>
                    <span className="text-sm font-medium text-red-400">
                      Recording… {recordSeconds}s / {MAX_RECORD_SECONDS}s
                    </span>
                    <div className="flex gap-0.5 items-end h-5">
                      {Array.from({ length: 8 }).map((_, i) => (
                        <span
                          key={i}
                          className="w-1 bg-red-400/80 rounded-full"
                          style={{
                            height: "100%",
                            animation: `wave 0.8s ease-in-out ${i * 0.1}s infinite`,
                            transformOrigin: "bottom",
                          }}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {uploading && (
                  <span className="text-sm text-muted-foreground animate-pulse">
                    Processing your voice — this takes a moment…
                  </span>
                )}
              </div>
            </div>
          )}
        </section>

        {/* ════════════════════════════════════════════════════════════════════
            SPEED / PITCH CUSTOMIZATION
            ════════════════════════════════════════════════════════════════════ */}
        <section className="glass border rounded-2xl p-6 space-y-6">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-display font-semibold text-lg">Customize Sound</h2>
            <Button
              variant="ghost" size="sm"
              onClick={onResetCustomization}
              disabled={!isCustomized}
              className="gap-1.5 h-8"
            >
              <RotateCcw className="h-3.5 w-3.5" /> Reset
            </Button>
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label htmlFor="speed-slider">Speed</Label>
              <span className="text-sm text-muted-foreground tabular-nums">{speed[0].toFixed(2)}×</span>
            </div>
            <Slider id="speed-slider" value={speed} onValueChange={setSpeed} min={0.5} max={1.5} step={0.05} aria-label="Voice speed" />
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label htmlFor="pitch-slider">Pitch</Label>
              <span className="text-sm text-muted-foreground tabular-nums">{pitch[0].toFixed(2)}×</span>
            </div>
            <Slider id="pitch-slider" value={pitch} onValueChange={setPitch} min={0.5} max={2} step={0.05} aria-label="Voice pitch" />
          </div>
          <p className="text-xs text-muted-foreground">
            Applies to both your cloned voice and library voices.
          </p>
        </section>

        {/* ════════════════════════════════════════════════════════════════════
            LIBRARY VOICES
            ════════════════════════════════════════════════════════════════════ */}
        <section className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="font-display font-bold text-xl">Library Voices</h2>
            <Badge variant="secondary" className="text-xs">Free · Edge TTS · No API key</Badge>
          </div>
          <p className="text-muted-foreground text-sm">
            Built-in voices that speak automatically in the language you use.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {loading &&
              Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="glass border rounded-2xl p-5 space-y-4">
                  <Skeleton className="h-6 w-24" />
                  <div className="flex gap-2"><Skeleton className="h-5 w-14 rounded-full" /><Skeleton className="h-5 w-14 rounded-full" /></div>
                  <Skeleton className="h-9 w-full rounded-md" />
                </div>
              ))}
            {!loading &&
              voices.map((v, i) => {
                const isSelected = selected === v.id;
                const isPlaying = playingId === v.id;
                return (
                  <div
                    key={v.id}
                    className={`glass border rounded-2xl p-5 transition-all animate-in fade-in slide-in-from-bottom-2 ${
                      isSelected ? "ring-2 ring-primary shadow-glow" : "hover:-translate-y-0.5"
                    }`}
                    style={{ animationDelay: `${i * 40}ms`, animationFillMode: "backwards" }}
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div>
                        <div className="font-display font-semibold text-lg">{v.name}</div>
                        <div className="flex flex-wrap gap-1 mt-2">
                          {v.tags.map((t) => (
                            <Badge key={t} variant="secondary" className="text-xs">{t}</Badge>
                          ))}
                        </div>
                      </div>
                      <Button
                        size="icon" variant="ghost"
                        onClick={() => onPreviewVoice(v)}
                        disabled={previewing === v.id}
                        aria-label={isPlaying ? `Stop previewing ${v.name}` : `Preview ${v.name}`}
                        aria-pressed={isPlaying}
                        className="rounded-full"
                      >
                        {previewing === v.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : isPlaying ? (
                          <Square className="h-4 w-4 fill-current" />
                        ) : (
                          <Play className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                    <Button
                      onClick={() => onSelectVoice(v.id, speed[0], pitch[0])}
                      disabled={selecting === v.id}
                      className={`w-full ${isSelected ? "bg-gradient-primary text-primary-foreground shadow-glow" : ""}`}
                      variant={isSelected ? "default" : "outline"}
                    >
                      {selecting === v.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : isSelected ? (
                        <><Check className="h-4 w-4 mr-1" /> Selected</>
                      ) : "Select"}
                    </Button>
                  </div>
                );
              })}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
