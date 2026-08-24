import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Mic,
  Square,
  Play,
  Loader2,
  Search,
  Trash2,
  Check,
  Sparkles,
  UserPlus,
  Volume2,
  AlertTriangle,
  Clock,
} from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AlertDialog,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/permissions")({ component: PermissionsPage });

type Grantee = {
  permission_id: number;
  user_id: number | null;
  user_name: string;
  status: string;
  created_at: string;
  updated_at: string;
};

type VoiceUse = {
  permission_id: number;
  voice_profile_id: number;
  owner_name: string;
  status: string;
  created_at: string;
  updated_at: string;
};

type DiscoverProfile = {
  voice_profile_id: number;
  owner_name: string;
  created_at: string;
  my_status: string;
};

type MyPermissions = {
  my_profile_id: number | null;
  my_voice_grantees: Grantee[];
  voices_i_can_use: VoiceUse[];
  clone_engine_available: boolean;
  clone_engine_message?: string;
};

type ClonedPreview = { audio_base64: string; audio_mime_type: string };

const MAX_RECORD_SECONDS = 15;

let previewAudioRef: HTMLAudioElement | null = null;
let previewUrlRef: string | null = null;

function stopPreview() {
  previewAudioRef?.pause();
  previewAudioRef = null;
  if (previewUrlRef) {
    URL.revokeObjectURL(previewUrlRef);
    previewUrlRef = null;
  }
}

function playPreview(base64: string, mimeType: string, onEnded?: () => void) {
  try {
    stopPreview();
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: mimeType || "audio/wav" });
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

function statusBadge(status: string) {
  switch (status) {
    case "approved":
      return <Badge className="bg-emerald-500/20 text-emerald-500 border-emerald-500/30">Approved</Badge>;
    case "pending":
      return <Badge variant="secondary">Pending</Badge>;
    case "revoked":
      return <Badge variant="outline" className="text-muted-foreground">Revoked</Badge>;
    default:
      return <Badge variant="outline">None</Badge>;
  }
}

function PermissionsPage() {
  const { token } = useAuth();

  const [data, setData] = useState<MyPermissions | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Recording / cloning state
  const [consent, setConsent] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const [uploading, setUploading] = useState(false);

  // Permission actions
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [requestingId, setRequestingId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [previewingId, setPreviewingId] = useState<number | null>(null);

  // Discovery
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [discover, setDiscover] = useState<DiscoverProfile[] | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const d = await apiFetch<MyPermissions>("/voice/my-permissions", { token });
      setData(d);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load your voice permissions.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Auto-stop the recording at the cap.
  useEffect(() => {
    if (recording && recordSeconds >= MAX_RECORD_SECONDS) stopRecording();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordSeconds, recording]);

  // Clean up media + preview audio on unmount.
  useEffect(() => {
    return () => {
      stopPreview();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  // Debounced discovery search.
  useEffect(() => {
    const t = setTimeout(() => runSearch(query), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, token]);

  const runSearch = async (q: string) => {
    setSearching(true);
    try {
      const res = await apiFetch<{ profiles: DiscoverProfile[] }>(
        `/voice/discover${q ? `?q=${encodeURIComponent(q)}` : ""}`,
        { token },
      );
      setDiscover(res.profiles);
    } catch (err) {
      setDiscover([]);
      toast.error(err instanceof Error ? err.message : "Could not search voices.");
    } finally {
      setSearching(false);
    }
  };

  // -------------------------------------------------------------------------
  // Recording + cloning
  // -------------------------------------------------------------------------

  const startRecording = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      toast.error("Microphone is not supported in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeType });
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        recorderRef.current = null;
        if (timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
        setRecording(false);
        setRecordSeconds(0);
        uploadSample(blob);
      };
      recorderRef.current = recorder;
      setRecordSeconds(0);
      recorder.start();
      setRecording(true);
      timerRef.current = window.setInterval(() => {
        setRecordSeconds((s) => s + 1);
      }, 1000);
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
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
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
        method: "POST",
        formData,
        token,
      });
      toast.success("Your voice has been cloned!", {
        description: "It's now available in the Voice Library as 'My Voice' — free and unlimited.",
      });
      setConsent(false);
      await refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Could not clone your voice. Try recording again.",
      );
    } finally {
      setUploading(false);
    }
  };

  // -------------------------------------------------------------------------
  // Permission actions
  // -------------------------------------------------------------------------

  const onApprove = async (permissionId: number) => {
    setUpdatingId(permissionId);
    try {
      await apiFetch("/voice/approve-access", {
        method: "POST",
        body: { permission_id: permissionId },
        token,
      });
      toast.success("Access approved — they can now use your voice.");
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not approve access.");
    } finally {
      setUpdatingId(null);
    }
  };

  const onRevoke = async (permissionId: number) => {
    setUpdatingId(permissionId);
    try {
      await apiFetch("/voice/revoke-access", {
        method: "POST",
        body: { permission_id: permissionId },
        token,
      });
      toast.success("Access revoked.");
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not revoke access.");
    } finally {
      setUpdatingId(null);
    }
  };

  const onDeleteProfile = async () => {
    setDeleting(true);
    try {
      await apiFetch("/voice/delete-profile", { method: "DELETE", token });
      toast.success("Your voice profile was deleted and all access revoked.");
      setPreviewingId(null);
      stopPreview();
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete your voice profile.");
    } finally {
      setDeleting(false);
    }
  };

  const onRequestAccess = async (voiceProfileId: number) => {
    setRequestingId(voiceProfileId);
    try {
      await apiFetch("/voice/request-access", {
        method: "POST",
        body: { voice_profile_id: voiceProfileId },
        token,
      });
      toast.success("Access requested", {
        description: "The voice owner needs to approve it before you can use it.",
      });
      await runSearch(query);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not request access.");
    } finally {
      setRequestingId(null);
    }
  };

  const onPreviewVoice = async (voiceProfileId: number) => {
    if (previewingId === voiceProfileId) {
      stopPreview();
      setPreviewingId(null);
      return;
    }
    stopPreview();
    setPreviewingId(voiceProfileId);
    try {
      const res = await apiFetch<ClonedPreview>("/voice/preview-cloned", {
        method: "POST",
        body: { voice_profile_id: voiceProfileId },
        token,
      });
      playPreview(res.audio_base64, res.audio_mime_type, () => setPreviewingId(null));
    } catch (err) {
      setPreviewingId(null);
      toast.error(err instanceof Error ? err.message : "Could not preview this voice.");
    }
  };

  const myProfileId = data?.my_profile_id ?? null;
  const grantees = data?.my_voice_grantees ?? [];
  const voicesICanUse = data?.voices_i_can_use ?? [];

  return (
    <AppShell title="My Voice & Permissions">
      <div className="p-6 sm:p-8 max-w-4xl mx-auto space-y-8">
        <div>
          <h1 className="font-display text-3xl font-bold">My Voice &amp; Permissions</h1>
          <p className="text-muted-foreground mt-1">
            Clone your voice for free (local engine, no API key) and control who can use it.
          </p>
        </div>

        {loading ? (
          <div className="space-y-4">
            <Skeleton className="h-44 rounded-2xl" />
            <Skeleton className="h-52 rounded-2xl" />
          </div>
        ) : loadError ? (
          <div className="glass border rounded-2xl p-6 flex flex-col items-center gap-3 text-center">
            <AlertTriangle className="h-6 w-6 text-destructive" />
            <p className="text-sm text-muted-foreground max-w-md">{loadError}</p>
            <Button variant="outline" onClick={refresh}>
              <Loader2 className="h-4 w-4 mr-1.5" /> Retry
            </Button>
          </div>
        ) : (
          <>
            {!data?.clone_engine_available && (
              <div className="flex items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm animate-in fade-in">
                <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                <div>
                  <div className="font-medium text-amber-500">Voice cloning engine not available</div>
                  <p className="text-muted-foreground mt-0.5">
                    {data?.clone_engine_message ??
                      "Run the backend from the Python 3.11 venv (backend/voice-venv) to enable OmniVoice cloning. Voice calls still work with the free Edge TTS voices."}
                  </p>
                </div>
              </div>
            )}

            {/* ---------------------------------------------------------------
                MY VOICE
                --------------------------------------------------------------- */}
            <section className="glass border rounded-2xl p-6 space-y-5">
              {data?.clone_engine_available && (
                <div className="flex items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm animate-in fade-in">
                  <Clock className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                  <div>
                    <div className="font-medium text-amber-500">May take a few minutes</div>
                    <p className="text-muted-foreground mt-0.5">
                      VoiceLink is a prototype running on free servers, so cloning your voice —
                      and generating speech with it — can take a few minutes to finish. If you
                      have a little patience, it&apos;s worth the wait!
                    </p>
                  </div>
                </div>
              )}

              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div>
                  <h2 className="font-display font-semibold text-xl">My Voice</h2>
                  <p className="text-sm text-muted-foreground mt-1">
                    {myProfileId != null
                      ? "Your cloned voice is ready. Preview it, use it in calls, or delete it."
                      : "Record a short sample and your voice will be cloned locally — free and unlimited."}
                  </p>
                </div>
                {myProfileId != null && (
                  <Badge className="bg-emerald-500/20 text-emerald-500 border-emerald-500/30">
                    <Check className="h-3 w-3 mr-1" /> Cloned
                  </Badge>
                )}
              </div>

              {myProfileId == null ? (
                <div className="space-y-4">
                  <label className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 cursor-pointer">
                    <Checkbox
                      checked={consent}
                      onCheckedChange={(v) => setConsent(!!v)}
                      className="mt-0.5"
                    />
                    <span className="text-sm text-muted-foreground">
                      I consent to having my voice cloned and stored locally on this server (free,
                      no third-party service). I understand that other users I approve may use this
                      voice for text-to-speech responses. I can revoke access or delete my voice
                      profile at any time.
                    </span>
                  </label>

                  {data?.clone_engine_available && (
                    <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 space-y-2">
                      <div className="text-xs font-semibold uppercase tracking-wider text-primary">
                        📝 Read this aloud when you click Record
                      </div>
                      <p className="text-sm text-foreground/90 leading-relaxed">
                        "Hello! This is my voice. My name is Venky, and I love building
                        things with technology. Today is a wonderful day, and I'm excited
                        to talk with my AI companion. The weather is beautiful, the sun is
                        shining, and I feel happy and motivated to learn something new."
                      </p>
                      <p className="text-xs text-muted-foreground">
                        Speak clearly and naturally for 8–10 seconds. This helps the AI capture
                        your voice tone, pitch, and speaking style accurately.
                      </p>
                    </div>
                  )}

                  <div className="flex flex-wrap items-center gap-3">
                    <Button
                      onClick={recording ? stopRecording : startRecording}
                      disabled={!consent || uploading || !data?.clone_engine_available}
                      title={
                        data?.clone_engine_available
                          ? undefined
                          : "Voice cloning engine is not available — see the notice above."
                      }
                      className="bg-gradient-primary text-primary-foreground shadow-glow"
                    >
                      {recording ? (
                        <>
                          <Square className="h-4 w-4 mr-2 fill-current" /> Stop ({recordSeconds}s)
                        </>
                      ) : uploading ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Cloning…
                        </>
                      ) : (
                        <>
                          <Mic className="h-4 w-4 mr-2" /> Record sample
                        </>
                      )}
                    </Button>
                    {recording && (
                      <span className="text-xs text-primary font-medium animate-pulse">
                        🔴 Recording... {recordSeconds}s / {MAX_RECORD_SECONDS}s
                      </span>
                    )}
                    {!recording && !uploading && data?.clone_engine_available && (
                      <span className="text-xs text-muted-foreground">
                        Click Record, then read the sentence above out loud.
                      </span>
                    )}
                  </div>
                </div>
              ) : (
                <div className="space-y-5">
                  <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-xl border bg-card/50">
                    <div className="flex items-center gap-3">
                      <div className="h-10 w-10 rounded-full bg-gradient-primary shadow-glow flex items-center justify-center shrink-0">
                        <Sparkles className="h-5 w-5 text-primary-foreground" />
                      </div>
                      <div>
                        <div className="font-medium">Your voice is cloned</div>
                        <div className="text-xs text-muted-foreground">
                          Powered by OmniVoice — free, local, 600+ languages. Only people you approve can use
                          it.
                        </div>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        onClick={() => onPreviewVoice(myProfileId)}
                        disabled={previewingId === myProfileId}
                      >
                        {previewingId === myProfileId ? (
                          <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                        ) : (
                          <Play className="h-4 w-4 mr-1.5" />
                        )}
                        {previewingId === myProfileId ? "Preparing…" : "Preview"}
                      </Button>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="destructive" disabled={deleting}>
                            {deleting ? (
                              <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                            ) : (
                              <Trash2 className="h-4 w-4 mr-1.5" />
                            )}
                            Delete
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Delete your cloned voice?</AlertDialogTitle>
                            <AlertDialogDescription>
                              This removes your voice profile and immediately revokes access for
                              everyone who was approved. This cannot be undone — you would need to
                              record a new sample to clone your voice again.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Keep it</AlertDialogCancel>
                            <AlertDialogAction
                              onClick={onDeleteProfile}
                              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                            >
                              {deleting ? (
                                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                              ) : (
                                <Trash2 className="h-4 w-4 mr-1.5" />
                              )}
                              Delete my voice
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </div>

                  <div>
                    <div className="text-sm font-medium mb-2">People with access</div>
                    {grantees.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        No one has requested access yet. Others can find your voice in their
                        "Request Access" search.
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {grantees.map((g) => (
                          <div
                            key={g.permission_id}
                            className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg border bg-card/50"
                          >
                            <div className="flex items-center gap-3">
                              <Avatar className="h-9 w-9">
                                <AvatarFallback>{(g.user_name || "?")[0]}</AvatarFallback>
                              </Avatar>
                              <div>
                                <div className="text-sm font-medium">{g.user_name}</div>
                                <div className="text-xs text-muted-foreground">
                                  {g.status === "pending" ? "Waiting for your approval" : `Permission ${g.permission_id}`}
                                </div>
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              {statusBadge(g.status)}
                              {g.status === "pending" && (
                                <Button
                                  size="sm"
                                  onClick={() => onApprove(g.permission_id)}
                                  disabled={updatingId === g.permission_id}
                                >
                                  {updatingId === g.permission_id ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <Check className="h-3.5 w-3.5 mr-1" />
                                  )}
                                  Approve
                                </Button>
                              )}
                              {g.status !== "revoked" && (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => onRevoke(g.permission_id)}
                                  disabled={updatingId === g.permission_id}
                                >
                                  {updatingId === g.permission_id ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <Trash2 className="h-3.5 w-3.5 mr-1" />
                                  )}
                                  Revoke
                                </Button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </section>

            {/* ---------------------------------------------------------------
                REQUEST ACCESS (discovery)
                --------------------------------------------------------------- */}
            <section className="glass border rounded-2xl p-6 space-y-4">
              <div>
                <h2 className="font-display font-semibold text-xl">Request Access</h2>
                <p className="text-sm text-muted-foreground mt-1">
                  Find other people&apos;s cloned voices and ask to use them in your calls.
                </p>
              </div>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="pl-9"
                  placeholder="Search by name…"
                />
              </div>
              {searching ? (
                <div className="space-y-2">
                  <Skeleton className="h-14 rounded-lg" />
                  <Skeleton className="h-14 rounded-lg" />
                </div>
              ) : discover && discover.length > 0 ? (
                <div className="space-y-2">
                  {discover.map((p) => (
                    <div
                      key={p.voice_profile_id}
                      className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg border bg-card/50"
                    >
                      <div className="flex items-center gap-3">
                        <Avatar className="h-9 w-9">
                          <AvatarFallback>{(p.owner_name || "?")[0]}</AvatarFallback>
                        </Avatar>
                        <div>
                          <div className="text-sm font-medium">{p.owner_name}</div>
                          <div className="text-xs text-muted-foreground">
                            Cloned voice · available
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {statusBadge(p.my_status)}
                        {p.my_status === "approved" ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => onPreviewVoice(p.voice_profile_id)}
                            disabled={previewingId === p.voice_profile_id}
                          >
                            {previewingId === p.voice_profile_id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Volume2 className="h-3.5 w-3.5 mr-1" />
                            )}
                            Preview
                          </Button>
                        ) : p.my_status === "pending" ? null : (
                          <Button
                            size="sm"
                            onClick={() => onRequestAccess(p.voice_profile_id)}
                            disabled={requestingId === p.voice_profile_id}
                          >
                            {requestingId === p.voice_profile_id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <UserPlus className="h-3.5 w-3.5 mr-1" />
                            )}
                            Request
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : discover && discover.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-6">
                  No cloned voices found. Clone your own voice above so others can find you!
                </p>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-6">
                  Searching…
                </p>
              )}
            </section>

            {/* ---------------------------------------------------------------
                VOICES I CAN USE
                --------------------------------------------------------------- */}
            <section className="glass border rounded-2xl p-6 space-y-4">
              <div>
                <h2 className="font-display font-semibold text-xl">Voices I can use</h2>
                <p className="text-sm text-muted-foreground mt-1">
                  Access you&apos;ve been granted on other people&apos;s cloned voices. Approved
                  voices are available in the Voice Library under &quot;Request Access&quot;.
                </p>
              </div>
              {voicesICanUse.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  You don&apos;t have access to any other voices yet. Search above and request
                  access.
                </p>
              ) : (
                <div className="space-y-2">
                  {voicesICanUse.map((v) => (
                    <div
                      key={v.permission_id}
                      className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg border bg-card/50"
                    >
                      <div className="flex items-center gap-3">
                        <Avatar className="h-9 w-9">
                          <AvatarFallback>{(v.owner_name || "?")[0]}</AvatarFallback>
                        </Avatar>
                        <div>
                          <div className="text-sm font-medium">{v.owner_name}</div>
                          <div className="text-xs text-muted-foreground">
                            {v.status === "approved"
                              ? "You can use this voice in calls"
                              : v.status === "pending"
                                ? "Awaiting the owner's approval"
                                : "Access was revoked"}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {statusBadge(v.status)}
                        {v.status === "approved" && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => onPreviewVoice(v.voice_profile_id)}
                            disabled={previewingId === v.voice_profile_id}
                          >
                            {previewingId === v.voice_profile_id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Volume2 className="h-3.5 w-3.5 mr-1" />
                            )}
                            Preview
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </AppShell>
  );
}
