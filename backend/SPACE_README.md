---
title: VoiceLink AI API
emoji: 🎙️
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8080
pinned: false
license: mit
---

# VoiceLink AI — Backend

FastAPI backend for VoiceLink AI: Groq chat, Firebase auth, Supabase Postgres,
Edge TTS replies, and faster-whisper speech-to-text.

This Space runs in **DEMO_MODE** (Edge TTS, no GPU voice cloning) so it starts
fast and stays reliable on the free CPU tier.

## Required Secrets and Variables

Set these under **Settings → Variables and secrets** in the Space UI.

### Secrets (mark as "Secret" so they stay hidden)

| Name | Value |
|------|-------|
| `GROQ_API_KEY` | From https://console.groq.com/keys |
| `DATABASE_URL` | Supabase, must use the async scheme: `postgresql+asyncpg://postgres.<ref>:<url-encoded-password>@aws-0-<region>.pooler.supabase.com:5432/postgres` |
| `FIREBASE_CREDENTIALS_JSON` | The **entire contents** of your `firebase-service-account.json`, pasted as one line. Do not commit the file to git. |

### Variables (plain text is fine)

| Name | Value | Why |
|------|-------|-----|
| `DEMO_MODE` | `true` | Voice replies use Edge TTS and the GPU cloning engines are skipped, so startup is fast and cannot hang. |
| `WHISPER_MODEL` | `base` | Small enough to run on free CPU. Use `large-v3-turbo` for better accuracy if you can accept a slow first request. |
| `FIREBASE_CREDENTIALS_PATH` | `./firebase-service-account.json` | Only used when no JSON env var is set. |

> **Do not set `DEMO_MODE=false` here.** This Space has no GPU. Cloning engines
> are not installed in this image and would never load, so setting it to false
> only adds startup time with no benefit.

## Health check

```
https://<your-username>-voicelink-api.hf.space/health
```

Expect `"status":"ok"`. A healthy free Space shows
`"tts_engine":"edge-tts (free, no API key)"`.

Note: free Spaces **sleep when idle**, so the first request after a pause takes
30–60 seconds while it wakes up. That is normal.

## Voice cloning engines (architecture note)

The cloning engines — OmniVoice (`omnivoice_engine.py`), Coqui XTTS v2
(`voice_clone_engine.py`), and Chatterbox (`chatterbox_engine.py`) — are kept in
this repository and are **not** installed in this image, because they total
~2 GB and require a GPU. They run on a local machine with a CUDA GPU, and the
system automatically falls back to Edge TTS when they are unavailable.

The engine-selection order is: OmniVoice → XTTS v2 → Edge TTS.
