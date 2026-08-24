# 03 — Left for Later + What to Do Next

This file lists everything we **deliberately did NOT build** (on purpose), and the
**next steps** in priority order.

---

## 🛑 Things we LEFT for later (you said: keep aside, do in the future)

| # | Feature | Why we left it | Backend status |
|---|---------|----------------|----------------|
| 1 | ~~Voice Permissions screen~~ | **✅ DONE 2026-08-08** — real UI in `frontend/src/routes/permissions.tsx` (record sample, consent, preview, delete, approve/revoke, request access) | ✅ Complete |
| 2 | ~~Voice cloning UX + cloned-voice TTS~~ | **✅ DONE 2026-08-08** — engine live from `voice-venv`; "My Voice (cloned)" card added to the Voice Library; calls send `voice_profile_id` | ✅ Complete (verified `/health` shows `xtts-v2 (local, free)`) |
| 3 | ~~User / voice discovery~~ | **✅ DONE 2026-08-08** — new `GET /voice/discover?q=` endpoint + search UI on the "My Voice" page | ✅ Complete |
| 4 | **Voice-call history** (call captions saved across sessions) | Voice-related | ❌ Not built |
| 5 | **Deployment** (put the app online) | You said: *"leave deployment topic, we discuss about deployment after this"* | ⚠️ Frontend build already produces a Cloudflare Worker — backend hosting (Render/Railway) not configured |

### Other roadmap ideas mentioned but not chosen yet
- **PWA + mobile polish** (installable app, offline shell)
- **Push notifications** (daily check-ins from the companion)

---

## ✅ DONE 2026-08-08 — Voice cloning is now fully wired (see below for what's left)

- **🔴 Priority 1 — Voice Permissions screen: DONE** — `frontend/src/routes/permissions.tsx`
  is now the real UI ("My Voice & Permissions"): record sample + consent →
  `POST /voice/record-sample`, preview/delete your clone, approve/revoke grantees,
  request access, and see the voices you can use. The nav entry is now "My Voice".
- **🟠 Priority 2 — Voice discovery endpoint: DONE** — new `GET /voice/discover?q=`
  searches other users' active cloned voices (never your own) and reports your
  current status per voice.
- **🎁 Bonus** — `POST /voice/preview-cloned` lets owners and approved grantees
  hear a cloned voice; `GET /voice/my-permissions` now returns
  `clone_engine_available` so the UI can tell you when the local engine is live.
- **Engine verified live:** the backend running from `backend/voice-venv` (Python 3.11.8,
  torch 2.13.0, coqui-tts 0.27.5) reports `voice_clone_engine: "xtts-v2 (local, free)"`
  and the XTTS v2 model is already downloaded.

## 🚀 What to do next (priority order)

### 🟡 Priority 3 — Deployment (the only big thing left)
- Backend → Render / Railway / Fly.io (needs `DATABASE_URL`, Firebase key, `GROQ_API_KEY`, etc. as env vars)
- Frontend → Cloudflare Workers (build already generates the worker files; free URL looks like `https://venky10008-voice-link-ui.<account>.workers.dev`)
- Then set up a production database + custom domain
- ⚠️ **Honest caveat:** free hosts can't run the XTTS clone engine (needs ~2 GB model + RAM/GPU) — deployed users get Edge TTS voices and cloned voices gracefully fall back. Voice cloning stays perfect locally.
- **If cloned voices must work in production** (user's main goal): host XTTS v2 on a Hugging Face Space with a GPU (~$10–20/mo T4) and point the backend at it. Free HF Spaces = CPU = minutes per sentence (too slow). XTTS v2 is NOT on HF's serverless Inference API.

### 🟢 Nice-to-have (anytime)
- Voice-call history persistence
- PWA (installable + offline)
- Push notifications / daily check-ins
- Live "conversations left" counter in the UI for the 100-quota

---

## ✅ Already done — do not redo

- Auth bugs fixed (History + Profile token, custom name overwrite)
- Emotion-aware AI (chat + voice)
- Auto memory extraction
- Streaming chat
- Forgot password
- README updated with the new API contract
- **ElevenLabs removed entirely** — free + unlimited voice (Edge TTS for calls, local XTTS v2 for cloning); see doc 04
- **100-conversation prototype quota** (auto database cleanup every 100 conversations) — see doc 05
- **Prototype + UPI donation banner** (Dashboard + Profile) — see doc 05
- **"Cloning may take a few minutes" notices** (My Voice page + Voice Library) — see doc 05
- `test_quota.py` + `test_clone_e2e.py` backend tests — see doc 05

> If in doubt, read **docs/01** (audit) and **docs/02** (what we implemented) first.
Everything from both sessions is now recorded.