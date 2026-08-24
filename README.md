# VoiceLink AI — Text Chat + Voice Conversation

Minimal stack: **React** frontend (TanStack Start + TypeScript), **FastAPI** backend, **Groq** chat, **Firebase** email/password auth, **Supabase** Postgres, **Edge TTS** (free, unlimited — no API key), **faster-whisper** STT.

```
project/
├── backend/             # FastAPI + Groq + Firebase Admin + Supabase Postgres + Voice
└── frontend/            # TanStack Start + React + TypeScript web UI (UI-only, API wiring in progress)
```

---

## 1. Create a free Firebase project

1. Go to [https://console.firebase.google.com/](https://console.firebase.google.com/) and sign in with Google.
2. Click **Add project** → name it e.g. `voicelink-ai` → continue (Google Analytics optional → you can disable it).
3. Open the project → left sidebar **Build** → **Authentication** → **Get started**.
4. Open the **Sign-in method** tab → click **Email/Password** → enable the first toggle → **Save**.

### Backend: service account key (Admin SDK)

1. Click the gear icon → **Project settings** → **Service accounts**.
2. Click **Generate new private key** → confirm → download the JSON file.
3. Rename/move it to:

```
project/backend/firebase-service-account.json
```

That path matches `FIREBASE_CREDENTIALS_PATH` in `backend/.env.example`.

### Frontend: register the web app

1. Project settings → **Your apps** → add a **Web** app.
2. Copy the Firebase config (apiKey, authDomain, projectId, etc.).
3. It will be added to `frontend/` as the Firebase web SDK config when the frontend is wired up.

---

## 2. Get a free Groq API key

1. Go to [https://console.groq.com/](https://console.groq.com/) and sign up / log in.
2. Open [https://console.groq.com/keys](https://console.groq.com/keys).
3. Create an API key and copy it.

---

## 2b. Voice TTS — FREE and UNLIMITED (no API key needed)

Voice replies use **Microsoft Edge TTS** via the open-source `edge-tts` package:

- **No API key, no signup, no credit balance**
- **No character limits / no monthly caps** — genuinely unlimited
- This replaced ElevenLabs, whose free tier is limited to ~10k characters/month
  and whose voice cloning requires a paid plan.

Optional settings in `backend/.env` (defaults are fine):

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_EDGE_TTS_VOICE` | `en-US-AriaNeural` | Default Edge TTS voice |
| `WHISPER_MODEL` | `large-v3-turbo` | Local Whisper model size (`tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo`) |

### Voice cloning (optional, still free)

Cloned voices are handled by **two local engines** — both free and unlimited:

1. **OmniVoice** (`backend/omnivoice_engine.py`) — preferred, supports 600+ languages
2. **Coqui XTTS v2** (`backend/voice_clone_engine.py`) — fallback, supports ~17 languages

The system automatically uses OmniVoice if available, falls back to XTTS v2, and finally
to Edge TTS if neither engine is installed.

#### OmniVoice (recommended)

OmniVoice is a state-of-the-art open-source TTS model (Apache 2.0 license) that supports
600+ languages with superior voice cloning quality. Install with:

```powershell
cd c:\Users\polav\Desktop\project\backend
pip install omnivoice torch torchaudio
```

For NVIDIA GPU support, install PyTorch with CUDA:
```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
```

For Apple Silicon:
```powershell
pip install torch torchaudio
```

#### XTTS v2 (fallback)

The XTTS v2 engine needs PyTorch (Python 3.11/3.12). The project's `backend/voice-venv`
(Python 3.11) already has it installed and the XTTS v2 model downloaded, so cloning
works out of the box when the backend runs from that venv:

```powershell
cd c:\Users\polav\Desktop\project\backend
.\voice-venv\Scripts\Activate.ps1   # Python 3.11 venv (coqui-tts + torch already installed)
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

If neither engine is available (e.g. the backend runs on newer Python), cloned voices
gracefully fall back to Edge TTS so calls always work — `/health` shows the truth
under `voice_clone_engine` ("omnivoice (local, free, 600+ languages)" vs
"xtts-v2 (local, free)" vs "not installed").

> Windows note: torchaudio's torchcodec backend often can't load its FFmpeg DLLs
> (`Could not load libtorchcodec`). `voice_clone_engine.py` detects this and
> automatically patches XTTS to load reference audio via `soundfile` instead —
> cloning works out of the box, no extra installs.

---

## 3. Backend setup — where to paste keys

```powershell
cd c:\Users\polav\Desktop\project\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `backend/.env`:

| Variable | What to paste |
|----------|----------------|
| `GROQ_API_KEY` | Your Groq API key from §2 |
| `FIREBASE_CREDENTIALS_PATH` | Keep `./firebase-service-account.json` if the JSON is in `backend/` |

> Voice TTS needs **no key** — it uses Edge TTS (free, unlimited).

Place the Firebase service account JSON at:

```
backend/firebase-service-account.json
```

Start the API:

```powershell
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Check: open [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) — you should see `"status":"ok"`, `"tts_engine": "edge-tts (free, no API key)"` and `"database_ready": true`.

API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

> If `pip install` fails on Python 3.14, use Python 3.11 or 3.12 for the venv.

---

## 3b. Supabase Postgres (chat history + memory)

### Get your connection string

1. Open [https://supabase.com/dashboard](https://supabase.com/dashboard) → your project.
2. Go to **Project Settings** (gear) → **Database**.
3. Under **Connection string**, choose **URI**.
4. Copy it. It looks like:
   `postgresql://postgres.[REF]:[YOUR-PASSWORD]@aws-0-....pooler.supabase.com:5432/postgres`
   or
   `postgresql://postgres:[YOUR-PASSWORD]@db.[REF].supabase.co:5432/postgres`

### Put it in `backend/.env`

1. Open `backend/.env`.
2. Set `DATABASE_URL` using the **asyncpg** scheme:

```
DATABASE_URL=postgresql+asyncpg://postgres.[REF]:ENCODED_PASSWORD@aws-0-....pooler.supabase.com:5432/postgres
```

Important:
- Change `postgresql://` → `postgresql+asyncpg://`
- Do **not** leave `[YOUR-PASSWORD]` brackets in the final URL
- If the password has `@ ( ) : / #`, URL-encode them (e.g. `@` → `%40`, `(` → `%28`, `)` → `%29`)
- The backend also auto-encodes common special characters and enables SSL for `*.supabase.co`

### Create tables on Supabase

```powershell
cd c:\Users\polav\Desktop\project\backend
.\.venv\Scripts\Activate.ps1
python init_db.py
```

You should see `Found tables: messages, user_memory, users`.

### Verify in Supabase SQL Editor

Dashboard → **SQL Editor** → New query → Run:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('users', 'messages', 'user_memory')
ORDER BY table_name;
```

After chatting from the app:

```sql
SELECT id, user_id, role, left(content, 60) AS content, created_at
FROM messages
ORDER BY id DESC
LIMIT 10;
```

`/health` should show `"database_ready": true`.

---

## 4. Frontend setup

The frontend is a **UI-only** TanStack Start + TypeScript app cloned from
`https://github.com/Venky10008/voice-link-ui`. It is intentionally built with
placeholder handlers and mock data — backend wiring is an in-progress task.

```powershell
cd c:\Users\polav\Desktop\project\frontend
bun install        # or: npm i
bun run dev        # or: npm run dev
```

Default dev URL: http://localhost:3000

### Screens

| Route | Screen |
|-------|--------|
| `/` | Login / Signup (placeholder auth — wire to Firebase) |
| `/dashboard` | Home dashboard |
| `/chat` | Text chat |
| `/call` | Voice call |
| `/voices` | Voice Library (built-in voices + speed/pitch sliders + your cloned "My Voice") |
| `/personalities` | Personalities (mock cards, localStorage selection) |
| `/permissions` | My Voice — clone your voice (free local engine), manage access, request other voices |
| `/history` | Conversation history (mock data) |
| `/profile` | Profile & settings |

> Note: this repo is connected to [Lovable](https://lovable.dev) — avoid force-pushing
> or rewriting published git history on the frontend repo.

### Connecting to the local backend

- The backend runs at `http://127.0.0.1:8000`.
- All protected endpoints expect `Authorization: Bearer <Firebase ID token>`.
- The frontend currently stores a placeholder token in localStorage (`voicelink.auth`)
  and must be switched to the Firebase web SDK to obtain real ID tokens.

---

## 5. Run backend + app together

**Terminal 1 — backend**

```powershell
cd c:\Users\polav\Desktop\project\backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 — frontend**

```powershell
cd c:\Users\polav\Desktop\project\frontend
npm run dev
```

---

## API contract

### `POST /chat` (text)

- Header: `Authorization: Bearer <Firebase ID token>`
- Body: `{ "message": "Hello" }`
- Success: `{ "reply": "...", "emotion": "happy", "fresh_start": false, "notice": null }` — `emotion` is one of `happy / sad / angry / anxious / excited / tired / neutral`
- Side effects: creates `users` row if needed, saves user + assistant messages, uses last 10 messages + `user_memory` in the Groq prompt, and the AI adapts its tone to your detected mood
- Auto memory: after each exchange, the backend extracts durable facts about you in the background and saves them as `auto-*` keys in `user_memory` (deduped, capped at 60)
- **Prototype quota (default 100 conversations):** each account gets 100 conversation exchanges. When the 100th is reached, the backend wipes that user's chat history + memories for a fresh start and returns `"fresh_start": true` with a human-readable `notice`. Configure with `CONVERSATION_LIMIT` env var.
- Errors: `{ "detail": "..." }` with 400 / 401 / 502 / 503

### `POST /chat/stream` (streaming chat, SSE)

- Header: `Authorization: Bearer <Firebase ID token>`
- Body: same as `POST /chat`
- Returns `text/event-stream`. Events:
  - `{"type": "emotion", "emotion": "happy"}` — detected mood, sent first
  - `{"type": "token", "content": "..."}` — one per reply chunk
  - `{"type": "fresh_start", "notice": "..."}` — sent when the 100-conversation quota was reached and the account's history was wiped
  - `{"type": "done"}` — stream finished (messages saved)
  - `{"type": "error", "detail": "..."}` — an error occurred mid-stream
- Side effects: same as `POST /chat` (messages saved after the stream completes)

### `POST /voice-chat` (voice)

- Header: `Authorization: Bearer <Firebase ID token>`
- Body: `multipart/form-data` with field `file` (audio file: `.wav`, `.webm`, `.ogg`, `.mp3`, `.m4a`, `.mp4`, `.aac`; max 15 MB) and optional `voice_profile_id` to use an approved cloned voice
- Success:
  ```json
  {
    "transcript": "Hello there",
    "reply": "Hi! How can I help you today?",
    "emotion": "happy",
    "audio_base64": "//uQxAAA...",
    "audio_mime_type": "audio/mpeg",
    "fresh_start": false,
    "notice": null
  }
  ```
- Pipeline: upload → Whisper STT → emotion detection → Groq chat (with history + memory) → TTS (Edge TTS, free — or the local XTTS clone if an approved cloned voice is requested) → response
- Errors: `{ "detail": "..." }` with 400 / 401 / 403 / 502 / 503

### `POST /memory`

- Header: `Authorization: Bearer <Firebase ID token>`
- Body: `{ "key": "name", "value": "Alex" }`
- Success: `{ "key": "...", "value": "...", "updated_at": "..." }`
- Keys starting with `auto-` are saved automatically by the companion from your conversations (shown with an "auto" badge in the profile screen)

### Voice sharing / permissions (`/voice/*`)

All require `Authorization: Bearer <Firebase ID token>`.

| Endpoint | Purpose |
|----------|---------|
| `POST /voice/record-sample` | Upload an audio sample to clone your voice locally (multipart `file` + `consent_confirmed=true`; free XTTS engine, no API key) |
| `POST /voice/request-access` | Request to use another user's cloned voice `{ "voice_profile_id": 1 }` |
| `POST /voice/approve-access` | Owner approves a request `{ "permission_id": 1 }` |
| `POST /voice/revoke-access` | Owner revokes access `{ "permission_id": 1 }` |
| `DELETE /voice/delete-profile` | Delete your voice profile + revoke all permissions |
| `GET /voice/my-permissions` | Who can use my voice + which voices I can use + `clone_engine_available` status |
| `GET /voice/discover?q=` | Search other users' cloned voices to request access (excludes your own) |
| `POST /voice/preview-cloned` | Hear a cloned voice `{ "voice_profile_id": 1 }` (owner or approved grantee only) |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Login fails | Email/Password enabled in Firebase Auth? Correct Firebase web config in `frontend/`? |
| Chat: missing/invalid token | Sign out and sign in again; check Authorization header is sent |
| Chat: cannot reach server | Backend running? Correct API base URL? CORS enabled? |
| Groq errors | Valid `GROQ_API_KEY` in `backend/.env`? Restart uvicorn after editing `.env` |
| Firebase Admin not ready | `firebase-service-account.json` path correct? Check `/health` → `firebase_ready` |
| Database not ready | Valid Supabase `DATABASE_URL` in `.env` (with `postgresql+asyncpg://`)? Password URL-encoded? Check `/health` → `database_ready` |
| Voice: cloned voice silent/fallback | Neither OmniVoice nor XTTS engine installed. Install OmniVoice: `pip install omnivoice torch torchaudio` — calls still work with the free Edge TTS voice |
| Voice: OmniVoice not available | Install OmniVoice: `pip install omnivoice torch torchaudio`. For GPU support: `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128` |
| Voice: Whisper fails | `pip install faster-whisper` in the venv? First run downloads model (~150 MB) |

---

## Voice Cloning Engines

This project supports two voice cloning engines:

1. **OmniVoice** (recommended) - 600+ languages, Apache 2.0 license
2. **XTTS v2** (fallback) - ~17 languages, CPML license

See `backend/OMNIVOICE_INTEGRATION.md` for detailed integration documentation.
