# OmniVoice Integration

## Overview

OmniVoice is an open-source, Apache 2.0 licensed voice cloning engine that supports
600+ languages with superior voice cloning quality. It's integrated as an alternative
to the existing Coqui XTTS v2 engine.

## Key Features

- **600+ languages supported** (vs ~17 for XTTS v2)
- **Zero-shot voice cloning** (no training required)
- **Voice design from text descriptions**
- **Fast inference** (40x faster than real-time on GPU)
- **Cross-lingual voice cloning**
- **Free and open-source** (Apache 2.0 license)

## Installation

### Basic Installation (CPU)

```bash
pip install omnivoice torch torchaudio
```

### NVIDIA GPU Support

```bash
# Install PyTorch with CUDA support (replace cu128 with your CUDA version)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install omnivoice
```

### Apple Silicon

```bash
pip install torch torchaudio
pip install omnivoice
```

## Architecture

The system uses a priority-based engine selection:

1. **OmniVoice** (preferred) - If available, uses the newer engine with 600+ languages
2. **XTTS v2** (fallback) - Uses the existing engine with ~17 languages
3. **Edge TTS** (final fallback) - Uses Microsoft Edge TTS if neither engine is available

## Usage

### Voice Cloning

```python
from omnivoice_engine import clone_voice, synthesize_cloned_voice

# Clone a voice from a reference audio file
voice_key = await clone_voice(audio_bytes, "user_voice_name", filename="reference.wav")

# Synthesize speech with the cloned voice
audio_bytes, mime_type = await synthesize_cloned_voice(
    "Hello, this is my cloned voice!",
    voice_key,
    language="en",  # Supports 600+ languages
    speed=1.0
)
```

### Engine Availability Check

```python
from omnivoice_engine import engine_available

if engine_available():
    print("OmniVoice is ready to use!")
else:
    print("OmniVoice is not installed")
```

## API Endpoints

### Health Check

The `/health` endpoint now shows which voice cloning engine is available:

```json
{
  "status": "ok",
  "voice_clone_engine": "omnivoice (local, free, 600+ languages)",
  "omnivoice_available": true,
  "xtts_available": false,
  ...
}
```

### Voice Sharing

The voice sharing endpoints (`/voice/*`) automatically use OmniVoice if available,
falling back to XTTS v2 or Edge TTS as needed.

## Configuration

### Environment Variables

- `VOICE_CLONE_DATA_DIR` - Directory to store cloned voice data (default: `data/cloned_voices`)
- `OMNIVOICE_MODEL` - HuggingFace model ID (default: `k2-fsa/OmniVoice`)

### GPU Configuration

OmniVoice automatically detects and uses:
- NVIDIA CUDA GPUs (preferred)
- Apple Silicon MPS
- CPU (fallback)

## Performance

### Benchmark Results

- **RTF (Real-Time Factor)**: 0.025 on H100 GPU (40x faster than real-time)
- **Speaker Similarity**: 0.830 (vs 0.655 for ElevenLabs)
- **Word Error Rate**: 2.85% (vs 10.95% for ElevenLabs)

### Hardware Requirements

- **GPU**: Recommended for production use
- **RAM**: 4GB+ recommended
- **Storage**: ~2GB for model download

## Testing

Run the end-to-end test:

```bash
cd backend
python test_omnivoice_e2e.py
```

## Troubleshooting

### Common Issues

1. **Import Error**: `No module named 'soundfile'`
   - Install soundfile: `pip install soundfile`

2. **Model Download Fails**
   - Set HuggingFace mirror: `export HF_ENDPOINT="https://hf-mirror.com"`

3. **GPU Not Detected**
   - Ensure CUDA drivers are installed
   - Check PyTorch CUDA support: `python -c "import torch; print(torch.cuda.is_available())"`

4. **Memory Issues**
   - Use CPU mode: Set `OMNIVOICE_DEVICE=cpu`
   - Reduce batch size if processing multiple voices

## Comparison with XTTS v2

| Feature | OmniVoice | XTTS v2 |
|---------|-----------|---------|
| Languages | 600+ | ~17 |
| License | Apache 2.0 | CPML (non-commercial) |
| Voice Cloning Quality | Superior | Good |
| Inference Speed | Faster (GPU) | Good |
| Model Size | ~1.8GB | ~1.8GB |
| Training Data | 581k hours | Multi-dataset |

## Migration from XTTS v2

The integration is backward-compatible:

1. Existing voice profiles continue to work
2. No changes needed to the frontend
3. Automatic engine selection based on availability
4. Graceful fallback to Edge TTS if neither engine is available

## References

- [OmniVoice GitHub](https://github.com/k2-fsa/OmniVoice)
- [OmniVoice Paper](https://arxiv.org/abs/2604.00688)
- [HuggingFace Model](https://huggingface.co/k2-fsa/OmniVoice)