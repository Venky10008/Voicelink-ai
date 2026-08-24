"""Benchmark: local CPU Whisper vs Groq cloud Whisper for voice-call transcription.

Generates a ~4s speech sample with edge-tts, then times:
  1) local faster-whisper "small" (exactly what the voice call used before)
  2) Groq hosted whisper-large-v3-turbo (candidate replacement)

Usage:
    voice-venv/Scripts/python.exe bench_stt.py
"""

import asyncio
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()


async def _make_sample() -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(
        "Hello, how are you doing today? I hope you are having a wonderful time.",
        voice="en-US-AriaNeural",
    )
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)


def _bench_local(sample: bytes, filename: str) -> float:
    from faster_whisper import WhisperModel

    t0 = time.time()
    model = WhisperModel("small", device="cpu", compute_type="int8")
    t_load = time.time() - t0

    tmp = Path("_bench_audio.webm")
    tmp.write_bytes(sample)
    t0 = time.time()
    segments, _info = model.transcribe(
        str(tmp),
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    t_transcribe = time.time() - t0
    tmp.unlink(missing_ok=True)

    print(f"[local]  model load {t_load:5.1f}s | transcribe {t_transcribe:5.2f}s | {text!r}")
    return t_transcribe


async def _bench_groq(sample: bytes, filename: str) -> float:
    import httpx

    if not GROQ_API_KEY:
        print("[groq]  no GROQ_API_KEY — skipping")
        return float("inf")

    t0 = time.time()
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            data={"model": "whisper-large-v3-turbo", "response_format": "json"},
            files={"file": (filename, sample, "audio/mpeg")},
        )
    dt = time.time() - t0
    if response.status_code != 200:
        print(f"[groq]  FAILED {response.status_code}: {response.text[:200]}")
        return float("inf")
    text = response.json().get("text", "").strip()
    print(f"[groq]   transcribe {dt:5.2f}s | {text!r}")
    return dt


async def main() -> None:
    print("Generating a ~4s speech sample with edge-tts...")
    sample = await _make_sample()
    print(f"sample: {len(sample)} bytes\n")

    local_t = _bench_local(sample, "sample.mp3")
    groq_t = await _bench_groq(sample, "sample.mp3")

    print("\n--- summary ---")
    print(f"local CPU Whisper: {local_t:.2f}s")
    print(f"Groq cloud Whisper: {groq_t:.2f}s" if groq_t != float("inf") else "Groq cloud Whisper: failed")
    if groq_t != float("inf"):
        print(f"speedup: {local_t / groq_t:.1f}x")


if __name__ == "__main__":
    asyncio.run(main())
