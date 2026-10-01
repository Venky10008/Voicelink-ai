# ─────────────────────────────────────────────────────────────────────────────
# VoiceLink AI — backend (FREE-TIER build)
#
# This image deliberately does NOT install the voice-cloning engines
# (omnivoice / coqui-tts / transformers). Those are ~2 GB and need a GPU to be
# usable. On a free CPU host they would either fail to fit in RAM or be so slow
# they time out.
#
# What you still get, all free:
#   - Groq chat  (text + memory + history)
#   - Edge TTS   (free, unlimited, no API key)
#   - faster-whisper STT (local, CPU)
#   - Firebase auth, Supabase Postgres
#
# Run with DEMO_MODE=true so voice replies use Edge TTS and the app never blocks
# on a model load. Set COLAB_TTS_URL to offload cloning to a free Colab T4 GPU
# if you want real cloning without paying.
#
# Requires Python 3.11 (matches backend/voice-venv).
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ffmpeg        -> faster-whisper decodes audio through it
# libsndfile1   -> soundfile/librosa WAV IO
# Both are runtime system libs, so they must be in the image, not pip.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# HF Spaces runs the container as UID 1000 and blocks writes outside the
# workspace. Create that user up front so pip never tries to write to a
# read-only /usr/local. Must happen BEFORE any COPY.
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

# Install deps first so code edits don't invalidate the pip layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the Whisper model at BUILD time.
# Free CPU hosts are far too slow to download + load large-v3-turbo on a cold
# start, so "base" is baked in (~150 MB). Override WHISPER_MODEL at runtime if
# you want better accuracy and can tolerate a longer first request.
ENV HF_HUB_DISABLE_PROGRESS_BARS=1
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')" \
    || echo "WARNING: Whisper pre-download failed; it will retry at runtime."

# --chown is required: files copied as root are unreadable by UID 1000.
COPY --chown=user:user . .

# Writable scratch space for runtime state (SQLite fallback, temp audio).
RUN mkdir -p data && chown -R user:user data

USER user

# HF Spaces requires the app to listen on 8080. It also injects PORT, so honour
# that when present (Render/Railway/Fly do the same) and fall back to 8080.
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8080}/health" || exit 1

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
