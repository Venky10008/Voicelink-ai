"""Proof test: Telugu transcription with vs without an explicit language hint.

Generates real Telugu speech via edge-tts, then asks Groq Whisper to
transcribe it (a) with auto language detection and (b) with language="te".

Usage:
    voice-venv/Scripts/python.exe bench_telugu_stt.py
"""

import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()


async def _make_telugu_sample() -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(
        "నమస్కారం! మీరు ఎలా ఉన్నారు? నాకు తెలుగులో మాట్లాడటం చాలా ఇష్టం. మనం తెలుగులోనే మాట్లాడుకుందాం.",
        voice="te-IN-ShrutiNeural",
    )
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)


async def _transcribe(sample: bytes, language: str | None) -> str:
    data: dict = {"model": "whisper-large-v3-turbo", "response_format": "json"}
    if language:
        data["language"] = language
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            data=data,
            files={"file": ("telugu.mp3", sample, "audio/mpeg")},
        )
    if response.status_code != 200:
        return f"<HTTP {response.status_code}: {response.text[:120]}>"
    return response.json().get("text", "").strip()


async def main() -> None:
    print("Generating a Telugu speech sample with edge-tts...")
    sample = await _make_telugu_sample()
    print(f"sample: {len(sample)} bytes\n")

    print("auto-detect (what the call does today):")
    auto = await _transcribe(sample, None)
    print(f"  {auto!r}\n")

    print("with language='te' (the proposed fix):")
    hinted = await _transcribe(sample, "te")
    print(f"  {hinted!r}\n")

    expected = "నమస్కారం"
    print("--- verdict ---")
    print(f"auto-detect correct: {'YES' if expected in auto else 'NO (this is the bug!)'}")
    print(f"language='te' correct: {'YES' if expected in hinted else 'NO'}")


if __name__ == "__main__":
    asyncio.run(main())
