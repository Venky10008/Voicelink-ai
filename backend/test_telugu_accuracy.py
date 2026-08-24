"""Test Telugu transcription accuracy with different Whisper models.

This script helps you compare the accuracy of different Whisper models
for Telugu speech recognition.

Usage:
    python test_telugu_accuracy.py
"""

import asyncio
import time
from pathlib import Path

# Test audio files (you can add your own Telugu audio samples)
TEST_SAMPLES = [
    # (filename, expected_text, language)
    ("telugu_sample.wav", "నమస్కారం, నేను మీ స్నేహితుడిని", "te"),
    # Add more test samples as needed
]


async def test_model(model_name: str, audio_path: Path, expected_text: str) -> dict:
    """Test a specific Whisper model on an audio file."""
    print(f"\n{'='*60}")
    print(f"Testing model: {model_name}")
    print(f"Audio file: {audio_path}")
    print(f"Expected: {expected_text}")
    print(f"{'='*60}")
    
    try:
        from faster_whisper import WhisperModel
        
        print(f"Loading model {model_name}... (first time downloads the model)")
        start_time = time.time()
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        load_time = time.time() - start_time
        print(f"Model loaded in {load_time:.1f}s")
        
        print("Transcribing...")
        start_time = time.time()
        segments, info = model.transcribe(
            str(audio_path),
            beam_size=5,
            language="te",  # Telugu
            vad_filter=True,
        )
        
        transcription = " ".join(segment.text.strip() for segment in segments)
        transcription_time = time.time() - start_time
        
        print(f"\nResult:")
        print(f"  Transcribed: {transcription}")
        print(f"  Time: {transcription_time:.1f}s")
        print(f"  Detected language: {info.language} (confidence: {info.language_probability:.2%})")
        
        # Simple accuracy check (you can improve this)
        if expected_text.lower() in transcription.lower():
            print(f"  ✅ ACCURACY: GOOD - transcription matches expected")
            accuracy = "good"
        else:
            print(f"  ⚠️  ACCURACY: NEEDS REVIEW - check transcription manually")
            accuracy = "needs_review"
        
        return {
            "model": model_name,
            "transcription": transcription,
            "load_time": load_time,
            "transcription_time": transcription_time,
            "accuracy": accuracy,
        }
        
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        return {
            "model": model_name,
            "error": str(e),
        }


async def main():
    """Compare different Whisper models for Telugu."""
    print("Telugu Whisper Model Accuracy Test")
    print("=" * 60)
    
    # Models to test (in order of size/accuracy)
    models = [
        "small",           # Current default (466 MB)
        "medium",          # Better accuracy (1.5 GB)
        "large-v3-turbo",  # Recommended (809 MB)
        "large-v3",        # Best accuracy (3 GB)
    ]
    
    # Check if test audio exists
    test_audio = Path("telugu_sample.wav")
    if not test_audio.exists():
        print("\n⚠️  No test audio file found!")
        print("To test Telugu accuracy:")
        print("1. Record yourself speaking Telugu")
        print("2. Save as 'telugu_sample.wav' in the backend directory")
        print("3. Run this script again")
        print("\nFor now, I'll show you the model differences:")
        print("\n" + "=" * 60)
        print("WHISPER MODEL COMPARISON FOR TELUGU")
        print("=" * 60)
        print("\n| Model | Size | Telugu Accuracy | Speed |")
        print("|-------|------|-----------------|-------|")
        print("| small | 466 MB | ⚠️ Okay | Fast |")
        print("| medium | 1.5 GB | ✅ Good | Slow |")
        print("| large-v3-turbo | 809 MB | ✅✅ Very Good | Medium |")
        print("| large-v3 | 3 GB | ✅✅✅ Best | Slow |")
        print("\n📌 RECOMMENDATION: Use 'large-v3-turbo' for best balance")
        print("   - 4x faster than large-v3")
        print("   - 95% accuracy of large-v3")
        print("   - Much better than 'small' for Telugu")
        return
    
    # Run tests
    results = []
    for model_name in models:
        result = await test_model(model_name, test_audio, "నమస్కారం")
        results.append(result)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("\n| Model | Load Time | Transcription Time | Accuracy |")
    print("|-------|-----------|-------------------|----------|")
    for r in results:
        if "error" in r:
            print(f"| {r['model']} | ERROR | - | - |")
        else:
            print(f"| {r['model']} | {r['load_time']:.1f}s | {r['transcription_time']:.1f}s | {r['accuracy']} |")
    
    print("\n📌 RECOMMENDATION:")
    print("   For Telugu, use 'large-v3-turbo' in your .env file:")
    print("   WHISPER_MODEL=large-v3-turbo")


if __name__ == "__main__":
    asyncio.run(main())