# VoiceLink AI — Frontend

The web client for **VoiceLink AI**, an emotion-aware AI voice companion.
React 19 + TanStack Start (SSR) + TypeScript + Tailwind CSS v4.

This half is UI only. Every API call goes to the FastAPI backend in
[`../backend`](../backend) — nothing is faked at runtime.

## Screens

| Route | Screen |
|-------|--------|
| `/` | Login / Signup (Firebase email + password) |
| `/dashboard` | Home dashboard |
| `/chat` | Text chat |
| `/call` | Voice call — mic capture, live captions, waveform |
| `/voices` | Voice library with speed/pitch controls |
| `/personalities` | Personalities (localStorage selection) |
| `/permissions` | My Voice — clone, manage access, request other voices |
| `/history` | Conversation history |
| `/profile` | Profile & settings |

## Development

```sh
npm install
npm run dev     # http://localhost:8080
```

Other scripts:

```sh
npm run build     # production build
npm run preview   # serve the production build
npm run lint      # eslint
npm run format    # prettier
```

## Configuration

Copy `.env.example` to `.env` and fill it in:

| Variable | Purpose |
|----------|---------|
| `VITE_API_URL` | Backend base URL (e.g. `https://your-api.onrender.com`) |
| `VITE_FIREBASE_API_KEY` | Firebase web app config |
| `VITE_FIREBASE_AUTH_DOMAIN` | |
| `VITE_FIREBASE_PROJECT_ID` | |
| `VITE_FIREBASE_STORAGE_BUCKET` | |
| `VITE_FIREBASE_MESSAGING_SENDER_ID` | |
| `VITE_FIREBASE_APP_ID` | |

All `VITE_*` values are inlined at build time — change them, then rebuild.

## Deployment

Deployed to **Vercel** with SSR via the Nitro build output.

- **Root Directory:** `frontend`
- **Framework Preset:** Other
- **Output Directory:** *(leave empty — the build emits `.vercel/output`)*
- **Build Command:** `npm run build`

See [`../DEPLOYMENT.md`](../DEPLOYMENT.md) for the full walkthrough, including
backend hosting on Hugging Face Spaces or Render.

## Icons

Brand icons live in `public/`. Regenerate them from a higher-resolution source
with:

```powershell
.\scripts\make-favicon.ps1
```