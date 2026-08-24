# 📁 VoiceLink AI — Project Docs

This folder explains **what happened to the project so far** and **what to do next**.
It was created on **August 8, 2026** after a full feature audit + feature build session.

> Read the files in this order:
> 1. **[01-project-audit.md](01-project-audit.md)** — What the project has, what was working, what was broken
> 2. **[02-implemented-changes.md](02-implemented-changes.md)** — Exactly what we built and which files changed
> 3. **[03-deferred-and-roadmap.md](03-deferred-and-roadmap.md)** — What we LEFT for later and the next steps
> 4. **[04-elevenlabs-removed-free-voice.md](04-elevenlabs-removed-free-voice.md)** — ElevenLabs removed; free + unlimited voice (Edge TTS + local XTTS cloning)

---

## 🧭 What is this project?

**VoiceLink AI** — an "emotion-aware AI voice companion" app.

| Part | Tech | Location |
|------|------|----------|
| Frontend (UI) | React + TanStack Start + TypeScript + Tailwind | `frontend/` |
| Backend (API) | Python FastAPI | `backend/` |
| AI chat | Groq (LLM) | — |
| Voice (speak) | Microsoft Edge TTS (free, no API key) | — |
| Voice (listen) | faster-whisper (local speech-to-text) | — |
| Auth | Firebase (email + password) | — |
| Database | Supabase Postgres | — |

---

## ▶️ How to run the app

**Terminal 1 — Backend** (port 8000):
```powershell
cd C:\Users\polav\Desktop\project\backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 — Frontend** (port 3000):
```powershell
cd C:\Users\polav\Desktop\project\frontend
npm run dev
```

Open **http://localhost:3000** in your browser.

> ✅ All keys are already configured:
> `backend/.env` (GROQ, Supabase), `backend/firebase-service-account.json`, `frontend/.env` (Firebase web config).
> Voice TTS needs **no key** — it uses Microsoft Edge TTS (free, unlimited). ElevenLabs was removed (see doc 04).
> `/health` on the backend shows `firebase_ready: true`, `groq_key_set: true`, `tts_engine: "edge-tts (free, no API key)"`, `database_ready: true`.

---

## ⚙️ Checks that pass right now

| Check | Result |
|-------|--------|
| Backend starts + `/health` | ✅ OK |
| Frontend TypeScript (`tsc --noEmit`) | ✅ 0 errors |
| Frontend production build (`vite build`) | ✅ OK |
| Browser: app loads with no console errors | ✅ OK |
| Live API end-to-end tests | ✅ 32/32 passed |

---

## 🔑 Note about test account

During testing I created a temporary Firebase account:
**`buffytest@voicelink.dev`** (password `test123456`).
You can delete it anytime from the Firebase Console → Authentication → Users.
