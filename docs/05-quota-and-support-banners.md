# 05 — 100-Conversation Quota + Prototype Support Banner (August 9, 2026)

Second session's changes. Everything below was **implemented and validated** on
August 9, 2026 (frontend typecheck 0 errors, production build success, backend
compiles, quota logic test passes, backend `/health` all green).

---

## 1. 🧮 100-Conversation Prototype Quota (auto database cleanup)

The user's goal: keep the database small as users grow — each account gets a
limited number of conversations, then their data is wiped for a fresh start.

**Rules (decided with the user):**
- Each account gets **100 conversations** by default (configurable via
  `CONVERSATION_LIMIT` env var).
- Chat messages **and** voice calls both count (any `role="user"` message).
- **Wipe happens exactly at the 100th conversation** — after the 100th exchange
  is saved, the backend deletes that user's **chat history + memories**
  ("What I remember").
- **Kept safe:** the account itself, profile name, voice settings, and the
  user's cloned voice.
- After the wipe, the user's next message starts a fresh cycle at #1 — the app
  never blocks or breaks.

**What the user sees:** a notice explaining it's a prototype limit and that
their history was reset for a fresh start. Shown as:
- a yellow/amber dismissible banner in **Text Chat** (`chat.tsx`),
- a toast in **Voice Call** (`call.tsx`).

**API changes:**
- `POST /chat` response gains `"fresh_start": bool` and `"notice": string|null`
- `POST /chat/stream` emits a new `{"type": "fresh_start", "notice": "..."}` SSE event before `done`
- `POST /voice-chat` response gains `fresh_start` + `notice`

**Files:**
- `backend/crud.py` — `count_user_messages()`, `reset_user_conversation_data()`
- `backend/chat_service.py` — `CONVERSATION_LIMIT`, `CONVERSATION_LIMIT_NOTICE`,
  `_maybe_reset_for_limit()`, `_save_exchange()` returns `fresh_start`,
  `generate_chat_reply()` returns 4-tuple, stream yields `("fresh_start", True)`
- `backend/main.py` — response models + endpoint wiring (all 3 endpoints)
- `frontend/src/routes/chat.tsx` — fresh_start handling + notice banner
- `frontend/src/routes/call.tsx` — fresh_start toast
- `backend/test_quota.py` — **NEW** logic test (fakes, no real DB): verifies the
  99th exchange doesn't wipe, the 100th does, memory extraction is skipped on
  the wipe, and the count restarts after.

**Edge cases handled (from code review):**
- `CONVERSATION_LIMIT` is guarded with `max(1, ...)` so a bad env value (0/negative)
  can never wipe on every message.
- In-flight background memory-extraction tasks are cancelled before the wipe
  (`cancel_pending_memory_tasks`) so stale `auto-*` facts can't be re-inserted
  AFTER the reset.
- The wipe deletes messages + memories only; account/settings/cloned voice stay.

> ⚠️ **Deployment note:** users who ALREADY have 100+ messages stored when this
> feature ships will get an instant wipe on their very first message after
deploy (their count is already over the limit). That is the intended
"clean database" behavior, but it means existing long histories vanish —
communicate this before rollout if you care about current test accounts.

---

## 2. 🧡 "This is a prototype" + Donation (UPI) Banner

The user wants to tell early users the project is a prototype and invite
optional support via UPI.

**Wording shown to users** (polished from the user's draft):

> **This is a prototype — and we need you**
> We're building VoiceLink into a professional product, and early support from
> people like you means everything to us. If you've enjoyed it and would like to
> help the journey, you can donate any amount you wish — every little bit counts.
>
> `hacker36@freecharge` *(tap to copy)*
>
> Thank you for being part of this journey 🙏

- UPI ID: **`hacker36@freecharge`**
- The UPI chip is **tap-to-copy** with a confirmation toast.
- Shown on the **Dashboard** (top) and **Profile** (bottom).

**Files:**
- `frontend/src/components/prototype-support-banner.tsx` — **NEW** reusable component
- `frontend/src/routes/dashboard.tsx`
- `frontend/src/routes/profile.tsx`

---

## 3. ⏱ "Cloning may take a few minutes" notices

The user wants users to know voice cloning runs on free servers and can take
minutes (free hosts = CPU-only XTTS; see docs/04). Two notices added:

- **My Voice & Permissions page** (`permissions.tsx`) — amber "May take a few
  minutes" notice when the clone engine is available.
- **Voice Library → My Voice card** (`voices.tsx`) — small ⏱ line under the
  cloned-voice description.

---

## ✅ Validation summary (all passed)

- `backend/test_quota.py` — QUOTA LOGIC TEST: OK
- `python -m py_compile` main/chat_service/crud — OK
- `tsc --noEmit` — 0 errors
- `vite build` — success (Cloudflare Worker files generated)
- Backend boot + `/health` — `status ok`, firebase/db/groq ready,
  `voice_clone_engine: xtts-v2 (local, free)`

---

## 🔜 What's next (see docs/03)

1. **Deployment** (backend → Render/Railway/Fly; frontend → Cloudflare Workers
   — build already generates the worker). Needs the user's free accounts.
   ⚠️ Free hosts can't run XTTS cloning (needs ~2GB model + RAM/GPU) — cloned
   voices fall back to Edge TTS there.
2. Optional: HF Spaces GPU host for real cloning in production (~$10–20/mo).
3. Nice-to-have: voice-call history, PWA, push notifications.
