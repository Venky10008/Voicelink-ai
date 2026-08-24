"""Speech-to-text (Groq cloud Whisper + faster-whisper fallback) and TTS (edge-tts, free)."""

from __future__ import annotations

import asyncio
import base64
import os
import re
import tempfile
from pathlib import Path

import httpx
from fastapi import HTTPException, status

from voice_catalog import (
    get_builtin_voice,
    get_edge_voice_name,
    get_language_default_voice,
    match_voice_for_language,
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

# Fast hosted Whisper on Groq — the same key used for chat. This is what voice
# calls use so replies start in seconds instead of ~40s of local CPU Whisper.
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo").strip()

# "large-v3-turbo" is the best balance of accuracy and speed for Indian
# languages (Hindi/Telugu/Tamil). It's 4x faster than large-v3 while
# maintaining 95% accuracy. Override with WHISPER_MODEL in .env.
# First use downloads the model (~809 MB) once. This is now the FALLBACK path
# (used only when Groq transcription is unavailable).
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3-turbo").strip()

# Unicode ranges used by detect_language() for a cheap, script-based guess.
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")  # Hindi (and other Indic scripts)
_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
_TELUGU_RE = re.compile(r"[\u0C00-\u0C7F]")


def detect_language(text: str) -> str:
    """
    Rough script-based language detection for TTS voice selection.

    Looks at the characters actually used in the text: Telugu script → "te",
    Tamil → "ta", Devanagari → "hi", anything else → "en". This is instant
    and free (no extra AI call) and is reliable because the AI reply is
    written in the same script the user used.
    """
    if not text:
        return "en"
    if _TELUGU_RE.search(text):
        return "te"
    if _TAMIL_RE.search(text):
        return "ta"
    if _DEVANAGARI_RE.search(text):
        return "hi"
    return "en"

_whisper_model = None
_whisper_lock = asyncio.Lock()


def _load_whisper_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "faster-whisper is not installed. Run: pip install faster-whisper"
            ),
        ) from exc

    # CPU-friendly default; first run downloads the model.
    _whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper_model


def _transcribe_sync(
    audio_path: Path, beam_size: int, condition_on_previous_text: bool,
    language: str | None = None,
) -> str:
    model = _load_whisper_model()
    segments, _info = model.transcribe(
        str(audio_path),
        beam_size=beam_size,
        vad_filter=True,
        condition_on_previous_text=condition_on_previous_text,
        language=language,  # None → Whisper auto-detect
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return text


_STT_MIME = {
    "mp3": "audio/mpeg",
    "mpeg": "audio/mpeg",
    "mpga": "audio/mpeg",
    "wav": "audio/wav",
    "webm": "audio/webm",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "aac": "audio/aac",
    "flac": "audio/flac",
}


async def transcribe_audio_groq(
    audio_bytes: bytes,
    filename: str,
    language: str | None = None,
) -> str | None:
    """Transcribe with Groq's hosted Whisper (fast, cloud).

    Returns the transcript, or None on ANY failure (missing key, rate limit,
    network error...) so callers can fall back to the local CPU model. The
    free tier allows 20 requests/min and ~2 hours of audio per hour.
    """
    if not audio_bytes or not GROQ_API_KEY:
        return None

    suffix = Path(filename or "audio.webm").suffix.lstrip(".").lower()
    mime = _STT_MIME.get(suffix, "audio/webm")
    data: dict = {"model": GROQ_STT_MODEL, "response_format": "json"}
    if language:
        data["language"] = language

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GROQ_STT_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                data=data,
                files={"file": (filename or "audio.webm", audio_bytes, mime)},
            )
    except Exception as exc:
        print(f"[stt] Groq transcription request failed: {exc}", flush=True)
        return None

    if response.status_code != 200:
        print(
            f"[stt] Groq transcription failed ({response.status_code}): "
            f"{response.text[:200]}",
            flush=True,
        )
        return None

    try:
        text = response.json().get("text", "").strip()
    except Exception as exc:
        print(f"[stt] Groq transcription response parse failed: {exc}", flush=True)
        return None
    return text or None


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    *,
    beam_size: int = 5,
    condition_on_previous_text: bool = True,
    language: str | None = None,
) -> str:
    """Transcribe recorded audio to text with faster-whisper.

    The keyword arguments tune the speed/quality tradeoff. The default
    (beam_size=5) keeps the existing behaviour; live voice calls pass
    beam_size=1 + condition_on_previous_text=False, which is roughly 2x
    faster on CPU with only a small quality difference for short clips.
    `language` pins Whisper to one language instead of auto-detecting.
    """
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file is empty.",
        )

    suffix = Path(filename or "audio.wav").suffix or ".wav"
    if suffix.lower() not in {".wav", ".webm", ".ogg", ".mp3", ".m4a", ".mp4", ".aac"}:
        suffix = ".wav"

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)

        async with _whisper_lock:
            text = await asyncio.to_thread(
                _transcribe_sync, tmp_path, beam_size, condition_on_previous_text, language
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Speech transcription failed: {exc}",
        ) from exc
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not transcribe audio. Try speaking clearly and record again.",
        )

    return text


async def synthesize_speech(
    text: str,
    voice_id: str | None = None,
    speed: float | None = None,
    pitch: float | None = None,
    language: str | None = None,
) -> tuple[bytes, str]:
    """
    Synthesize speech with Microsoft Edge TTS — free and unlimited (no API key).

    `voice_id` is an app-level voice id ("aria") or an edge-tts voice name.
    When it's None, the voice is chosen automatically from `language` (or
    detected from the text's script) — so a Hindi reply is spoken by a
    Hindi voice and a Telugu reply by a Telugu voice.
    `speed` maps to edge-tts rate (capped at ±50%). `pitch` maps to edge-tts
    pitch in Hz (capped at ±50Hz). Both default to neutral when not provided.
    """
    try:
        import edge_tts
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="edge-tts is not installed. Run: pip install edge-tts",
        ) from exc

    if voice_id is None:
        # No explicit voice → pick the default voice for the reply's language.
        lang = language or detect_language(text)
        voice = get_language_default_voice(lang)
    else:
        # Explicit voice → keep its character, but if the reply is in another
        # language, match it to the closest voice of that language so the
        # spoken language is always perfect (e.g. "Aria" + Telugu reply → the
        # warm female Telugu voice). Unknown ids keep the old fallback.
        builtin = get_builtin_voice(voice_id)
        if builtin is not None:
            lang = language or detect_language(text)
            voice = match_voice_for_language(builtin, lang)["edge_tts_voice"]
        else:
            voice = get_edge_voice_name(voice_id)

    rate = "+0%"
    if speed is not None:
        pct = round((speed - 1.0) * 100)
        rate = f"{max(-50, min(50, pct)):+d}%"

    pitch_hz = "+0Hz"
    if pitch is not None:
        pct = round((pitch - 1.0) * 100)
        pitch_hz = f"{max(-50, min(50, pct)):+d}Hz"

    try:
        communicate = edge_tts.Communicate(
            text, voice=voice, rate=rate, pitch=pitch_hz
        )
        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Edge TTS synthesis failed: {exc}",
        ) from exc

    if not audio:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Edge TTS returned empty audio.",
        )

    return bytes(audio), "audio/mpeg"


def audio_to_base64(audio_bytes: bytes) -> str:
    return base64.b64encode(audio_bytes).decode("ascii")
