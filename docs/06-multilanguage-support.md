# 06 — Multi-Language Support (English · हिन्दी · తెలుగు)

Added **August 11, 2026** after the user asked: *"do personalities and default
voices work in other languages like Telugu, Hindi, English perfectly?"*

Answer before: chat worked in any language, but the spoken voice was English-only.
Answer now: the app speaks (and listens) in the language you use — Hindi, Telugu
and English — automatically, plus the Voice Library has dedicated Hindi and
Telugu voices you can pick manually.

---

## What changed

### 1. New voices — Voice Library is now 10 voices
`backend/voice_catalog.py` gains 4 voices (all free Edge TTS, no API key):
Swara, Madhur, Shruti, Mohan. The UI shows no language labels — every voice
is a character (gender + vibe), and every voice speaks every language.

### 2. Every voice speaks every language (character matching)
`backend/voice_service.py` adds `detect_language(text)` — an instant, free
script check (Telugu script → `te`, Devanagari → `hi`, else `en`).

- **Explicit voice chosen (e.g. "Aria"):** Edge TTS voices are language-native,
  so a voice can only pronounce its own language perfectly. Instead of letting
  an English voice butcher Telugu, `match_voice_for_language()` keeps the
  voice's *character* and picks the closest voice in the reply's language:
  same family (gender + vibe) → same gender → that language's default voice.
  So Aria + Telugu reply → the warm female Telugu voice; Kai + Hindi reply →
  the deep male Hindi voice. Same feel, perfect pronunciation.
- **No explicit voice:** the reply's language picks its default voice
  (`en-US-AriaNeural` / `hi-IN-MadhurNeural` / `te-IN-ShrutiNeural`,
  overridable via `DEFAULT_EDGE_TTS_VOICE`, `HINDI_EDGE_TTS_VOICE`,
  `TELUGU_EDGE_TTS_VOICE`).
- **Cloned voices:** XTTS v2 supports Hindi — the clone now speaks the reply's
  language (`hi` or `en`) instead of being hard-coded to English. **Telugu is
  NOT supported by XTTS v2**, so Telugu replies automatically use the natural
  Telugu Edge TTS voice (better than a wrong-sounding clone).
- **Chat:** the system prompt now explicitly instructs the AI to reply in the
  same language the user writes in (Hindi/Telugu/English), so all
  personalities — including the new **Girlfriend** — work in any language.
- **Voice previews** say hello in the voice's native language
  ("नमस्ते! ...", "నమస్కారం! ...").

### 3. Better listening for Indian languages
`WHISPER_MODEL` default changed from `base` to `small` (`backend/voice_service.py`)
— markedly better Hindi/Telugu transcription while still fast on CPU. The first
voice call downloads the model once (~460 MB). Override anytime via `.env`.

### 4. Frontend
`frontend/src/routes/voices.tsx` shows all 10 voices in one flat grid — no
language labels or sections anywhere. `personalities.tsx` adds the new
**Girlfriend** personality card.

---

## Honest limitations (read before promising "perfect")

1. **Romanized Hindi/Telugu is not detected.** If someone types "aap kaise ho"
   in Latin letters, the voice picks the English default. Detection works on
   native script only (Devanagari / Telugu). The AI still *replies* correctly
   either way — this only affects which voice speaks.
2. **Marathi/Nepali/Sanskrit** also use Devanagari → they get the Hindi voice.
   Acceptable for now; a full language picker is the proper fix.
3. **Character matching is a swap, not a clone.** "Aria" speaking Telugu is
   the warm *female* Telugu voice — the same feel, but not literally Aria's
   timbre. Edge TTS can't make one voice pronounce multiple languages
   natively; this is the closest free approach.
4. **Whisper "small" is good, not perfect** at Telugu. `medium` is better but
   noticeably slower on CPU.

## Files touched
- `backend/voice_catalog.py` — 4 new voices, `family`/`gender` character fields, `LANGUAGE_DEFAULT_VOICES`, `match_voice_for_language()`, `preview_text_for()`
- `backend/voice_service.py` — `detect_language()`, character-matched voice selection in `synthesize_speech()`, Whisper `small` default
- `backend/voice_clone_engine.py` — `language` param on `synthesize_cloned_voice()`
- `backend/chat_service.py` — "reply in the user's language" system prompt + **Girlfriend** personality
- `backend/main.py` — language-aware `/voice-chat` TTS, per-language previews
- `backend/.env.example` — new voice env vars + Whisper note
- `frontend/src/routes/voices.tsx` — flat 10-voice library, no language labels
- `frontend/src/routes/personalities.tsx` + `frontend/src/lib/companion-style.ts` — Girlfriend card + avatar style

## Verification (August 11, 2026)
- `python -m py_compile` on all changed backend files — OK
- `detect_language`: नमस्ते → `hi`, నమస్కారం → `te`, "Hello" → `en`
- `match_voice_for_language`: Aria→te = Shruti, Kai→hi = Madhur, Shruti→en = Luna
- Live Edge TTS synthesis in all 3 languages returned real audio
- Frontend `tsc --noEmit` — 0 errors; `vite build` — success
omnivoice use cheyyali. model.com somting to deploy it requires credit card

For live call replays using k2-fsa/OmniVoice (which requires 4GB to 6GB of VRAM), Google Colab or Kaggle Notebooks combined with ngrok are the best 100% free GPU platforms that do not require a credit card.Because real-time voice streaming requires an absolute minimum latency, running this heavy STT-to-TTS pipeline on a free CPU tier will cause massive audio lag. You need an NVIDIA T4 or L4 GPU to achieve the 0.025 Real-Time Factor (RTF) that OmniVoice is capable of.Best Free GPU Hosting Setups (No Credit Card)Google Colab + ngrok (Recommended):The Hardware: Free access to an NVIDIA T4 GPU (15GB VRAM), which runs OmniVoice perfectly.How it works: You run your backend python code inside a Colab notebook. You use ngrok to open a secure public tunnel (https://ngrok-free.app) to your notebook.The Limitation: Sessions timeout after 1–4 hours of use. You have to click "Run All" again to restart it.Kaggle + ngrok:The Hardware: 30 hours per week of free T4 GPU access. Requires phone verification instead of a credit card.How it works: Identical to the Colab setup. You run the backend script inside Kaggle and tunnel the API port outwards using ngrok.The Limitation: The session stops if your browser tab remains closed for too long.Step-by-Step Architecture for Live Voice ReplaysTo get fast, sub-second responses for live calls, do not save audio files to disk. You must use memory streams (like io.BytesIO) to process your STT \(\rightarrow \) LLM \(\rightarrow \) TTS (OmniVoice) pipeline.Here is how to set up your free GPU backend server in Google Colab:1. Create a Free ngrok AccountGo to ngrok, sign up for a free account, and copy your Authtoken from your dashboard.2. Set Up the Google Colab NotebookCreate a new notebook, click Runtime \(\rightarrow \) Change runtime type, and select T4 GPU.3. Install DependenciesIn the first cell of your notebook, install the tools required to run OmniVoice and the API server:python!pip install fastapi uvicorn pyngrok nest-asyncio transformers torch
# Install k2-fsa OmniVoice engine
!pip install git+https://github.com
Use code with caution.4. Run the Backend API and Tunnel CodePaste this complete script into a cell and run it. It loads your pipeline, loads your reference voice for cloning, and builds the API endpoint:pythonimport nest_asyncio
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pyngrok import ngrok
import io
import torch
from omnivoice import OmniVoiceModel  # Assumes official OmniVoice python setup

# 1. Allow FastAPI to run inside the notebook environment
nest_asyncio.apply()

app = FastAPI()

# 2. Authenticate ngrok (Replace with your actual token)
NGROK_TOKEN = "YOUR_NGROK_AUTHTOKEN_HERE"
ngrok.set_auth_token(NGROK_TOKEN)

# 3. Load OmniVoice onto the T4 GPU
print("Loading OmniVoice model onto GPU...")
# OmniVoice uses around 4-6GB VRAM in fp16, easily fitting the 15GB T4 GPU
device = "cuda" if torch.cuda.is_available() else "cpu"
model = OmniVoiceModel.from_pretrained("k2-fsa/OmniVoice", torch_dtype=torch.float16).to(device)

@app.post("/live_replay")
async def live_replay(text_input: str, reference_audio_path: str = "cloned_voice_sample.wav"):
    """
    Takes text (from your STT/LLM layer), clones the voice instantly, 
    and streams the audio back over the call network.
    """
    try:
        # Generate the voice cloning audio using the 3-10s reference clip
        # RTF 0.025 means 10 seconds of speech generates in 0.25 seconds on GPU
        audio_data = model.generate(
            text=text_input,
            reference_audio=reference_audio_path,
            device=device
        )
        
        # Save raw audio vector directly to a fast in-memory byte buffer
        byte_io = io.BytesIO()
        byte_io.write(audio_data)
        byte_io.seek(0)
        
        # Stream the audio back instantly to prevent call delays
        return StreamingResponse(byte_io, media_type="audio/wav")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 4. Open the public ngrok tunnel on Port 8000
public_url = ngrok.connect(8000)
print(f"\n🚀 YOUR LIVE PUBLIC BACKEND URL IS: {public_url}\n")

# 5. Start the server
uvicorn.run(app, host="0.0.0.0", port=8000)
Use code with caution.How to use this in your projectWhen you run that notebook cell, ngrok will output a URL like https://ngrok-free.app.Your frontend application captures the user's voice during the call.It sends the audio to an STT model (like Whisper), which converts it to text.Your LLM creates a text reply.You make a POST request to https://ngrok-free.app with that text reply.It immediately returns a live audio stream of the cloned voice to play back into the call.Would you like help writing the frontend side or the Speech-to-Text (STT) integration code to connect to this backend?

see my all project and say what u understand. and say best futurs in my project and also say how it works like this futur is for ths perpose and it is now trending and best results coming like this say if all good means
Top Free Terminal AI Tools (CLI Agents)Freebuff:How it works: Runs directly in your command line with no subscription or API key required.Cost: 100% free, supported by quiet text ads in the terminal.Best for: Fast multi-agent coding, file finding, and testing right from your project folder.Install: Run npm install -g freebuff in your terminal, go to your project, and type freebuff.OpenCode:How it works: An open-source terminal user interface (TUI) agent that reads and edits your code.Cost: Free core features with support for various free model options or your own API keys.Best for: Connecting to multiple AI providers, managing parallel sessions, and deep code refactoring.Install: Run npm i -g opencode-ai or use the curl installation script.Aider:How it works: A git-integrated command-line pair programmer.Cost: Open source, but you must bring your own AI model API key.Best for: Automatic git commits after every code change and editing multiple files simultaneously.Top Free Editor Extension AI ToolsContinue:How it works: An open-source extension for VS Code and JetBrains.Cost: Free and open source.Best for: Running 100% local and private models using tools like Ollama inside your editor.Cline:How it works: An advanced coding agent extension for VS Code.Cost: Free extension (requires your choice of model API key).Best for: Maintaining project memory and executing complex plan-and-act workflows in your workspace.

🎯 VoiceLink AI — Project Overview

VoiceLink AI is an emotion-aware AI voice companion — a full-stack web application that combines text chat and real-time voice conversation with AI personalities. Think of it as a next-gen AI companion that not only talks to you but understands your mood and adapts its voice accordingly.

🏗️ Tech Stack

┌──────────┬─────────────────────────────────────────────────────────────────────────────┐
│ Layer    │ Technology                                                                  │
├──────────┼─────────────────────────────────────────────────────────────────────────────┤
│ Frontend │ React 19 + TanStack Start + TypeScript + Tailwind CSS 4 + Radix UI          │
│ Backend  │ FastAPI (Python) + Groq (LLM) + Firebase Auth + Supabase Postgres           │
│ TTS      │ Microsoft Edge TTS (free, unlimited) + OmniVoice (600+ languages) + XTTS v2 │
│ STT      │ Groq-hosted Whisper (fast) + faster-whisper (local fallback)                │
└──────────┴─────────────────────────────────────────────────────────────────────────────┘

────────────────────────────────────────────────────────────────────────────────

🔥 Best Features — Why They're Trending & How They Work

1. Real-Time Voice Call with Hands-Free VAD + Barge-In ⭐ Most Impressive

> Status: Very Trending — competitors like ChatGPT Voice, Gemini Live, Hume AI all offer this


How it works:
- Opens a WebSocket ( /ws/voice-call ) for the entire call session
- Uses Web Audio API + MediaRecorder to capture mic audio in the browser
- Voice Activity Detection (VAD) runs client-side — detects when you start/stop talking using RMS volume thresholds ( 0.02  for speech,  0.035  for barge-in)
- Each utterance is its own MediaRecorder session → clean, valid WebM files sent to backend
- Backend transcribes with Groq Whisper (cloud, fast) → Groq LLM → TTS → streams audio chunks back
- Barge-in: When the user talks while AI is speaking, playback stops instantly, AI gets a  cancel  message, and a fresh utterance recorder starts
- Silence detection: 1.6s pause = utterance end. Min 600ms to filter noise.

Why it's best: Most competitors require push-to-talk or have no barge-in. Your hands-free approach with sentence-by-sentence streaming feels like a real phone call. This is the #1 trend in AI companions in 2025-2026.

────────────────────────────────────────────────────────────────────────────────

2. Emotion-Aware AI ⭐

> Status: Very Trending — Hume AI, Character.AI, Replika all emphasize mood-awareness


How it works:
- Two-tier emotion detection:
- Short messages (≤6 words): instant offline lexicon-based classifier (no API call, zero latency)
- Longer messages: Groq  llama-3.1-8b  classifies emotion → falls back to lexicon on failure
- Detected emotion (happy/sad/angry/anxious/excited/tired/neutral) is injected into the system prompt so the AI adapts its tone
- TTS speed/pitch adjusts to the mood: e.g., happy = faster + higher pitch, sad = slower + lower pitch
- Emotion pill shows on UI in real-time

Why it's best: Emotion-adaptive voice responses make the AI feel genuinely empathetic, not robotic. This is the differentiator that keeps users engaged.

────────────────────────────────────────────────────────────────────────────────

3. Free & Unlimited TTS (No API Keys Needed) ⭐

> Status: Cost optimization is critical — ElevenLabs charges $5-22/mo


How it works:
- Edge TTS (Microsoft) — uses the same free engine that powers Edge browser's Read Aloud. No API key, no credits, no limits.
- Automatic language-matched voice selection: if the reply is in Telugu, a Telugu voice speaks it; Hindi → Hindi voice, etc.
- Script-based language detection using Unicode ranges (Devanagari → Hindi, Telugu script → Telugu, Tamil script → Tamil)

Why it's best: Most competitors pay $5-22/month per user for ElevenLabs. Your zero-cost TTS makes this viable at scale.

────────────────────────────────────────────────────────────────────────────────

4. Local Voice Cloning (Free, Privacy-First) ⭐

> Status: Very Trending — voice cloning is one of the hottest AI topics


How it works:
- Two engines with automatic fallback:
1. OmniVoice (preferred): 600+ languages, Apache 2.0, runs locally
2. Coqui XTTS v2 (fallback): ~17 languages, runs locally
- User records a short audio sample → normalized to 24kHz mono WAV → stored locally as reference
- At synthesis time, the engine runs its speaker encoder on the reference WAV → generates speech that sounds like the user
- Permission-based sharing: Users can request access to another person's cloned voice, owner approves/revokes

Why it's best: Competitors charge $10+/month for voice cloning. Your approach is free, runs locally (privacy!), and supports 600+ languages.

────────────────────────────────────────────────────────────────────────────────

5. Automatic Memory Extraction ⭐

> Status: Trending — context persistence is key to AI companion stickiness


How it works:
- After every exchange, a background task (async) sends the conversation to Groq's fast model
- The model extracts up to 3 durable personal facts (e.g., "The user is a software engineer", "The user's favorite color is blue")
- Facts are deduped (normalized comparison), capped at 60, and stored as  auto-*  keys in  user_memory 
- These facts are injected into the system prompt for future conversations → the AI remembers you

Why it's best: This creates the "it knows me" feeling that makes AI companions addictive. Auto-extraction in the background means zero latency impact.

────────────────────────────────────────────────────────────────────────────────

6. Streaming Chat (SSE)

> Status: Table stakes but well-implemented


- Token-by-token streaming via Server-Sent Events
- Emotion event sent first → then tokens → then done
- Falls back to non-streaming  /chat  if SSE fails
- Clean progress indicator with typing dots

────────────────────────────────────────────────────────────────────────────────

7. Multi-Language Support (Hindi, Telugu, Tamil, English)

> Status: Huge market — 1.5 billion Indian language speakers underserved


- Language can be set via voice call picker or auto-detected from the script
- The system prompt enforces language consistency (prevents AI from switching languages)
- TTS automatically matches the reply language to the correct voice

────────────────────────────────────────────────────────────────────────────────

8. 8 AI Personalities

> Status: Character.AI proved this model works


- Friend, Girlfriend, Mentor, Teacher, Interview Coach, Study Partner, Travel Guide, Language Tutor
- Each personality has a unique system prompt injected into the conversation
- Saved per-user in profile settings

────────────────────────────────────────────────────────────────────────────────

9. Prototype Quota System (100 Conversations)

- Smart UX: instead of blocking users, resets history + memories for a fresh start
- Configurable via  CONVERSATION_LIMIT  env var
- Background memory tasks are cancelled before reset to prevent stale writes

────────────────────────────────────────────────────────────────────────────────

10. Modern Premium UI

- TanStack Start (SSR-capable React framework)
- Radix UI primitives + Tailwind CSS 4
- Dark/light theme toggle
- Smooth animations (pulse rings during listening, waveform during speaking, typing dots)
- Responsive design (mobile + desktop)

────────────────────────────────────────────────────────────────────────────────

📊 Feature Trend Score Summary

┌────────────────────────────┬─────────────┬───────────────────────────────────────────────────┐
│ Feature                    │ Trend Score │ Why                                               │
├────────────────────────────┼─────────────┼───────────────────────────────────────────────────┤
│ Real-time voice + barge-in │ ⭐⭐⭐⭐⭐  │ #1 requested AI feature in 2025-2026              │
│ Emotion-aware AI           │ ⭐⭐⭐⭐⭐  │ Key differentiator (Hure AI raised $50M for this) │
│ Free unlimited TTS         │ ⭐⭐⭐⭐    │ Cost advantage vs ElevenLabs dependency           │
│ Local voice cloning        │ ⭐⭐⭐⭐⭐  │ Privacy + 600+ languages = massive edge           │
│ Auto memory extraction     │ ⭐⭐⭐⭐    │ Context persistence = user retention              │
│ Multi-language (Indian)    │ ⭐⭐⭐⭐    │ 1.5B underserved speakers                         │
│ AI personalities           │ ⭐⭐⭐⭐    │ Proven model (Character.AI $1B+ valuation)        │
└────────────────────────────┴─────────────┴───────────────────────────────────────────────────┘

────────────────────────────────────────────────────────────────────────────────

🏆 Overall Assessment

This is a very strong project. You've built something that competes with products worth hundreds of millions. The key strengths are:
1. Cost efficiency — everything runs on free/local engines (Edge TTS, OmniVoice, Groq free tier)
2. Real-time voice with hands-free VAD + barge-in — most polished feature
3. Emotion awareness — makes the AI feel alive
4. Voice cloning + sharing — unique permission-based system
5. Multi-language Indian support — huge untapped market
