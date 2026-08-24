"""Chatterbox TTS voice-cloning engine — free, open-source, MIT licensed.

This module provides voice cloning using Chatterbox Multilingual V3 by
Resemble AI. It's a drop-in replacement for the OmniVoice engine with the
same public API surface (engine_available, synthesize_cloned_voice,
VoiceCloneUnavailableError, VoiceSynthesisError).

Model details
-------------
- Chatterbox Multilingual V3: 500M parameters, 23+ languages
- Supports: ar, da, de, el, en, es, fi, fr, he, hi, it, ja, ko, ms,
  nl, no, pl, pt, ru, sv, sw, tr, zh
- Does NOT support: te (Telugu), ta (Tamil) — falls back to XTTS or Edge TTS
- Voice cloning from a short reference clip (reuse existing stored WAVs)

Remote GPU mode (Colab)
-----------------------
Set ``COLAB_TTS_URL`` in .env to offload inference to a free Colab T4 GPU:
  - The Colab runs ``colab_chatterbox_server.ipynb`` which exposes a
    ``POST /synthesize`` endpoint via ngrok.
  - This module sends text + reference audio (base64) to the Colab URL
    and receives synthesized audio back.
  - If the Colab is unreachable (notebook not running), falls back to the
    local GPU/CPU so the app never fully breaks.
  - Round-trip latency is logged with ``[COLAB_TTS_TIMING]`` tags.

Hardware notes
--------------
- Runs on GPU (recommended) or CPU
- Model ~1 GB (vs OmniVoice's ~1.8 GB), significantly faster on constrained GPUs
- 500M params vs OmniVoice's larger architecture
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from io import BytesIO
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
from fastapi import HTTPException, status

from voice_keys import voice_key_for as shared_voice_key_for

# ── Remote GPU (Colab) configuration ────────────────────────────────────
COLAB_TTS_URL: str = os.getenv("COLAB_TTS_URL", "").strip().rstrip("/")
COLAB_TTS_TIMEOUT: int = int(os.getenv("COLAB_TTS_TIMEOUT", "120"))  # seconds

CLONE_DATA_DIR = Path(os.getenv("VOICE_CLONE_DATA_DIR", "data/cloned_voices")).resolve()

_chatterbox_model = None
_chatterbox_lock = asyncio.Lock()

# Cached per-process result: importing torch + chatterbox can take time in a
# fresh process, so we check once and reuse the answer on every later call.
_engine_available: bool | None = None
_colab_reachable: bool | None = None  # cached probe result for Colab endpoint

# Languages supported by Chatterbox Multilingual V3.
# te (Telugu) and ta (Tamil) are NOT supported — callers must fall back.
SUPPORTED_LANGUAGES = frozenset({
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi",
    "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv",
    "sw", "tr", "zh",
})


class VoiceCloneUnavailableError(RuntimeError):
    """Raised when the Chatterbox engine cannot be used (not installed / wrong Python)."""


class VoiceSynthesisError(RuntimeError):
    """The model IS loaded but a synthesis attempt failed at runtime
    (OOM, CUDA error, malformed output, empty result...).

    Deliberately distinct from VoiceCloneUnavailableError so callers can tell a
    genuine "engine missing" (legitimate Edge TTS fallback) apart from a runtime
    failure that should be retried and surfaced to the user instead of silently
    swapping in a completely different-sounding voice.
    """


def engine_available() -> bool:
    """True if Chatterbox is usable — either remote (Colab) or local.

    The result is cached after the first check.
    """
    global _engine_available, _colab_reachable
    # If Colab is configured, prefer it (avoids loading the model locally)
    if COLAB_TTS_URL:
        if _colab_reachable is None:
            _colab_reachable = _probe_colab()
        if _colab_reachable:
            return True
    # Fall back to local import check
    if _engine_available is None:
        try:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # noqa: F401
            _engine_available = True
        except Exception:
            _engine_available = False
    return _engine_available


def _load_chatterbox():
    """Lazily load the Chatterbox Multilingual V3 model once (thread-safe via the caller's lock)."""
    global _chatterbox_model
    if _chatterbox_model is not None:
        return _chatterbox_model

    try:
        import torch
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    except Exception as exc:
        raise VoiceCloneUnavailableError(
            "The Chatterbox engine is not available in this "
            "Python environment. Install with: pip install chatterbox-tts\n"
            "For GPU support: pip install torch torchaudio (with appropriate CUDA version)"
        ) from exc

    # Determine device based on availability
    if torch.cuda.is_available():
        device = "cuda"
        dtype = torch.float16
    elif hasattr(torch, "mps") and torch.mps.is_available():
        device = "mps"
        dtype = torch.float32
    else:
        device = "cpu"
        dtype = torch.float32

    try:
        t0 = time.time()
        _chatterbox_model = ChatterboxMultilingualTTS.from_pretrained(
            device=device,
        )
        load_time = time.time() - t0
        print(f"[chatterbox] Model loaded on {device} ({dtype}) in {load_time:.2f}s", flush=True)
        if torch.cuda.is_available():
            print(
                f"[chatterbox] VRAM: allocated={torch.cuda.memory_allocated() / 1024**2:.1f}MB "
                f"reserved={torch.cuda.memory_reserved() / 1024**2:.1f}MB",
                flush=True,
            )
    except Exception as exc:
        raise VoiceCloneUnavailableError(
            f"Failed to load Chatterbox model: {exc}"
        ) from exc

    return _chatterbox_model


def _voice_key_for(voice_name: str) -> str:
    """Stable local key derived from the voice name (e.g. VoiceLink_<user_id>).

    Delegates to the shared scheme so BOTH engines mint identical keys and a
    profile's key never depends on which engine was active at record time.
    """
    return shared_voice_key_for(voice_name)


def _ref_wav_path(voice_key: str) -> Path:
    """Stored normalized reference WAV that drives Chatterbox voice cloning."""
    return CLONE_DATA_DIR / f"{voice_key}.wav"


# ---------------------------------------------------------------------------
# Remote Colab helpers
# ---------------------------------------------------------------------------


def _probe_colab() -> bool:
    """Quick health check — returns True if the Colab server is up."""
    if not COLAB_TTS_URL:
        return False
    try:
        resp = httpx.get(f"{COLAB_TTS_URL}/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


async def _synthesize_via_colab(
    text: str,
    ref_wav_path: Path,
    language: str,
    speed: float,
) -> tuple[bytes, str]:
    """Send text + reference audio to the Colab GPU and return (audio_bytes, mime)."""
    ref_bytes = ref_wav_path.read_bytes()
    ref_b64 = base64.b64encode(ref_bytes).decode()

    payload = {
        "text": text,
        "reference_audio_b64": ref_b64,
        "language": language,
        "speed": speed,
    }

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=COLAB_TTS_TIMEOUT) as client:
            resp = await client.post(f"{COLAB_TTS_URL}/synthesize", json=payload)
            resp.raise_for_status()
    except httpx.ConnectError:
        raise VoiceCloneUnavailableError(
            f"Colab TTS server unreachable at {COLAB_TTS_URL}. "
            "The notebook may have stopped — falling back to local."
        )
    except httpx.TimeoutException:
        raise VoiceSynthesisError(
            f"Colab TTS request timed out after {COLAB_TTS_TIMEOUT}s. "
            "The GPU may be overloaded."
        )
    except httpx.HTTPStatusError as exc:
        raise VoiceSynthesisError(
            f"Colab TTS returned HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        )
    elapsed = time.perf_counter() - t0

    result = resp.json()
    audio_b64 = result["audio_base64"]
    mime_type = result.get("mime_type", "audio/wav")
    audio_bytes = base64.b64decode(audio_b64)

    print(
        f"[COLAB_TTS_TIMING] round-trip={elapsed:.2f}s "
        f"(server inference={result.get('inference_time_s', '?')}s, "
        f"audio={result.get('duration_s', '?')}s) lang={language}",
        flush=True,
    )
    return audio_bytes, mime_type


# ---------------------------------------------------------------------------
# Public API (async — call from FastAPI routes)
# ---------------------------------------------------------------------------


async def clone_voice(audio_bytes: bytes, voice_name: str, filename: str | None = None) -> str:
    """
    Clone a voice from a short reference recording (wav/webm/mp3...).

    `filename` (optional) is only used to pick the right temporary file suffix
    so the audio codec is detected correctly.

    Returns a local voice key that can later be passed to
    `synthesize_cloned_voice()`. Raises HTTPException 400/503 or
    VoiceCloneUnavailableError when the engine is missing.
    """
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file is empty.",
        )

    key = _voice_key_for(voice_name)
    out_path = _ref_wav_path(key)
    if out_path.exists():
        return key  # already cloned for this voice name

    suffix = Path(filename or "sample.wav").suffix or ".wav"
    if suffix.lower() not in {".wav", ".webm", ".ogg", ".mp3", ".m4a", ".mp4", ".aac"}:
        suffix = ".wav"

    # Normalize any common format to clean PCM WAV so Chatterbox always
    # receives valid audio.
    wav_bytes = _normalize_to_wav(audio_bytes, suffix)
    if wav_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Could not decode the uploaded audio to WAV. Please record a "
                "clear sample and try again."
            ),
        )

    try:
        CLONE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        async with _chatterbox_lock:
            await asyncio.to_thread(_load_chatterbox)
            await asyncio.to_thread(_write_ref_wav, wav_bytes, out_path)
    except VoiceCloneUnavailableError:
        raise
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Chatterbox voice cloning failed: {exc}",
        ) from exc

    return key


async def synthesize_cloned_voice(
    text: str,
    voice_key: str,
    language: str = "en",
    speed: float = 1.0,
) -> tuple[bytes, str]:
    """
    Synthesize speech with a previously cloned voice. Returns (audio bytes,
    "audio/wav"). Raises VoiceCloneUnavailableError when the engine is missing
    or HTTPException 404 when the cloned voice file is gone.

    `language` is an ISO language code ("en", "hi", ...). Chatterbox
    Multilingual V3 supports 23+ languages. For unsupported languages
    (te, ta), the caller must fall back to another engine.
    """
    ref_wav_path = _ref_wav_path(voice_key)
    if not ref_wav_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Cloned voice '{voice_key}' is not stored on this server anymore. "
                "The owner may have deleted it."
            ),
        )

    # Chatterbox doesn't support te (Telugu) or ta (Tamil) — raise immediately
    # so callers can fall back to XTTS or Edge TTS.
    if language not in SUPPORTED_LANGUAGES:
        raise VoiceSynthesisError(
            f"Chatterbox does not support language '{language}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_LANGUAGES))}"
        )

    # ── Try remote Colab first (if configured) ──────────────────────────
    if COLAB_TTS_URL and _colab_reachable is not False:
        try:
            return await _synthesize_via_colab(text, ref_wav_path, language, speed)
        except VoiceCloneUnavailableError:
            # Colab unreachable — mark it and fall through to local
            global _colab_reachable
            _colab_reachable = False
            print(
                "[CHATTERBOX] Colab unreachable, falling back to local GPU",
                flush=True,
            )
        except VoiceSynthesisError:
            raise  # Colab is up but inference failed — don't retry locally

    # ── Local synthesis (RTX 2050 / CPU fallback) ────────────────────────
    # Runtime synthesis failures are retried ONCE before giving up — they are
    # often transient.
    last_error: VoiceSynthesisError | None = None
    for attempt in (1, 2):
        try:
            async with _chatterbox_lock:
                audio = await asyncio.to_thread(
                    _synthesize_sync, text, ref_wav_path, language, speed
                )
            return audio, "audio/wav"
        except VoiceSynthesisError as exc:
            last_error = exc
            if attempt == 1:
                print(
                    "[CHATTERBOX_SYNTHESIS_FAILURE] attempt 1 failed, retrying once: "
                    f"{type(exc).__name__}: {exc!r}",
                    flush=True,
                )
        except (VoiceCloneUnavailableError, HTTPException):
            raise
        except Exception as exc:
            print(
                f"[CHATTERBOX_SYNTHESIS_FAILURE] unexpected {type(exc).__name__}: {exc!r}",
                flush=True,
            )
            last_error = VoiceSynthesisError(f"Chatterbox synthesis failed: {exc}")

    assert last_error is not None  # loop always runs at least once
    raise last_error


def delete_voice(voice_key: str) -> None:
    """Best-effort removal of a cloned voice from local storage. Never raises."""
    try:
        _ref_wav_path(voice_key).unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Synchronous helpers (run via asyncio.to_thread — they block)
# ---------------------------------------------------------------------------


def _normalize_to_wav(audio_bytes: bytes, suffix: str) -> bytes | None:
    """
    Convert any common audio container (wav/mp3/webm/ogg/m4a/aac...) to 24 kHz
    mono WAV using PyAV. Returns None when PyAV isn't available or the bytes
    can't be decoded, so callers can fall back to the raw file.
    """
    try:
        import av
    except Exception:
        return None

    try:
        container = av.open(BytesIO(audio_bytes))
    except Exception:
        return None

    stream = next((s for s in container.streams if s.type == "audio"), None)
    if stream is None:
        container.close()
        return None

    frames = []
    sample_rate = 24000
    try:
        for frame in container.decode(stream):
            if sample_rate == 24000 and frame.sample_rate:
                sample_rate = int(frame.sample_rate)
            frames.append(frame.to_ndarray())
    except Exception:
        frames = []
    finally:
        container.close()

    if not frames:
        return None

    try:
        audio = np.concatenate(frames, axis=1)
        if audio.ndim > 1:
            audio = audio.mean(axis=0)  # downmix to mono
        if np.issubdtype(audio.dtype, np.integer):
            audio = audio.astype("float32") / np.iinfo(audio.dtype).max
        else:
            audio = audio.astype("float32")

        buffer = BytesIO()
        sf.write(buffer, audio, samplerate=sample_rate, format="WAV")
        return buffer.getvalue()
    except Exception:
        return None


def _write_ref_wav(wav_bytes: bytes, out_path: Path) -> None:
    """Persist the normalized reference WAV for a cloned voice."""
    out_path.write_bytes(wav_bytes)


def _synthesize_sync(text: str, ref_wav_path: Path, language: str, speed: float) -> bytes:
    """Synchronous synthesis using Chatterbox Multilingual V3."""
    model = _load_chatterbox()
    if model is None:
        raise VoiceCloneUnavailableError(
            "The Chatterbox engine is not available in this Python environment."
        )

    try:
        import torch

        # Chatterbox doesn't have a direct speed parameter, but we can
        # note the speed for future use. For now, generate at default speed.
        _ = speed  # reserved for future speed adjustment

        t0 = time.time()
        wav = model.generate(
            text=text,
            language_id=language,
            audio_prompt_path=str(ref_wav_path),
        )
        elapsed = time.time() - t0
        print(f"[CHATTERBOX_TIMING] sentence synthesis took {elapsed:.2f}s", flush=True)

        # Log VRAM usage after generation
        if torch.cuda.is_available():
            print(
                f"[CHATTERBOX_VRAM] allocated={torch.cuda.memory_allocated() / 1024**2:.1f}MB "
                f"reserved={torch.cuda.memory_reserved() / 1024**2:.1f}MB",
                flush=True,
            )

        # Chatterbox returns a torch.Tensor (shape: [1, num_samples] or [num_samples])
        if wav is None:
            raise VoiceSynthesisError("Chatterbox returned None")

        # Convert to numpy
        if isinstance(wav, torch.Tensor):
            audio_data = wav.cpu().numpy()
        else:
            audio_data = np.asarray(wav, dtype=np.float32)

        # Squeeze batch dimension if present
        if audio_data.ndim > 1:
            audio_data = audio_data.squeeze()

        if audio_data.size == 0:
            raise VoiceSynthesisError("Chatterbox returned empty audio data")

        # Get sample rate from model
        sr = getattr(model, "sr", 24000)

        # Normalise to float32 in [-1, 1] range
        audio_data = audio_data.astype(np.float32)
        max_val = np.abs(audio_data).max()
        if max_val > 1.0:
            audio_data = audio_data / max_val

        # Convert to WAV bytes
        buffer = BytesIO()
        sf.write(buffer, audio_data, samplerate=sr, format="WAV")
        return buffer.getvalue()

    except VoiceCloneUnavailableError:
        raise  # genuine engine-missing — callers may fall back to Edge TTS quietly
    except VoiceSynthesisError:
        raise  # already logged at raise site
    except Exception as exc:
        print(
            f"[CHATTERBOX_SYNTHESIS_FAILURE] {type(exc).__name__}: {exc!r}",
            flush=True,
        )
        raise VoiceSynthesisError(f"Chatterbox synthesis failed: {exc}") from exc
