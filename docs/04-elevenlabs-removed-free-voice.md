# 04 — ElevenLabs Removed: 100% Free + Unlimited Voice

Created **August 8, 2026** after the user decided: *"totally remove elevenlabs and
keep alternative unlimited and best."* This project no longer uses ElevenLabs —
**no paid APIs, no credit limits, nothing.**

---

## 🗑️ What was removed

| Where | Before | After |
|-------|--------|-------|
| `backend/.env` | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | **Deleted** — only `GROQ_API_KEY`, `FIREBASE_CREDENTIALS_PATH`, `DATABASE_URL` remain |
| `backend/voice_sharing_router.py` | `_clone_voice_on_elevenlabs()`, `_delete_voice_on_elevenlabs()` (HTTP calls to `api.elevenlabs.io`) | Removed; `record-sample` now clones **locally** via `voice_clone_engine.py` |
| `backend/main.py` `/voice-chat` | Cloned voices silently fell back to the default Edge TTS voice | Cloned voices go through the local XTTS engine, with graceful Edge TTS fallback if the engine isn't installed |
| `backend/models.py` | `elevenlabs_voice_id` column | Renamed to `cloned_voice_key` in code. **The physical DB column keeps its legacy name** (`elevenlabs_voice_id`) so no migration is needed — it now stores a local key |
| `README.md` | ElevenLabs setup guide (§2b), env table, health check, troubleshooting | Replaced with Edge TTS (free, unlimited) + optional local cloning guide |
| `docs/01`, `docs/03` | Marked cloning as "paid / requires ElevenLabs" | Updated to reflect the local free engine |

---

## 🎙️ The two voice engines (both free + unlimited)

### 1. Call voice: Microsoft Edge TTS (`backend/voice_service.py`)
- **Free, unlimited, no API key, no signup, no character caps.**
- Used for `/voice-chat` replies, `/voices/preview`, and every default voice.
- Verified live: `/health` → `"tts_engine": "edge-tts (free, no API key)"`.
- Honest caveat: edge-tts wraps Microsoft's free read-aloud endpoint (unofficial).
  If Microsoft ever locks it down, we swap the engine in one file — the rest of
  the app is untouched.

### 2. Cloned voices: Coqui XTTS v2 (`backend/voice_clone_engine.py`)
- **Free, local, unlimited.** Clones a voice from a short reference recording
  and synthesizes speech with it. No third-party service ever sees the audio.
- Cloned voices are stored as speaker embeddings under
  `backend/data/cloned_voices/` (gitignored).
- **Requirement:** `coqui-tts` needs PyTorch (Python ≤ 3.12). The main backend
  often runs on newer Python, so `engine_available()` returns `False` there and
  calls **gracefully fall back to Edge TTS** — the app never breaks.
- To enable real cloning:
  ```powershell
  cd C:\Users\polav\Desktop\project\backend
  .\voice-venv\Scripts\Activate.ps1        # Python 3.11 venv (already exists)
  pip install coqui-tts                    # downloads torch + model (~4 GB)
  ```
  Then run the backend from `voice-venv` (Python 3.11) so the engine loads.
- Hardware note: on the RTX 2050 (4 GB VRAM) XTTS works but takes ~2–5 s per
  sentence; set `XTTS_GPU=0` to force CPU. Override the model with `XTTS_MODEL`.
- **Windows torchcodec fix (verified live 2026-08-08):** torchaudio ≥ 2.9 routes
  WAV loading through torchcodec, whose FFmpeg DLLs fail to load on this machine
  (`Could not load libtorchcodec ... libtorchcodec_core4.dll`).
  `voice_clone_engine._patch_xtts_audio_loading()` swaps XTTS's `load_audio` for a
  `soundfile` (libsndfile) implementation — cloning + synthesis now run end-to-end.
  Full pipeline verified: clone ≈45 s + synthesize ≈17 s on CPU.

---

## 📋 Why Pipecat / Voicebox were NOT chosen

| Option | Verdict |
|--------|---------|
| **Meta Voicebox** | ❌ Never released publicly (research paper only) — cannot be integrated |
| **Pipecat** | ⚠️ Great for *real-time hands-free* conversations (WebSocket/WebRTC), but a big rewrite for this app's press-to-talk flow. Revisit if we add always-on voice |
| **ElevenLabs** | ❌ Removed — free tier is only ~10k chars/month; cloning needs a paid plan |

---

## ✅ What to verify after this change

- `/health` shows `tts_engine: "edge-tts (free, no API key)"` and
  `voice_clone_engine: "xtts-v2 (local, free)"` when the backend runs from
  `backend/voice-venv` (Python 3.11 — coqui-tts 0.27.5 + torch installed, XTTS v2
  model already downloaded). Verified live 2026-08-08.
- Voice calls still produce audio with the default Edge TTS voice.
- `POST /voice/record-sample` returns a `voice_profile_id` + `cloned_voice_key`
  (not an ElevenLabs id). `POST /voice/preview-cloned` lets you hear the clone,
  and `GET /voice/discover` lists other users' voices to request access to.
