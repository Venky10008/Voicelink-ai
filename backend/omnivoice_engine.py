"""OmniVoice voice-cloning engine — free, open-source, Apache 2.0 licensed.

This module provides voice cloning using OmniVoice, a state-of-the-art
massively multilingual zero-shot text-to-speech (TTS) model supporting
over 600 languages. It's an alternative to the Coqui XTTS v2 engine.

Engine availability
-------------------
- OmniVoice requires PyTorch and the omnivoice package.
- Install with: pip install omnivoice
- For NVIDIA GPU support: pip install torch torchaudio (with appropriate CUDA version)
- For Apple Silicon: pip install torch torchaudio
- For CPU-only: pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

Hardware notes
--------------
- OmniVoice runs on GPU (recommended) or CPU.
- GPU inference is significantly faster (RTF as low as 0.025).
- CPU inference works but is slower.
- The model (~1.8 GB) is downloaded automatically from Hugging Face on first use.

Key features of OmniVoice:
- 600+ languages supported
- Zero-shot voice cloning (no training required)
- Voice design from text descriptions
- Fast inference (40x faster than real-time on GPU)
- Cross-lingual voice cloning
"""

from __future__ import annotations

import asyncio
import os
from io import BytesIO
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import HTTPException, status

from voice_keys import voice_key_for as shared_voice_key_for

CLONE_DATA_DIR = Path(os.getenv("VOICE_CLONE_DATA_DIR", "data/cloned_voices")).resolve()
OMNIVOICE_MODEL = os.getenv("OMNIVOICE_MODEL", "k2-fsa/OmniVoice")

_omnivoice_model = None
_omnivoice_lock = asyncio.Lock()

# Cached per-process result: importing torch + omnivoice can take time in a
# fresh process, so we check once and reuse the answer on every later call.
_engine_available: bool | None = None


def _warm_engine_check() -> None:
    """
    Kick the slow first import (torch + omnivoice) off the event loop.

    Runs in a daemon thread at module import so /health and
    /voice/my-permissions answer instantly once warmed. Fail-safe: if the
    thread fails, engine_available() lazily performs the check on first use.
    """
    try:
        import threading

        threading.Thread(target=engine_available, daemon=True).start()
    except Exception:
        pass


class VoiceCloneUnavailableError(RuntimeError):
    """Raised when the OmniVoice engine cannot be used (not installed / wrong Python)."""


class VoiceSynthesisError(RuntimeError):
    """The model IS loaded but a synthesis attempt failed at runtime
    (OOM, CUDA error, malformed output, empty result...).

    Deliberately distinct from VoiceCloneUnavailableError so callers can tell a
    genuine "engine missing" (legitimate Edge TTS fallback) apart from a runtime
    failure that should be retried and surfaced to the user instead of silently
    swapping in a completely different-sounding voice.
    """


def engine_available() -> bool:
    """True if the OmniVoice engine (torch + omnivoice) can import in THIS process.

    The result is cached after the first check — importing torch + omnivoice is
    slow (30-60s on first load), so endpoints like /health and
    /voice/my-permissions stay fast on every subsequent call.
    """
    global _engine_available
    if _engine_available is None:
        try:
            from omnivoice import OmniVoice  # noqa: F401

            _engine_available = True
        except Exception:
            _engine_available = False
    return _engine_available


def _load_omnivoice():
    """Lazily load the OmniVoice model once (thread-safe via the caller's lock)."""
    global _omnivoice_model
    if _omnivoice_model is not None:
        return _omnivoice_model

    try:
        import torch
        from omnivoice import OmniVoice
    except Exception as exc:
        raise VoiceCloneUnavailableError(
            "The OmniVoice engine is not available in this "
            "Python environment. Install with: pip install omnivoice\n"
            "For GPU support: pip install torch torchaudio (with appropriate CUDA version)"
        ) from exc

    # Determine device based on availability
    if torch.cuda.is_available():
        device_map = "cuda:0"
        dtype = torch.float16
    elif hasattr(torch, "mps") and torch.mps.is_available():
        device_map = "mps"
        dtype = torch.float32
    else:
        device_map = "cpu"
        dtype = torch.float32

    try:
        _omnivoice_model = OmniVoice.from_pretrained(
            OMNIVOICE_MODEL,
            device_map=device_map,
            dtype=dtype,
        )
        print(f"[omnivoice] Model loaded on {device_map} with {dtype}", flush=True)
    except Exception as exc:
        raise VoiceCloneUnavailableError(
            f"Failed to load OmniVoice model: {exc}"
        ) from exc

    return _omnivoice_model


def _voice_key_for(voice_name: str) -> str:
    """Stable local key derived from the voice name (e.g. VoiceLink_<user_id>).

    Delegates to the shared scheme so BOTH engines mint identical keys and a
    profile's key never depends on which engine was active at record time.
    """
    return shared_voice_key_for(voice_name)


def _ref_wav_path(voice_key: str) -> Path:
    """Stored normalized reference WAV that drives OmniVoice voice cloning."""
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
    # OmniVoice speaker encoder always receives valid audio.
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
        async with _omnivoice_lock:
            # Model load happens inside the lock + thread so a cold first clone
            # never blocks the event loop.
            await asyncio.to_thread(_load_omnivoice)  # raises if the engine is missing
            await asyncio.to_thread(_write_ref_wav, wav_bytes, out_path)
    except VoiceCloneUnavailableError:
        raise
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OmniVoice voice cloning failed: {exc}",
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

    `language` is an ISO language code ("en", "hi", ...). OmniVoice supports
    600+ languages, so more languages are available compared to XTTS v2.
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

    # Runtime synthesis failures (OOM, CUDA hiccups, bad output...) are retried
    # ONCE before giving up — they are often transient. Only a genuine
    # engine-unavailable error propagates immediately. After the retry is
    # exhausted, VoiceSynthesisError is raised so callers can surface a clear
    # "cloning failed, using default voice" notice instead of failing silently.
    last_error: VoiceSynthesisError | None = None
    for attempt in (1, 2):
        try:
            async with _omnivoice_lock:
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
                    "[OMNIVOICE_SYNTHESIS_FAILURE] attempt 1 failed, retrying once: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
        except (VoiceCloneUnavailableError, HTTPException):
            raise
        except Exception as exc:
            print(
                f"[OMNIVOICE_SYNTHESIS_FAILURE] unexpected {type(exc).__name__}: {exc}",
                flush=True,
            )
            last_error = VoiceSynthesisError(f"OmniVoice synthesis failed: {exc}")

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
    """Synchronous synthesis using OmniVoice."""
    model = _load_omnivoice()
    if model is None:
        raise VoiceCloneUnavailableError(
            "The OmniVoice engine is not available in this Python environment."
        )

    try:
        # OmniVoice voice cloning.
        # Pass language so the model knows which phoneme set to use —
        # critical for Indian languages (hi/te/ta) vs English.
        generate_kwargs: dict = {
            "text": text,
            "ref_audio": str(ref_wav_path),
            "speed": max(0.5, min(2.0, round(float(speed), 2))),
            "language": language,
        }
        # Always pass language — if OmniVoice's generate() doesn't accept it,
        # the error is visible and debuggable instead of silently ignored.

        import time as _time
        _t0 = _time.time()
        audio = model.generate(**generate_kwargs)
        _elapsed = _time.time() - _t0
        print(f"[OMNIVOICE_TIMING] sentence synthesis took {_elapsed:.2f}s", flush=True)
        try:
            import torch as _torch
            if _torch.cuda.is_available():
                print(
                    f"[OMNIVOICE_VRAM] allocated={_torch.cuda.memory_allocated() / 1024**2:.1f}MB "
                    f"reserved={_torch.cuda.memory_reserved() / 1024**2:.1f}MB",
                    flush=True,
                )
        except Exception:
            pass

        # OmniVoice may return:
        #   - A list of numpy arrays, e.g. [array(shape=(T,))]
        #   - A single numpy array
        #   - A torch.Tensor
        # Handle all cases defensively.
        audio_data: np.ndarray | None = None

        if audio is None:
            print(
                "[OMNIVOICE_SYNTHESIS_FAILURE] ValueError: OmniVoice returned None",
                flush=True,
            )
            raise VoiceSynthesisError("OmniVoice returned None")

        try:
            import torch
            if isinstance(audio, torch.Tensor):
                audio_data = audio.cpu().numpy()
                if audio_data.ndim > 1:
                    audio_data = audio_data.squeeze()
        except ImportError:
            pass

        if audio_data is None:
            if isinstance(audio, list):
                if len(audio) == 0:
                    print(
                        "[OMNIVOICE_SYNTHESIS_FAILURE] ValueError: "
                        "OmniVoice returned an empty list",
                        flush=True,
                    )
                    raise VoiceSynthesisError("OmniVoice returned empty list")
                audio_data = np.asarray(audio[0], dtype=np.float32)
            else:
                audio_data = np.asarray(audio, dtype=np.float32)

            if audio_data.ndim > 1:
                audio_data = audio_data.squeeze()

        if audio_data is None or audio_data.size == 0:
            print(
                "[OMNIVOICE_SYNTHESIS_FAILURE] ValueError: "
                "OmniVoice returned empty audio data",
                flush=True,
            )
            raise VoiceSynthesisError("OmniVoice returned empty audio data")

        # Normalise to float32 in [-1, 1] range.
        audio_data = audio_data.astype(np.float32)
        max_val = np.abs(audio_data).max()
        if max_val > 1.0:
            audio_data = audio_data / max_val

        # Convert to WAV bytes
        buffer = BytesIO()
        sf.write(buffer, audio_data, samplerate=24000, format="WAV")
        return buffer.getvalue()

    except VoiceCloneUnavailableError:
        raise  # genuine engine-missing — callers may fall back to Edge TTS quietly
    except VoiceSynthesisError:
        raise  # already logged at raise site
    except Exception as exc:
        print(
            f"[OMNIVOICE_SYNTHESIS_FAILURE] {type(exc).__name__}: {exc}",
            flush=True,
        )
        raise VoiceSynthesisError(f"OmniVoice synthesis failed: {exc}") from exc


_warm_engine_check()