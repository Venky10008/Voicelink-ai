import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { PhoneOff, Eye, EyeOff, Trash2, AlertTriangle, RotateCw } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CompanionAvatar } from "@/components/companion-avatar";
import { useActiveSelection } from "@/hooks/use-active-selection";
import { personalityStyle, voiceTone, TONE_BAR } from "@/lib/companion-style";
import { API_BASE_URL } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { EmotionPill } from "@/components/emotion-pill";

export const Route = createFileRoute("/call")({ component: CallPage });

type CallState = "idle" | "listening" | "transcribing" | "thinking" | "speaking";

export type Caption = { id: string; role: "user" | "ai"; text: string; at: string };

/**
 * Events the backend streams back over the call WebSocket.
 * See backend/voice_call_ws.py for the full protocol.
 */
type WsEvent =
  | { type: "ready" }
  | {
      type: "status";
      state: "listening" | "transcribing" | "thinking" | "speaking" | "idle";
      transcript?: string;
    }
  | { type: "token"; content: string }
  | { type: "audio"; audio_base64: string; mime: string }
  | { type: "voice_fallback_notice"; detail: string }
  | { type: "done"; emotion?: string; fresh_start?: boolean; notice?: string | null }
  | { type: "error"; detail: string }
  | { type: "pong" };

type CallConfig = {
  voice_profile_id?: number;
  voice_id?: string;
  personality?: string;
  /** Reply language lock ("en"/"hi"/"te"/"ta") — backend auto-detects when unset. */
  language?: string;
};

// --- Hands-free call tuning (continuous VAD + barge-in) --------------------
const VAD_TICK_MS = 100; // how often we sample the mic level
const RECORDER_TIMESLICE_MS = 200; // MediaRecorder chunk size

/** Best supported webm flavour (browser-only — do not call during SSR). */
const recorderMime = () => {
  if (typeof MediaRecorder === "undefined") return "audio/webm";
  return MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
    ? "audio/webm;codecs=opus"
    : "audio/webm";
};
const VAD_RMS_THRESHOLD = 0.02;        // volume level that counts as "speaking"
const VAD_BARGE_IN_THRESHOLD = 0.05;   // higher bar while the AI is talking (echo) — raised to reduce false barge-ins
const VAD_ONSET_FRAMES = 3;            // frames of voice to declare speech start (was 2)
const VAD_BARGE_IN_FRAMES = 5;         // sustained frames needed to interrupt a reply (was 3)
const VAD_SILENCE_LIMIT_MS = 2200;     // pause this long and the utterance ends (was 1600) — gives more natural pausing
const VAD_MIN_SEGMENT_MS = 1200;       // shorter "utterances" are noise — discard (was 600)
const VAD_MAX_SEGMENT_MS = 20000;      // hard cap — never hold audio forever
// After the AI finishes speaking, ignore VAD onset for this many ms so room
// echo / reverb cannot trigger a phantom utterance.
const VAD_POST_REPLY_COOLDOWN_MS = 900;

function CallPage({ initialTranscript = [] as Caption[] }: { initialTranscript?: Caption[] }) {
  const [state, setState] = useState<CallState>("idle");
  const [transcript, setTranscript] = useState<Caption[]>(initialTranscript);
  const [emotion, setEmotion] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(true);
  const [pending, setPending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const playQueueRef = useRef<{ url: string }[]>([]);
  const playingRef = useRef(false);
  const hardMuteRef = useRef(false);
  const vadTimerRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const callEndedRef = useRef(false);
  const mountedRef = useRef(true);
  const stateRef = useRef<CallState>("idle");
  const configRef = useRef<CallConfig | null>(null);
  // --- hands-free call state (mic stays on until the call ends) ---
  const inCallRef = useRef(false);
  // Each utterance is recorded by its OWN MediaRecorder session, so every
  // blob the backend receives is a complete, valid webm file (header + all).
  // Stitching chunks from one long session breaks the webm format.
  const utteranceRecorderRef = useRef<MediaRecorder | null>(null);
  const utteranceCtlRef = useRef<{ mark: (send: boolean) => void } | null>(null);
  const segmentStartRef = useRef(0); // when the current speech segment began
  const vadSpeakingRef = useRef(false); // VAD: user's voice is present
  const vadFramesRef = useRef(0); // consecutive voice frames (debounce)
  const lastVoiceRef = useRef(0); // last frame that contained voice
  // Timestamp until which VAD onset detection is suppressed (post-reply cooldown).
  // Prevents room echo/reverb from triggering a phantom utterance right after the AI speaks.
  const vadCooldownUntilRef = useRef(0);
  const aiStreamRef = useRef<{ id: string; text: string } | null>(null);
  const aiFlushScheduledRef = useRef(false);
  const { token } = useAuth();
  const {
    voice,
    personality,
    loading: voiceLoading,
    error: selectionError,
    retry: retrySelection,
  } = useActiveSelection();

  const voiceReady = !voiceLoading && !selectionError && !!voice;
  const avatarStyle = personalityStyle(personality);
  const tone = voiceTone(voice);

  const current = transcript[transcript.length - 1] ?? null;
  const history = transcript.slice(0, -1);
  const visible = showHistory ? transcript : current ? [current] : [];

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  // Auto-scroll to newest caption
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [transcript, showHistory, state]);

  // ---------------------------------------------------------------------------
  // Playback — plays TTS chunks back-to-back as they stream in
  // ---------------------------------------------------------------------------

  const clearPlayQueue = () => {
    playQueueRef.current.forEach((item) => URL.revokeObjectURL(item.url));
    playQueueRef.current = [];
  };

  const playNextInQueue = () => {
    if (playingRef.current) return;
    const next = playQueueRef.current.shift();
    if (!next) {
      // All audio finished — unmute VAD after a short delay so the last
      // sentence's reverb doesn't trigger a phantom utterance.
      if (hardMuteRef.current) {
        window.setTimeout(() => {
          hardMuteRef.current = false;
        }, 400);
      }
      setState((s) => (s === "speaking" ? "idle" : s));
      return;
    }
    // Mute VAD the moment TTS audio starts playing.
    hardMuteRef.current = true;
    playingRef.current = true;
    const audio = new Audio(next.url);
    audioRef.current = audio;
    setState("speaking");
    const finish = () => {
      URL.revokeObjectURL(next.url);
      audioRef.current = null;
      playingRef.current = false;
      playNextInQueue();
    };
    audio.onended = finish;
    audio.onerror = finish;
    audio.play().catch(finish);
  };

  const enqueueAudio = (base64: string, mime: string) => {
    try {
      const binary = atob(base64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const blob = new Blob([bytes], { type: mime || "audio/mpeg" });
      playQueueRef.current.push({ url: URL.createObjectURL(blob) });
      playNextInQueue();
    } catch {
      // Skip a bad chunk rather than killing the whole reply.
    }
  };

  const stopPlayback = () => {
    audioRef.current?.pause();
    audioRef.current = null;
    playingRef.current = false;
    hardMuteRef.current = false;
    clearPlayQueue();
  };

  // ---------------------------------------------------------------------------
  // Live captions — the AI caption grows as LLM tokens stream in
  // ---------------------------------------------------------------------------

  const flushAiCaption = () => {
    const cur = aiStreamRef.current;
    if (!cur) return;
    const text = cur.text;
    setTranscript((t) => t.map((c) => (c.id === cur.id ? { ...c, text } : c)));
  };

  const scheduleAiFlush = () => {
    if (aiFlushScheduledRef.current) return;
    aiFlushScheduledRef.current = true;
    requestAnimationFrame(() => {
      aiFlushScheduledRef.current = false;
      flushAiCaption();
    });
  };

  // ---------------------------------------------------------------------------
  // WebSocket message handling
  // ---------------------------------------------------------------------------

  function handleWsEvent(payload: WsEvent) {
    if (callEndedRef.current) return; // user ended the call — ignore late events
    switch (payload.type) {
      case "status": {
        // The backend attaches the transcript once transcription finishes, so
        // the user's caption appears as soon as their words are understood.
        const transcriptText = payload.transcript;
        if (transcriptText) {
          setTranscript((t) => [
            ...t,
            {
              id: crypto.randomUUID(),
              role: "user",
              text: transcriptText,
              at: new Date().toISOString(),
            },
          ]);
        }
        // The mic stays on for the whole call, so a server "idle" simply
        // means the mic is listening again — never leave the call.
        setState(
          payload.state === "transcribing"
            ? "transcribing"
            : payload.state === "thinking"
              ? "thinking"
              : payload.state === "speaking"
                ? "speaking"
                : payload.state === "listening" || inCallRef.current
                  ? "listening"
                  : "idle",
        );
        break;
      }
      case "token": {
        if (!aiStreamRef.current) {
          const id = crypto.randomUUID();
          aiStreamRef.current = { id, text: "" };
          setTranscript((t) => [...t, { id, role: "ai", text: "", at: new Date().toISOString() }]);
        }
        aiStreamRef.current.text += payload.content;
        scheduleAiFlush();
        break;
      }
      case "audio": {
        enqueueAudio(payload.audio_base64, payload.mime);
        break;
      }
      case "done": {
        flushAiCaption();
        aiStreamRef.current = null;
        if (payload.emotion) setEmotion(payload.emotion);
        if (payload.fresh_start) {
          setTranscript([]);
          toast(payload.notice ?? "Your call history was reset for a fresh start.");
        }
        // Arm the post-reply cooldown: suppress VAD onset for a short window so
        // room echo / reverb from the AI's own playback cannot trigger a new
        // phantom utterance (the leading cause of the "AI heard 'Thank you'" bug).
        vadCooldownUntilRef.current = Date.now() + VAD_POST_REPLY_COOLDOWN_MS;
        // If the reply produced no playable audio, settle back to listening
        // (the call itself never ends until the user hangs up). Either way,
        // start a fresh recorder so the next utterance is captured cleanly
        // (without the reply audio that just played).
        if (inCallRef.current) startUtteranceRecorder();
        window.setTimeout(() => {
          if (playQueueRef.current.length === 0 && !playingRef.current) {
            setState(inCallRef.current ? "listening" : "idle");
          }
        }, 300);
        break;
      }
      case "voice_fallback_notice": {
        toast(payload.detail);
        break;
      }
      case "error": {
        aiStreamRef.current = null;
        stopPlayback();
        // A failed turn shouldn't hang up a live call — go back to listening
        // and arm a fresh recorder for the next utterance.
        if (inCallRef.current) startUtteranceRecorder();
        setState(inCallRef.current ? "listening" : "idle");
        toast.error(payload.detail);
        break;
      }
      case "ready":
      case "pong":
        break;
    }
  }

  // ---------------------------------------------------------------------------
  // WebSocket lifecycle
  // ---------------------------------------------------------------------------

  const openSocket = (idToken: string) => {
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }
    wsRef.current?.close();
    const base = API_BASE_URL.replace(/^http/, "ws");
    const ws = new WebSocket(`${base}/ws/voice-call?token=${encodeURIComponent(idToken)}`);
    wsRef.current = ws;

    ws.onopen = () => {
      if (configRef.current) {
        ws.send(JSON.stringify({ type: "config", ...configRef.current }));
      }
    };
    ws.onmessage = (event) => {
      let payload: WsEvent;
      try {
        payload = JSON.parse(event.data as string) as WsEvent;
      } catch {
        return;
      }
      // A handler bug must never break the socket callback mid-call.
      try {
        handleWsEvent(payload);
      } catch (err) {
        console.error("[voice-call] failed to handle server event", err);
      }
    };
    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null;
      if (!mountedRef.current) return; // navigated away — don't touch state/toast
      stopPlayback();
      hardMuteRef.current = false;
      setPending(false);
      if (stateRef.current !== "idle") {
        inCallRef.current = false;
        stopRecording();
        setState("idle");
        toast.error("Call connection lost. Tap the mic to reconnect.");
      }
    };
    ws.onerror = () => ws.close();
  };

  /** Opens the socket if needed and resolves once it's ready to send audio. */
  const ensureSocket = (idToken: string): Promise<boolean> =>
    new Promise((resolve) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        resolve(true);
        return;
      }
      openSocket(idToken);
      const target = wsRef.current;
      if (!target) {
        resolve(false);
        return;
      }
      const startedAt = Date.now();
      const check = () => {
        if (target.readyState === WebSocket.OPEN) resolve(true);
        else if (target.readyState === WebSocket.CLOSED || Date.now() - startedAt > 4000) {
          resolve(false);
        } else {
          window.setTimeout(check, 50);
        }
      };
      check();
    });

  // NOTE: the socket is NOT opened on mount. The auth token is refreshed
  // from Firebase right after page load, so opening the socket immediately
  // could hand the backend a stale token. The socket connects lazily on the
  // first mic tap (see ensureSocket in startCall) with a fresh token.

  // Keep the backend's voice/personality config in sync. The spoken language
  // is left unset so the backend auto-detects it from each utterance.
  useEffect(() => {
    if (!voiceReady) return;
    const cfg: CallConfig = {};
    if (voice?.voiceProfileId) cfg.voice_profile_id = Number(voice.voiceProfileId);
    else if (voice?.id) cfg.voice_id = voice.id;
    if (personality?.id) cfg.personality = personality.id;
    // Lock the language to English from turn 1 so Whisper auto-detect
    // cannot drift to Hindi/Telugu/Tamil and cause the LLM to reply
    // in the wrong language.
    cfg.language = "en";
    configRef.current = cfg;
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "config", ...cfg }));
    }
  }, [voice, personality, voiceReady]);

  // ---------------------------------------------------------------------------
  // Recording — streams chunks up while talking, auto-stops on silence (VAD)
  // ---------------------------------------------------------------------------

  const stopVad = () => {
    if (vadTimerRef.current !== null) {
      window.clearInterval(vadTimerRef.current);
      vadTimerRef.current = null;
    }
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
  };

  /** Starts a fresh recorder session for the next utterance.
   *
   * The recorder runs from this moment until the utterance ends, so its file
   * naturally includes the silence before speech (which Whisper trims) — no
   * audio splicing, and the very first words are always captured. */
  const startUtteranceRecorder = () => {
    const stream = streamRef.current;
    if (!stream) return;
    // One recorder at a time — stop any leftover session first.
    if (utteranceRecorderRef.current?.state === "recording") {
      utteranceRecorderRef.current.stop();
    }
    const chunks: Blob[] = [];
    let shouldSend = false;
    // Creating a recorder can throw in unsupported browsers — a failed
    // recorder must never take the call down.
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType: recorderMime() });
    } catch (err) {
      console.error("[voice-call] MediaRecorder unavailable", err);
      return;
    }
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    recorder.onstop = () => {
      if (utteranceRecorderRef.current === recorder) utteranceRecorderRef.current = null;
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || !shouldSend || chunks.length === 0) {
        return;
      }
      // One complete, valid webm file — header + all chunks in order.
      try {
        ws.send(new Blob(chunks, { type: "audio/webm" }));
        ws.send(JSON.stringify({ type: "end_utterance" }));
      } catch {
        // the socket closed between the state check and the send — ignore
      }
    };
    try {
      recorder.start(RECORDER_TIMESLICE_MS);
    } catch (err) {
      console.error("[voice-call] recorder failed to start", err);
      return;
    }
    utteranceRecorderRef.current = recorder;
    utteranceCtlRef.current = {
      mark: (send: boolean) => {
        shouldSend = send;
      },
    };
  };

  /** The user spoke while the AI was replying — cut it off and take the floor. */
  const bargeIn = () => {
    stopPlayback();
    flushAiCaption();
    aiStreamRef.current = null;
    setEmotion(null);
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "cancel" }));
    }
    // Capture the interruption with a fresh recorder session (the previous
    // one already ended its utterance).
    utteranceCtlRef.current?.mark(false);
    if (utteranceRecorderRef.current?.state === "recording") {
      utteranceRecorderRef.current.stop();
    }
    startUtteranceRecorder();
    setState("listening");
  };

  /** Speech detected — note when the segment began (recorder already running). */
  const beginSegment = () => {
    segmentStartRef.current = Date.now();
    setState("listening");
  };

  /** Speech ended (or hit the cap) — stop the recorder and ship the utterance. */
  const endSegment = () => {
    const ws = wsRef.current;
    const recorder = utteranceRecorderRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !recorder || recorder.state !== "recording") {
      return;
    }
    const duration = Date.now() - segmentStartRef.current;
    if (duration < VAD_MIN_SEGMENT_MS) {
      // Too short to be real speech (a cough, a tap) — drop the file silently
      // and start a fresh session so the next utterance is captured.
      utteranceCtlRef.current?.mark(false);
      recorder.stop();
      startUtteranceRecorder();
      return;
    }
    utteranceCtlRef.current?.mark(true);
    setState("thinking");
    recorder.stop(); // onstop sends the blob + end_utterance
  };

  const startVad = (stream: MediaStream) => {
    try {
      const Ctx =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new Ctx();
      ctx.resume().catch(() => {}); // iOS requires a user-gesture resume
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.3;
      source.connect(analyser);
      audioCtxRef.current = ctx;

      const data = new Uint8Array(analyser.fftSize);
      vadTimerRef.current = window.setInterval(() => {
        try {
          analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) {
            const v = (data[i] - 128) / 128;
            sum += v * v;
          }
          const rms = Math.sqrt(sum / data.length);
          const now = Date.now();
          const st = stateRef.current;
          const aiReplying = st === "speaking" || st === "thinking" || st === "transcribing";
          // While the AI is talking the mic hears its own voice (echo), so
          // interrupting needs a louder signal sustained over more frames.
          // Hard mute: while AI audio is playing, skip VAD processing entirely.
          if (hardMuteRef.current) {
            vadSpeakingRef.current = false;
            vadFramesRef.current = 0;
            return;
          }
          const threshold = aiReplying ? VAD_BARGE_IN_THRESHOLD : VAD_RMS_THRESHOLD;
          const onsetFrames = aiReplying ? VAD_BARGE_IN_FRAMES : VAD_ONSET_FRAMES;

          if (rms > threshold) {
            lastVoiceRef.current = now;
            vadFramesRef.current += 1;
          } else {
            vadFramesRef.current = 0;
          }

          if (!vadSpeakingRef.current) {
            // During the post-reply cooldown window, ignore onset detection so
            // echo / room noise right after the AI speaks doesn't create a
            // phantom utterance. Barge-in (interruption) still works normally.
            const inCooldown = now < vadCooldownUntilRef.current;
            if (vadFramesRef.current >= onsetFrames && (!inCooldown || aiReplying)) {
              vadSpeakingRef.current = true;
              if (aiReplying) bargeIn();
              beginSegment();
            }
          } else if (
            now - lastVoiceRef.current >= VAD_SILENCE_LIMIT_MS ||
            now - segmentStartRef.current >= VAD_MAX_SEGMENT_MS
          ) {
            vadSpeakingRef.current = false;
            endSegment();
          }
        } catch (err) {
          // One bad VAD tick must never kill the interval (or the call).
          console.error("[voice-call] VAD tick failed", err);
        }
      }, VAD_TICK_MS);
    } catch {
      // VAD unavailable in this browser — the mic button still starts/stops
      // the call; speech just can't be auto-detected.
    }
  };

  const stopRecording = () => {
    stopVad();
    vadSpeakingRef.current = false;
    utteranceCtlRef.current?.mark(false); // never send a partial utterance
    const recorder = utteranceRecorderRef.current;
    if (recorder && recorder.state === "recording") recorder.stop();
    utteranceRecorderRef.current = null;
    utteranceCtlRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  };

  /** Tap the mic once — the call stays open and hands-free until you hang up. */
  const startCall = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      toast.error("Microphone recording is not supported in this browser.");
      return;
    }
    stopPlayback();
    setEmotion(null); // a fresh call means a fresh mood to detect
    callEndedRef.current = false; // a new call — accept events again
    setPending(true);
    try {
      const connected = await ensureSocket(token ?? "");
      if (!connected) {
        toast.error("Could not connect to the call. Is the backend running?");
        setState("idle");
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;
      // One recorder session per utterance — the first one starts now and
      // runs until the user's first utterance ends.
      startUtteranceRecorder();
      startVad(stream);
      inCallRef.current = true;
      setState("listening");
    } catch {
      stopRecording();
      setState("idle");
      toast.error("Microphone access denied or unavailable.");
    } finally {
      setPending(false);
    }
  };

  const onEndCall = () => {
    inCallRef.current = false;
    callEndedRef.current = true; // ignore any late audio/tokens from the aborted turn
    stopPlayback();
    stopRecording();
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "cancel" }));
    }
    setEmotion(null);
    setState("idle");
  };

  const onClearTranscript = () => {
    setTranscript([]);
  };

  // Clean up media on unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      inCallRef.current = false;
      stopPlayback();
      stopVad();
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleMic = () => {
    if (pending || !voiceReady) return;
    if (!token) {
      toast.error("You must be signed in to call.");
      return;
    }
    // The mic toggles the whole hands-free call: tap to start, tap to hang up.
    if (inCallRef.current) onEndCall();
    else void startCall();
  };

  const statusText: Record<CallState, string> = {
    idle: "Tap the mic to start the call",
    listening: "Listening — talk anytime",
    transcribing: "Understanding you…",
    thinking: "Thinking…",
    speaking: "Speaking",
  };

  const statusColor: Record<CallState, string> = {
    idle: "text-muted-foreground",
    listening: "text-primary",
    transcribing: "text-amber-400",
    thinking: "text-amber-400",
    speaking: "text-emerald-400",
  };

  // Always tappable while a call is live (it hangs up) — never lock the user
  // out mid-reply.
  const micDisabled = pending || !voiceReady;

  return (
    <AppShell title="Voice Call">
      <div className="min-h-[calc(100vh-4rem)] flex flex-col items-center justify-between p-6 sm:p-10 relative">
        <div className="absolute inset-0 -z-10 overflow-hidden">
          <div className="absolute top-10 left-1/2 -translate-x-1/2 h-[500px] w-[500px] rounded-full bg-primary/20 blur-[120px] animate-float-slow" />
        </div>

        <div className="text-center pt-6 w-full max-w-2xl">
          <div className={`text-sm font-medium uppercase tracking-widest ${statusColor[state]}`}>
            {voiceLoading
              ? "Loading voice…"
              : selectionError
                ? "Voice unavailable"
                : voiceReady
                  ? statusText[state]
                  : "No voice selected"}
          </div>

          {voiceReady && state === "idle" && (
            <p className="mt-1.5 text-xs text-muted-foreground animate-in fade-in">
              Tap once for a hands-free call — just talk, pause, and interrupt the reply anytime.
            </p>
          )}

          {selectionError && (
            <div className="mt-4 flex flex-col sm:flex-row items-center gap-3 rounded-xl border border-destructive/50 bg-destructive/10 px-4 py-3 text-left text-sm animate-in fade-in slide-in-from-top-1">
              <AlertTriangle className="h-4 w-4 text-destructive shrink-0" />
              <span className="flex-1">
                We couldn't load your voice or personality. {selectionError} Listening is disabled
                until this is resolved.
              </span>
              <Button size="sm" variant="outline" className="gap-1.5" onClick={retrySelection}>
                <RotateCw className="h-3.5 w-3.5" /> Retry
              </Button>
            </div>
          )}

          <div className="mt-2 flex flex-wrap items-center justify-center gap-2 text-xs text-muted-foreground">
            {voiceLoading ? (
              <>
                <Skeleton className="h-6 w-40 rounded-full" />
                <Skeleton className="h-6 w-32 rounded-full" />
              </>
            ) : selectionError ? null : voice ? (
              <span className="rounded-full border border-primary/50 bg-primary/10 px-3 py-1 text-foreground">
                Voice · {voice.name}
                {voice.speed ? ` · ${voice.speed.toFixed(2)}x` : ""}
              </span>
            ) : (
              <Link
                to="/voices"
                className="rounded-full border px-3 py-1 hover:text-foreground transition-colors"
              >
                Pick a voice to start the call
              </Link>
            )}
            {!voiceLoading && !selectionError && personality && (
              <span className="rounded-full border px-3 py-1">
                Personality · {personality.name}
              </span>
            )}
            <EmotionPill emotion={emotion} />
          </div>
        </div>

        <div className="relative flex items-center justify-center my-10">
          {state === "listening" && (
            <>
              <div className="absolute inset-0 rounded-full bg-primary/30 animate-pulse-ring" />
              <div
                className="absolute inset-0 rounded-full bg-primary/30 animate-pulse-ring"
                style={{ animationDelay: "0.6s" }}
              />
            </>
          )}
          <button
            onClick={toggleMic}
            disabled={micDisabled}
            aria-pressed={state === "listening"}
            aria-disabled={micDisabled}
            aria-label={
              !voiceReady
                ? "Microphone unavailable — select a voice first"
                : inCallRef.current
                  ? `End the hands-free call. ${personality?.name ?? "Companion"} with ${voice?.name ?? "no"} voice`
                  : `Start a hands-free call. ${personality?.name ?? "Companion"} with ${voice?.name ?? "no"} voice`
            }
            className="relative flex items-center justify-center rounded-full transition-transform active:scale-95 hover:scale-105 disabled:opacity-60 disabled:pointer-events-none focus:outline-none focus-visible:ring-4 focus-visible:ring-ring focus-visible:ring-offset-4 focus-visible:ring-offset-background"
          >
            {voiceLoading ? (
              <Skeleton className="h-40 w-40 sm:h-48 sm:w-48 rounded-full" />
            ) : (
              <CompanionAvatar
                voice={voice}
                personality={personality}
                listening={state === "listening"}
                size={176}
                className="sm:scale-110"
              />
            )}
          </button>
        </div>
        <p aria-live="polite" className="sr-only">
          {voiceLoading
            ? "Loading voice"
            : selectionError
              ? "Voice unavailable"
              : statusText[state]}
        </p>

        {state === "speaking" && (
          <div className="flex items-end gap-1.5 h-16 mb-6" aria-hidden="true">
            {Array.from({ length: 12 }).map((_, i) => (
              <span
                key={i}
                className={`bg-gradient-to-t ${avatarStyle.gradient} ${TONE_BAR[tone]} transition-colors duration-500`}
                style={{
                  height: "100%",
                  animation: `wave 0.9s ease-in-out ${i * 0.08}s infinite`,
                  transformOrigin: "bottom",
                }}
              />
            ))}
          </div>
        )}

        {(state === "transcribing" || state === "thinking") && (
          <div className="flex gap-2 mb-6">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="h-3 w-3 rounded-full bg-amber-400"
                style={{ animation: `typing-dot 1.2s ease-in-out ${i * 0.15}s infinite` }}
              />
            ))}
          </div>
        )}

        {/* Captions */}
        <div className="w-full max-w-2xl">
          <div className="flex items-center justify-between gap-2 mb-2 px-1">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Live captions
              {history.length > 0 && (
                <span className="ml-2 normal-case font-normal">({transcript.length} lines)</span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="gap-1.5 h-8"
                onClick={() => setShowHistory((v) => !v)}
                disabled={history.length === 0}
              >
                {showHistory ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                {showHistory ? "Hide history" : "Show history"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="gap-1.5 h-8 text-destructive hover:text-destructive"
                onClick={onClearTranscript}
                disabled={transcript.length === 0}
              >
                <Trash2 className="h-3.5 w-3.5" /> Clear
              </Button>
            </div>
          </div>

          <div
            ref={scrollRef}
            className="max-h-56 sm:max-h-64 overflow-y-auto space-y-2 pr-1 scroll-smooth"
          >
            {visible.length === 0 && state === "idle" && (
              <p className="text-center text-sm text-muted-foreground py-6">
                Live captions will appear here.
              </p>
            )}

            {visible.map((c) => {
              const isCurrent = current?.id === c.id;
              return (
                <div
                  key={c.id}
                  className={`rounded-2xl px-4 py-3 border transition-all animate-in fade-in slide-in-from-bottom-2 ${
                    isCurrent
                      ? "glass ring-1 ring-primary/60 shadow-glow"
                      : "bg-card/40 border-border/50 opacity-70"
                  }`}
                >
                  <div
                    className={`text-xs mb-1 ${c.role === "ai" ? "text-primary" : "text-muted-foreground"}`}
                  >
                    {c.role === "ai" ? "VoiceLink" : "You"}
                  </div>
                  <div className={`text-sm ${isCurrent ? "font-medium" : ""}`}>
                    {c.text || (isCurrent ? "…" : "")}
                  </div>
                </div>
              );
            })}

            {(state === "listening" || state === "transcribing" || state === "thinking") && (
              <div className="glass border rounded-2xl px-4 py-3 space-y-2">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="h-3.5 w-full" />
                <Skeleton className="h-3.5 w-2/3" />
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </div>

        <div className="mt-8">
          <Button
            variant="destructive"
            size="lg"
            onClick={onEndCall}
            disabled={pending}
            className="rounded-full h-14 px-6 gap-2"
          >
            <PhoneOff className="h-5 w-5" /> End call
          </Button>
        </div>
      </div>
    </AppShell>
  );
}
