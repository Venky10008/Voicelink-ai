"""List the Microsoft Edge TTS voices available via edge-tts (free)."""

import asyncio


async def main() -> None:
    import edge_tts

    voices = await edge_tts.list_voices()
    print(f"Total voices available: {len(voices)}")
    for v in voices:
        if v.get("Locale", "").startswith("en-US"):
            print(
                f"{v.get('ShortName')} — {v.get('Gender')} — {v.get('FriendlyName')}"
            )


if __name__ == "__main__":
    asyncio.run(main())
