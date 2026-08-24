"""End-to-end test of the OmniVoice voice cloning pipeline.

Generates a reference sample with edge-tts (as a stand-in for a user
recording), clones it via omnivoice_engine.clone_voice(), then synthesizes
speech with synthesize_cloned_voice(). Prints timings so we can judge whether
the engine is real and usable.

Usage:
    python test_omnivoice_e2e.py
"""

import asyncio
import io
import time

import soundfile as sf


async def _make_reference_sample() -> bytes:
    """Synthesize a ~6s reference 'voice' with edge-tts, return WAV bytes."""
    import edge_tts

    communicate = edge_tts.Communicate(
        "Hello, this is my voice. I use it every day to talk with my AI companion.",
        voice="en-US-AriaNeural",
    )
    mp3 = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3.extend(chunk["data"])

    import av  # PyAV decodes mp3 -> wav so OmniVoice gets clean PCM

    container = av.open(io.BytesIO(bytes(mp3)))
    stream = next(s for s in container.streams if s.type == "audio")
    frames = [f.to_ndarray() for f in container.decode(stream)]
    container.close()
    import numpy as np

    audio = np.concatenate(frames, axis=1)
    if audio.ndim > 1:
        audio = audio.mean(axis=0)
    buf = io.BytesIO()
    sf.write(buf, audio.astype("float32"), samplerate=24000, format="WAV")
    return buf.getvalue()


async def main() -> None:
    from omnivoice_engine import clone_voice, synthesize_cloned_voice, engine_available

    print("1) Checking OmniVoice engine availability...")
    if not engine_available():
        print("   OmniVoice engine is NOT available. Skipping test.")
        print("   Install with: pip install omnivoice torch torchaudio")
        return

    print("   OmniVoice engine is available!")

    print("2) Generating a reference voice sample (edge-tts)...")
    sample = await _make_reference_sample()
    print(f"   reference sample: {len(sample)} bytes")

    print("3) Cloning the voice (loads OmniVoice model on first run, can take a while)...")
    t0 = time.time()
    key = await clone_voice(sample, "omnivoice_test_voice", filename="ref.wav")
    print(f"   cloned OK in {time.time() - t0:.1f}s -> voice key: {key}")

    print("4) Synthesizing speech with the cloned voice...")
    t1 = time.time()
    audio, mime = await synthesize_cloned_voice(
        "Hello! This is my cloned voice using OmniVoice, speaking back to you.",
        key,
        speed=1.0,
    )
    dt = time.time() - t1
    print(f"   synthesized {len(audio)} bytes ({mime}) in {dt:.1f}s")
    print(f"   audio duration: {len(audio) / (24000 * 2):.1f}s")

    # 5) Verify the bytes are a real, non-silent WAV.
    import numpy as np

    data, sr = sf.read(io.BytesIO(audio), dtype="float32")
    peak = float(np.abs(data).max())
    rms = float(np.sqrt((data**2).mean()))
    print(f"   WAV parse OK: {sr} Hz, {len(data) / sr:.1f}s, peak={peak:.3f}, rms={rms:.4f}")
    assert sr == 24000 and len(data) > 8000 and peak > 0.05, "Audio looks invalid!"
    print("\nOMNIVOICE CLONE PIPELINE E2E: OK")


if __name__ == "__main__":
    asyncio.run(main())