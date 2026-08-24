"""Free local voice-cloning engine (Coqui XTTS v2) — no ElevenLabs, no API keys.

This module lets VoiceLink clone a user's voice from a short reference
recording and synthesize speech with it — 100% free and unlimited.

Engine availability
-------------------
- The `coqui-tts` package needs PyTorch, which currently only supports
  Python <= 3.12. The main backend usually runs on a newer Python, so in that
  environment `engine_available()` returns False and callers silently fall
  back to the free Edge TTS voices (the app never breaks).
- To enable real cloning, run the backend from a Python 3.11/3.12 venv
  (e.g. `backend/voice-venv`) and install torch + the engine:
      pip install torch torchaudio "coqui-tts[codec]"
      pip install "transformers==4.57.1"   # coqui-tts is broken with transformers 5.x
  (the coqui-tts fork keeps the legacy `TTS` import name, makes torch an
  explicit dependency you install yourself, and needs the `[codec]` extra
  (torchcodec) for audio IO on torch >= 2.9).
- Cloned voices are stored locally as normalized reference WAVs under
  `backend/data/cloned_voices/` (override with the VOICE_CLONE_DATA_DIR env
  var). XTTS re-runs its speaker encoder on the reference WAV at synthesis time.
- On Windows, torchaudio's torchcodec backend is often broken (missing FFmpeg
  DLLs → "Could not load libtorchcodec"). `_patch_xtts_audio_loading()` swaps
  XTTS's `load_audio` for a soundfile-based one automatically, so cloning works
  out of the box.

Hardware notes
--------------
- XTTS v2 runs on GPU (set XTTS_GPU=0 to force CPU) or CPU. On a 4GB laptop
  GPU it works but synthesizes a few seconds per sentence; CPU is slower.
- The model (~1.8 GB) is downloaded automatically from Hugging Face on first
  use.
"""

from __future__ import annotations

import asyncio
import os
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, status

from voice_keys import voice_key_for as shared_voice_key_for

CLONE_DATA_DIR = Path(os.getenv("VOICE_CLONE_DATA_DIR", "data/cloned_voices")).resolve()
XTTS_MODEL = os.getenv("XTTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
XTTS_LANGUAGE = os.getenv("XTTS_LANGUAGE", "en")

_xtts = None
_xtts_device = None
_xtts_lock = asyncio.Lock()

# Cached per-process result: importing torch + coqui-tts can take 15-60s in a
# fresh process, so we check once and reuse the answer on every later call.
_engine_available: bool | None = None


def _warm_engine_check() -> None:
    """
    Kick the slow first import (torch + coqui-tts) and model loading
    off the event loop into a background daemon thread.
    
    This ensures that endpoints like /health answer instantly, and the
    first voice synthesis call doesn't experience a 60-second loading timeout.
    """
    def warm():
        if engine_available():
            try:
                print("[xtts] Warming XTTS v2 model in background thread...", flush=True)
                _load_xtts()
                print("[xtts] Background warming complete. Model is ready.", flush=True)
            except Exception as exc:
                print(f"[xtts] Failed to pre-load XTTS model: {exc}", flush=True)

    try:
        import threading
        threading.Thread(target=warm, daemon=True).start()
    except Exception:
        pass


class VoiceCloneUnavailableError(RuntimeError):
    """Raised when the local XTTS engine cannot be used (not installed / wrong Python)."""


class VoiceSynthesisError(RuntimeError):
    """The model IS loaded but a synthesis attempt failed at runtime.

    Distinct from VoiceCloneUnavailableError so callers can retry and surface a
    visible "cloning failed" notice instead of silently swapping voices.
    """


def engine_available() -> bool:
    """True if the XTTS engine (torch + coqui-tts) can import in THIS process.

    The result is cached after the first check — importing torch + coqui-tts is
    slow (30-60s on first load), so endpoints like /health and
    /voice/my-permissions stay fast on every subsequent call.
    """
    global _engine_available
    if _engine_available is None:
        try:
            from TTS.api import TTS  # noqa: F401

            _engine_available = True
        except Exception:
            _engine_available = False
    return _engine_available


def _patch_xtts_audio_loading() -> None:
    """
    Make XTTS load reference audio with soundfile instead of torchaudio.

    torchaudio >= 2.9 routes WAV loading through the torchcodec backend, whose
    FFmpeg DLLs are frequently unavailable on Windows ("Could not load
    libtorchcodec..."). The bundled `soundfile`/libsndfile always works, so we
    swap XTTS's `load_audio` helper (the only place it calls torchaudio.load).
    """
    try:
        from TTS.tts.models import xtts as xtts_module
    except Exception:
        return  # model module not loaded yet — nothing to patch

    if getattr(xtts_module, "_load_audio_patched", False):
        return

    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio

    def _load_audio(audiopath, sampling_rate):
        """soundfile-based twin of TTS.tts.models.xtts.load_audio."""
        data, lsr = sf.read(audiopath, dtype="float32", always_2d=True)  # (frames, ch)
        data = data.T  # (ch, frames) — same shape torchaudio returns
        if data.shape[0] > 1:
            data = data.mean(axis=0, keepdims=True)  # downmix to mono
        audio = torch.from_numpy(np.ascontiguousarray(data))
        if lsr != sampling_rate:
            audio = torchaudio.functional.resample(audio, lsr, sampling_rate)
        audio = audio.clamp_(-1, 1)
        return audio

    xtts_module.load_audio = _load_audio
    xtts_module._load_audio_patched = True  # type: ignore[attr-defined]


def _load_xtts():
    """Lazily load the XTTS v2 model once (thread-safe via the caller's lock)."""
    global _xtts, _xtts_device
    if _xtts is not None:
        return _xtts, _xtts_device

    try:
        import torch
        from TTS.api import TTS as tts_api
    except Exception as exc:
        raise VoiceCloneUnavailableError(
            "The local voice engine (coqui-tts + torch) is not available in this "
            "Python environment. Run the backend from the Python 3.11 venv "
            "(backend/voice-venv) after: pip install torch torchaudio "
            "'coqui-tts[codec]' and pip install 'transformers==4.57.1'"
        ) from exc

    # torchaudio's torchcodec backend is broken on this Windows setup; make
    # XTTS load reference audio through soundfile instead.
    _patch_xtts_audio_loading()

    # Non-interactive acceptance of the Coqui non-commercial CPML license for
    # the XTTS v2 model download (same flag the fork uses in CI pipelines).
    os.environ.setdefault("COQUI_TOS_AGREED", "1")

    use_gpu = os.getenv("XTTS_GPU", "auto").strip().lower()
    if use_gpu == "auto":
        use_gpu = bool(torch.cuda.is_available())
    else:
        use_gpu = use_gpu in ("1", "true", "yes", "on")

    _xtts_device = "cuda" if use_gpu else "cpu"
    _xtts = tts_api(model_name=XTTS_MODEL, gpu=use_gpu)
    return _xtts, _xtts_device


def _voice_key_for(voice_name: str) -> str:
    """Stable local key derived from the voice name (e.g. VoiceLink_<user_id>).

    Delegates to the shared scheme so BOTH engines mint identical keys and a
    profile's key never depends on which engine was active at record time.
    """
    return shared_voice_key_for(voice_name)


def _ref_wav_path(voice_key: str) -> Path:
    """Stored normalized reference WAV that drives XTTS voice cloning."""
    return CLONE_DATA_DIR / f"{voice_key}.wav"


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

    # Normalize any common format (incl. browser webm) to clean PCM WAV so the
    # XTTS speaker encoder always receives valid audio.
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
        async with _xtts_lock:
            # Model load happens inside the lock + thread so a cold first clone
            # never blocks the event loop.
            await asyncio.to_thread(_load_xtts)  # raises if the engine is missing
            await asyncio.to_thread(_write_ref_wav, wav_bytes, out_path)
    except VoiceCloneUnavailableError:
        raise
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Local voice cloning failed: {exc}",
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

    `language` is an XTTS language code ("en", "hi", ...). XTTS v2 supports
    Hindi but NOT Telugu — callers should fall back to a Telugu Edge TTS
    voice for "te" text. Defaults to "en" for backward compatibility.
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

    # Runtime synthesis failures are retried ONCE (often transient); only a
    # genuine engine-unavailable error propagates immediately. After the retry
    # is exhausted VoiceSynthesisError is raised so callers can surface a clear
    # "cloning failed, using default voice" notice instead of failing silently.
    last_error: VoiceSynthesisError | None = None
    for attempt in (1, 2):
        try:
            async with _xtts_lock:
                # _synthesize_sync lazily loads the model inside the thread, so a
                # cold first synthesis never blocks the event loop.
                audio = await asyncio.to_thread(
                    _synthesize_sync, text, ref_wav_path, language, speed
                )
            return audio, "audio/wav"
        except VoiceSynthesisError as exc:
            last_error = exc
            if attempt == 1:
                print(
                    "[XTTS_SYNTHESIS_FAILURE] attempt 1 failed, retrying once: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
        except (VoiceCloneUnavailableError, HTTPException):
            raise
        except Exception as exc:
            print(f"[XTTS_SYNTHESIS_FAILURE] unexpected {type(exc).__name__}: {exc}", flush=True)
            last_error = VoiceSynthesisError(f"XTTS synthesis failed: {exc}")

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
        import numpy as np
        import soundfile as sf
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
    import numpy as np
    import soundfile as sf

    tts, _device = _load_xtts()
    if tts is None:
        raise VoiceCloneUnavailableError(
            "The local voice engine (coqui-tts + torch) is not available in this "
            "Python environment."
        )

    # XTTS v2 clones directly from the reference WAV on every call — the
    # speaker encoder runs on it, then the text is synthesized in that voice.
    # Language is chosen per-call (XTTS v2 supports e.g. "hi" but not "te").
    try:
        wav = tts.tts(
            text=text,
            language=language or XTTS_LANGUAGE,
            speaker_wav=str(ref_wav_path),
            speed=max(0.5, min(2.0, round(float(speed), 2))),
        )

        buffer = BytesIO()
        sf.write(buffer, np.asarray(wav, dtype=np.float32), samplerate=24000, format="WAV")
    except VoiceCloneUnavailableError:
        raise  # genuine engine-missing — callers may fall back to Edge TTS quietly
    except Exception as exc:
        print(f"[XTTS_SYNTHESIS_FAILURE] {type(exc).__name__}: {exc}", flush=True)
        raise VoiceSynthesisError(f"XTTS synthesis failed: {exc}") from exc
    return buffer.getvalue()


_warm_engine_check()
