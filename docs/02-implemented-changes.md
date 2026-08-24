# 02 — What We Implemented

Everything in this file was **built and tested live** in the August 8, 2026 session.

---

## 1. 🎭 Emotion-Aware AI (the app finally matches its tagline!)

The AI now **detects how you feel** and adapts its tone — and the spoken voice — to your mood.

- **Detected emotions:** `happy`, `sad`, `angry`, `anxious`, `excited`, `tired`, `neutral`
- **How detection works:** long messages → Groq fast model (`llama-3.1-8b-instant`); short messages → free offline keyword check (instant, no cost). If Groq fails, it falls back to the keyword check (never breaks).
- **Effect on replies:** a "mood awareness" instruction is added to the AI's system prompt (e.g. user is sad → reply warm and gentle).
- **Effect on voice calls:** the spoken reply is subtly slower/softer for sad, faster/brighter for excited, etc.
- **Visible in the UI:** a mood pill (emoji + label) appears in the **Chat** and **Call** screens.

**Verified live:** message *"I got promoted at work today!"* → detected `happy` ✅
message *"I am so excited, we are going to Japan next month!"* → detected `excited` ✅

**Files:**
- `backend/chat_service.py` — `classify_emotion()`, `EMOTION_TONES`, `EMOTION_LEXICON`, `emotion_voice_params()`
- `backend/main.py` — `ChatResponse.emotion`, `VoiceChatResponse.emotion`, emotion-tuned TTS in `/voice-chat`
- `frontend/src/lib/emotion.ts` — **NEW** emotion labels/emojis/colors
- `frontend/src/components/emotion-pill.tsx` — **NEW** mood pill component
- `frontend/src/routes/chat.tsx` — shows mood pill
- `frontend/src/routes/call.tsx` — shows mood pill, resets on new recording

---

## 2. 🧠 Automatic Memory ("the AI remembers you")

After every conversation, the AI **automatically extracts durable facts about you** and saves them — no manual typing needed.

- Runs **in the background** so replies are never slowed down.
- Saves up to 3 facts per message, **deduplicated** (no repeats).
- Capped at **60 auto-memories** (oldest removed).
- Shown in Profile → "What I remember" with an **auto** badge so you know which facts were saved automatically.
- Auto-facts also feed the AI's memory in future chats.

**Verified live:** message *"My name is Alex Rivera. I work as a nurse."* → auto-saved *"The user's name is Alex"*, *"The user works as a nurse"* ✅

**Files:**
- `backend/chat_service.py` — `extract_facts()`, `save_auto_memories()`, `schedule_memory_extraction()`
- `frontend/src/routes/profile.tsx` — "auto" badge + updated description

---

## 3. ⚡ Streaming Chat (replies type out live)

The chat screen now streams the AI reply **word-by-word** instead of waiting for the whole answer.

- New backend endpoint **`POST /chat/stream`** (Server-Sent Events): sends `emotion` → `token` events → `done`.
- Frontend streams tokens into the chat bubble in real time.
- **Automatic fallback:** if streaming fails, it silently uses the old `POST /chat`.
- The typing indicator hides once the first token arrives.
- Pressing Enter while a reply is streaming is ignored (no double-send).
- Stream is cancelled if you leave the page mid-reply.

**Verified live:** streaming endpoint returned emotion + 39 token events + done ✅

**Files:**
- `backend/main.py` — `POST /chat/stream` endpoint
- `backend/chat_service.py` — `stream_chat_reply()` (Groq streaming)
- `frontend/src/routes/chat.tsx` — streaming + fallback + AbortController

---

## 4. 🔑 Forgot Password

- New **"Forgot password?"** link on the login screen.
- Opens a dialog → enter email → Firebase sends a reset link.
- Friendly error messages (e.g. "No account found with that email.").

**Files:**
- `frontend/src/routes/index.tsx` — reset dialog
- `frontend/src/lib/firebase.ts` — `sendPasswordResetEmail()` + `resetPasswordErrorMessage()`

---

## 5. 🐛 Bug Fixes

| Bug | Fix |
|-----|-----|
| History screen 401 | `frontend/src/routes/history.tsx` — now sends the auth token on `GET /history` |
| Profile screen 401 | `frontend/src/routes/profile.tsx` — now sends the auth token on `GET /profile` |
| Custom name overwritten by email | `backend/crud.py` — `get_or_create_user` no longer overwrites the stored name |

---

## 📄 Docs updated

- `README.md` — API contract now documents `/chat/stream`, the `emotion` field, and auto-memory.

---

## 6. 📞 Real-Time Voice Call (no more 30-second waits)

Voice calls moved from a single slow HTTP round-trip to a **duplex WebSocket call** — audio streams up while you talk, and the AI's reply streams back sentence-by-sentence so audio starts playing in seconds.

**Why it was slow before:** the old `/voice-chat` flow uploaded the whole recording, then ran Whisper → full LLM reply → full TTS → base64 download **serially**, and only then played anything.

**What changed:**
- **Tap once and talk** — the mic now auto-stops when you pause (browser-side silence detection via the Web Audio API).
- **Audio streams to the server while you speak** (250 ms MediaRecorder slices over a persistent WebSocket) — no file upload at the end.
- **Live captions** — your words appear as soon as Whisper finishes, and the AI's reply types out as the LLM streams.
- **Streaming speech** — the reply is synthesized sentence-by-sentence (Edge TTS) and played back-to-back as it arrives; first audio lands ~1-2 s after the LLM starts answering.
- **Faster transcription for calls** — `beam_size=1` + `condition_on_previous_text=False` (~2× faster on CPU; the old endpoint keeps its original settings).
- **Cancel support** — "End call" aborts an in-flight turn; the socket stays open for the next call.
- Cloned voices (XTTS) still synthesize in one shot (the local engine is too slow for per-sentence streaming); built-in voices get the full streaming treatment.

**Files:**
- `backend/voice_call_ws.py` — **NEW** WebSocket handler: protocol, `split_sentences()`, `resolve_voice_config()`, streaming turn loop
- `backend/main.py` — **NEW** `WS /ws/voice-call` route (token via `?token=`), `verify_firebase_token_str()`, `/voice-chat` now reuses `resolve_voice_config()`
- `backend/voice_service.py` — `transcribe_audio()` accepts `beam_size` / `condition_on_previous_text`
- `frontend/src/routes/call.tsx` — WebSocket client, VAD auto-stop, streaming captions, queued chunk playback, auto-reconnect
- `backend/test_voice_call_ws.py` — **NEW** protocol smoke test (config → ready → transcribe → tokens → audio → done), all passing

**Verified:** `test_voice_call_ws.py` full protocol ✅ · `tsc --noEmit` 0 errors ✅ · `eslint` clean ✅ · backend imports OK ✅

### Follow-up: fast cloud transcription (the 40s → ~4s fix)

Benchmarked on the dev machine: local CPU Whisper (`small`) took **39.4s** to transcribe a 4s clip — the entire perceived delay. Voice calls now transcribe with **Groq's hosted Whisper** (`whisper-large-v3-turbo`, same `GROQ_API_KEY`) in **~2.8s (14× faster)**, falling back to local Whisper only if the key is missing or the request fails. Call turns also skip the extra Groq emotion round-trip (`fast_emotion=True`, instant offline lexicon).

- `backend/voice_service.py` — `transcribe_audio_groq()` (new)
- `backend/voice_call_ws.py` — Groq-first transcription + `fast_emotion=True`
- `backend/chat_service.py` — `stream_chat_reply(fast_emotion=...)`
- `backend/main.py` — `/voice-chat` also uses Groq-first transcription
- `backend/bench_stt.py` — **NEW** benchmark script (re-run anytime: `voice-venv/Scripts/python.exe bench_stt.py`)

Free-tier note: Groq STT allows 20 requests/min — beyond that, calls fall back to local Whisper.

### Follow-up: Telugu/Hindi mis-transcription fixed (language hint)

Reproduced the bug live: Groq Whisper with auto language detection transcribed real Telugu speech as **Tamil** (`நமச்காரம்!...`) — exactly what the user saw in the call history. With `language="te"` the same audio transcribed correctly (`నమస్కారం...`).

- The Call screen now has a **language picker** (Auto · English · हिन्दी · తెలుగు), remembered in localStorage (`voicelink.language`) and sent to the backend over the call WebSocket.
- The backend passes the chosen language to Groq STT as the `language` hint, so Whisper stops guessing wrong.
- In **Auto** mode, the call session locks onto Hindi/Telugu after the first turn that transcribes in that script (self-correcting within a call).
- The AI system prompt now pins the reply language: once the user picks Telugu, the AI **always replies in Telugu** even if a transcription is garbled — no more "you said Telugu, why Tamil input?".
- `/voice-chat` also accepts a `language` query param.

**Files:** `backend/voice_call_ws.py`, `backend/chat_service.py` (`build_system_prompt(language=...)`, `LANGUAGE_NAMES`), `backend/main.py`, `frontend/src/routes/call.tsx`. Verified with `bench_telugu_stt.py` (auto-detect ✗ → `language=te` ✓).

---

## ✅ Verification summary (all passed)

- **32 live API end-to-end tests** (chat, streaming, voice round-trip, memory, history, profile, settings, auth errors)
- `tsc --noEmit` → 0 errors
- `vite build` → success
- Browser check → no console errors
