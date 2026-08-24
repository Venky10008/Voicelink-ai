# 03 — Voice Call Fixes (hands-free, like ChatGPT voice)

Everything in this file was implemented and verified in the August 15, 2026
session. It fixes the four things that were broken in the call screen.

---

## 1. 🎧 Hands-free call — tap once, then just talk

Before: tap-to-talk — the mic auto-stopped ~1.4 s after you paused, so a short
pause cut you off, and you had to keep tapping the mic every time.

Now: **tap the mic once and the call stays open** (like a real phone call or
ChatGPT voice):

- The mic keeps running the whole call; VAD detects when you speak and when you
  stop, so no re-tapping.
- **Barge-in:** if you talk while the AI is replying, the reply is cut off
  instantly and the AI listens to you (parallel input/output). It takes a
  louder, sustained signal to interrupt while audio is playing so the AI's own
  voice doesn't trigger itself.
- Tap the mic again (or "End call") to hang up.
- **Faster replies:** audio now streams to the server *while you talk*, so the
  moment you pause, transcription starts immediately — no more upload-then-wait.

## 2. 🎤 Hearing fixed — no more words cut from the middle

Before: the first words of an utterance were often lost and the transcript came
out garbled ("taking my words from the middle").

Now:

- **Pre-roll buffer:** ~600 ms of audio before speech onset is included in every
  utterance, so the start of your words is never clipped.
- **Longer pause tolerance:** the utterance only ends after ~1.6 s of silence
  (was 1.4 s and felt even shorter because of the tap-to-talk cutoffs).
- Short/noise segments (a cough, a tap, echo) are detected client-side and
  discarded — they never reach Whisper.

## 3. 🗣️ Language — Telugu/Hindi/English/Tamil, no more mixing

Before: Telugu speech was transcribed as Tamil/Hindi text, the history filled
with those wrong-script transcripts, and the AI replied complaining "we said
Telugu, why are you speaking Tamil?".

Now:

- **Tamil added** to the language picker (Auto · English · हिन्दी · తెలుగు ·
  தமிழ்), Whisper language hinting, script detection, and TTS voices (Pallavi /
  Valluvar in the voice library).
- **The AI is told to never comment on or correct the user's language/spelling**
  — even a garbled transcript just gets a helpful reply in the pinned language.
- **Safer auto-lock:** with Auto selected, the call only locks onto a language
  after *two consecutive turns* agree on the same script (a single wrong guess
  can no longer lock the whole call into Tamil/Hindi).

## 4. ⚡ Backend protocol updated for the hands-free flow

`voice_call_ws.py` now buffers audio continuously and owns utterances
explicitly:

- Every chunk is buffered (even mid-reply — those belong to the next utterance).
- `cancel` aborts the in-flight turn **and** drops the buffered audio so only
  post-interruption audio is used.
- `end_utterance` waits for an in-flight turn to finish before starting the
  next (turns share one DB session and must never overlap).
- New `discard` message drops buffered audio without replying.

**Files:** `backend/voice_call_ws.py`, `backend/voice_service.py`,
`backend/chat_service.py`, `backend/voice_catalog.py`, `backend/main.py`,
`frontend/src/routes/call.tsx`, `backend/test_voice_call_ws.py`.

**Verified:** voice-call WS protocol tests (happy path, barge-in, discard,
ping/pong) ✅ · backend imports ✅ · `tsc --noEmit` 0 errors ✅ · eslint clean ✅
· `vite build` success ✅ · Tamil script detection + voices ✅
