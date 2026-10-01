# Deploying VoiceLink AI (free tiers only)

This repo is two apps that deploy **separately**:

| Part | Folder | What it is |
|------|--------|------------|
| Frontend | `frontend/` | TanStack Start + React (UI) |
| Backend | `backend/` | FastAPI (chat, auth, voice, DB) |

They are **not** deployed to the same place. The frontend is static/SSR and
loves Vercel. The backend is a long-running Python process holding ML models —
Vercel **cannot** host it.

---

## 1. Frontend → Vercel (free, do this first)

1. Push the repo to GitHub.
2. Go to [vercel.com/new](https://vercel.com/new) → import the repo.
3. **Root Directory** = `frontend`  ← important, the repo root has no `package.json`.
4. Framework preset: **Vite**.
5. Add these **Environment Variables** (Project → Settings → Environment Variables):

   ```
   VITE_API_URL=https://<your-backend-url>
   VITE_FIREBASE_API_KEY=AIzaSyCuRi5_bVzEJfWMvliwzuNghDMaLxckZcU
   VITE_FIREBASE_AUTH_DOMAIN=voicelink-ai-aead0.firebaseapp.com
   VITE_FIREBASE_PROJECT_ID=voicelink-ai-aead0
   VITE_FIREBASE_STORAGE_BUCKET=voicelink-ai-aead0.firebasestorage.app
   VITE_FIREBASE_MESSAGING_SENDER_ID=362527421933
   VITE_FIREBASE_APP_ID=1:362527421933:web:609ea01969df28155463e4
   ```

   The Firebase values are already in `frontend/.env` — copy them across.
   `VITE_API_URL` must point at your **deployed** backend, not `127.0.0.1`.
6. Deploy. Re-deploy after changing env vars (Vite inlines `VITE_*` at build time).

Add your production domain to Firebase → Authentication → **Settings →
Authorized domains**, or login will fail in the browser.

### Do the backend first

Deploy the HF Space **before** setting `VITE_API_URL` on Vercel — you need the
live Space URL, and the Space URL only exists after the Space is created.
`VITE_*` values are compiled into the bundle at build time, so a wrong
`VITE_API_URL` needs a rebuild, not just a restart.

Once the Space is up and `https://<user>-<space>.hf.space/health` returns
`"status":"ok"`, set:

```
VITE_API_URL=https://<hf-username>-voicelink-api.hf.space
```

---

## 2. Backend → where?

**Short answer: not Vercel.** Vercel functions are short-lived serverless
(12 s CPU on Hobby, no GPU, ~250 MB bundle). This backend needs torch,
transformers and a Whisper model — impossible there.

### Option A — Hugging Face Spaces (recommended free option)

The best free tier for this because it gives the most RAM.

- Free CPU hardware: **4 vCPU, 15 GiB RAM** (vs Render's 512 MB).
- Sleeps when idle, so the **first request after an idle period takes 30–60 s**.
- A Space is **its own git repo** — it cannot point at a sub-folder of your
  GitHub repo. `backend/deploy_hf_space.bat` handles the copying.

Steps:

1. Create a Space → **Docker** SDK → name it e.g. `voicelink-api`.
2. Copy `backend/SPACE_README.md` to the Space repo **as `README.md`**. That file
   already contains the required YAML frontmatter:
   ```yaml
   ---
   title: VoiceLink AI API
   emoji: 🎙️
   colorFrom: indigo
   colorTo: blue
   sdk: docker
   app_port: 8080
   pinned: false
   ---
   ```
3. Deploy the backend code — either let the Space build its default template
   first, then push yours:
   ```powershell
   cd c:\Users\polav\Desktop\project\backend
   deploy_hf_space.bat <hf-username> voicelink-api
   ```
   You will be prompted for a Hugging Face token on the first push — create one
   at https://huggingface.co/settings/tokens with **Write** permission.
4. In the Space: **Settings → Variables and secrets**, add:

   **Secrets** (tick the "Secret" checkbox so the value is hidden):
   | Name | Value |
   |------|-------|
   | `GROQ_API_KEY` | your Groq key |
   | `DATABASE_URL` | `postgresql+asyncpg://…` (must be the **asyncpg** scheme) |
   | `FIREBASE_CREDENTIALS_JSON` | the **entire contents** of `firebase-service-account.json`, pasted as one line |

   **Variables** (plain text is fine):
   | Name | Value |
   |------|-------|
   | `DEMO_MODE` | `true` |
   | `WHISPER_MODEL` | `base` |

   > The Firebase service-account JSON is gitignored, so it cannot be committed
   > to the Space. `FIREBASE_CREDENTIALS_JSON` is read directly by the backend
   > (`main.py` → `_init_firebase()`), so no file upload is needed. Paste it
   > exactly as-is — the `\n` inside `private_key` must stay escaped.

5. Check **https://<hf-username>-voicelink-api.hf.space/health** → `"status":"ok"`.

### Option B — Render (free, but RAM is tight)

- Free compute: **512 MB RAM, <1 CPU**, spins down when idle.
- Too small for Whisper + any cloning model. Works for chat + Edge TTS only.
- No Dockerfile needed — set Build Command `pip install -r requirements.txt`
  and Start Command `uvicorn main:app --host 0.0.0.0 --port $PORT`.

### Option C — Free GPU for real voice cloning (Colab)

This repo already supports it — no code change needed:

1. Open `colab_chatterbox_server.ipynb` → Google Colab → **Runtime → T4 GPU** → Run all.
2. Copy the printed ngrok URL and set it on the backend:
   ```
   DEMO_MODE=false
   COLAB_TTS_URL=https://XXXX.ngrok-free.app
   COLAB_TTS_TIMEOUT=120
   ```

Colab gives a real GPU for free but **disconnects after ~90 min idle** and the
URL changes on every restart, so it is fine for demos, not for production.

### What genuinely cannot be done for free

There is **no free, always-on, production-grade GPU host**. Options that come
close: Colab (disconnects), Kaggle Notebooks (30 h/week, session-based), or
Oracle Cloud Always Free (real 24/7 VM, but **no GPU**). If cloning must always
work for real users, you need a paid GPU box (RunPod / Vast.ai / Lambda, roughly
$0.3–0.6/hr) or a paid HF GPU Space.

**This is fine for your plan.** Keeping `DEMO_MODE=true` means voice replies use
Edge TTS — free, unlimited, no key, no GPU. Quality is lower than a cloned
voice, but nothing breaks.

---

## 3. Environment variables for the backend

Copy from `backend/.env.example`. The ones that matter:

| Variable | Notes |
|----------|-------|
| `GROQ_API_KEY` | from [console.groq.com/keys](https://console.groq.com/keys) — free |
| `FIREBASE_CREDENTIALS_PATH` | path to the service-account JSON |
| `DATABASE_URL` | Supabase, `postgresql+asyncpg://…` |
| `DEMO_MODE` | **`true` for free hosting** — skips cloning, uses Edge TTS |
| `WHISPER_MODEL` | use `base` on free CPU; `large-v3-turbo` locally for accuracy |

CORS is already `allow_origins=["*"]`, so the Vercel origin needs no change.

### Database warning

If `/health` shows `database_ready` via **SQLite**, your Supabase project is
paused or unreachable, and **chat history and memory will be lost on restart**.
Supabase free projects pause after a week of inactivity — wake it from the
Supabase dashboard. You will also see it in the log as:

```
[db] DEMO_MODE: Postgres unavailable (...) — falling back to local SQLite
```

---

## 4. After deploying — checklist

- [ ] `https://<backend>/health` returns `"status":"ok"`
- [ ] `VITE_API_URL` in Vercel points at the deployed backend
- [ ] Your Vercel domain added to Firebase **Authorized domains**
- [ ] Login works from the deployed frontend
- [ ] Send a chat message — reply comes back
- [ ] Voice call replies with Edge TTS audio

---

## 5. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Vercel build fails | Root Directory must be `frontend` |
| Login works locally, fails deployed | Add the Vercel domain to Firebase Authorized domains |
| Frontend "cannot reach server" | `VITE_API_URL` wrong, or backend asleep (free tier) |
| Voice call silent | `DEMO_MODE=true` + Edge TTS needs outbound internet; check `tts_engine` in `/health` |
| First call very slow | Free tier cold start, or Whisper downloading (~150 MB for `base`) |
| History empty after restart | Supabase unreachable → SQLite fallback (see above) |
| "Voice cloning engine not available" | Expected on cloud free tiers — cloning is intentionally skipped. Locally it means the engines aren't installed; see `backend/requirements-voice.txt`. |
