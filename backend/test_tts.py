"""Smoke test for the free edge-tts engine used by the app.

Usage:
    python test_tts.py [voice] [rate] [pitch]

Examples:
    python test_tts.py
    python test_tts.py en-US-GuyNeural +25% +15Hz
"""

import asyncio
import sys


async def main() -> None:
    import edge_tts

    voice = sys.argv[1] if len(sys.argv) > 1 else "en-US-AriaNeural"
    rate = sys.argv[2] if len(sys.argv) > 2 else "+0%"
    pitch = sys.argv[3] if len(sys.argv) > 3 else "+0Hz"

    communicate = edge_tts.Communicate(
        "Hello! This is a test of the free voice engine.",
        voice=voice,
        rate=rate,
        pitch=pitch,
    )
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])

    print(f"OK: synthesized {len(audio)} bytes (voice={voice}, rate={rate}, pitch={pitch})")
    if not audio:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
