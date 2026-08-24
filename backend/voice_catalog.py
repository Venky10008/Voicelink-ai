"""Built-in voice catalog for the Voice Library screen.

Each entry maps a friendly app-level `id` to a real Microsoft Edge TTS voice.
edge-tts is free and unlimited — no API key, no credit limits — so every
voice in the library genuinely sounds different.

Multi-language: every voice carries a `lang` code ("en", "hi", "te"...).
The backend uses `detect_language()` on the AI reply so calls without an
explicit voice automatically speak in the right language, and the library
groups voices by language.
"""

from __future__ import annotations

import os

# Default voice used when none is selected (or an unknown/cloned voice id is
# requested). Override with DEFAULT_EDGE_TTS_VOICE in the .env file.
DEFAULT_EDGE_TTS_VOICE = os.getenv(
    "DEFAULT_EDGE_TTS_VOICE", "en-US-AriaNeural"
).strip()

# Language display metadata (used by the Voice Library to group voices).
LANGUAGE_META: dict[str, dict[str, str]] = {
    "en": {"name": "English", "native": "English", "flag": "🌐"},
    "hi": {"name": "Hindi", "native": "हिन्दी", "flag": "🇮🇳"},
    "te": {"name": "Telugu", "native": "తెలుగు", "flag": "🇮🇳"},
    "ta": {"name": "Tamil", "native": "தமிழ்", "flag": "🇮🇳"},
}

# Default Edge TTS voice per language — used when no explicit voice is chosen
# and the AI reply's language was detected (see voice_service.detect_language).
LANGUAGE_DEFAULT_VOICES: dict[str, str] = {
    "en": DEFAULT_EDGE_TTS_VOICE,
    "hi": os.getenv("HINDI_EDGE_TTS_VOICE", "hi-IN-MadhurNeural").strip(),
    "te": os.getenv("TELUGU_EDGE_TTS_VOICE", "te-IN-ShrutiNeural").strip(),
    "ta": os.getenv("TAMIL_EDGE_TTS_VOICE", "ta-IN-PallaviNeural").strip(),
}

BUILT_IN_VOICES: list[dict] = [
    # Every voice has a `lang` (its native Edge TTS language) plus a character
    # `family` (gender + vibe). When a call's reply is in another language, the
    # selected voice's character is matched to a voice of that language — so
    # "Aria" speaking Telugu becomes the warm female Telugu voice, keeping the
    # same feel while pronouncing the language perfectly.
    # ── English ────────────────────────────────────────────────────────────
    {
        "id": "aria",
        "name": "Aria",
        "tags": ["Female", "Warm", "Calm"],
        "edge_tts_voice": "en-US-AriaNeural",
        "lang": "en",
        "family": "female-warm",
        "gender": "female",
    },
    {
        "id": "kai",
        "name": "Kai",
        "tags": ["Male", "Deep", "Calm"],
        "edge_tts_voice": "en-US-GuyNeural",
        "lang": "en",
        "family": "male-deep",
        "gender": "male",
    },
    {
        "id": "luna",
        "name": "Luna",
        "tags": ["Female", "Soft", "Warm"],
        "edge_tts_voice": "en-US-JennyNeural",
        "lang": "en",
        "family": "female-soft",
        "gender": "female",
    },
    {
        "id": "rex",
        "name": "Rex",
        "tags": ["Male", "Energetic"],
        "edge_tts_voice": "en-US-ChristopherNeural",
        "lang": "en",
        "family": "male-energetic",
        "gender": "male",
    },
    {
        "id": "nova",
        "name": "Nova",
        "tags": ["Female", "Energetic"],
        "edge_tts_voice": "en-US-MichelleNeural",
        "lang": "en",
        "family": "female-energetic",
        "gender": "female",
    },
    {
        "id": "orin",
        "name": "Orin",
        "tags": ["Male", "Warm"],
        "edge_tts_voice": "en-US-EricNeural",
        "lang": "en",
        "family": "male-warm",
        "gender": "male",
    },
    # ── Hindi (हिन्दी) ────────────────────────────────────────────────────
    {
        "id": "swara",
        "name": "Swara",
        "tags": ["Female", "Warm"],
        "edge_tts_voice": "hi-IN-SwaraNeural",
        "lang": "hi",
        "family": "female-warm",
        "gender": "female",
    },
    {
        "id": "madhur",
        "name": "Madhur",
        "tags": ["Male", "Deep"],
        "edge_tts_voice": "hi-IN-MadhurNeural",
        "lang": "hi",
        "family": "male-deep",
        "gender": "male",
    },
    # ── Telugu (తెలుగు) ───────────────────────────────────────────────────
    {
        "id": "shruti",
        "name": "Shruti",
        "tags": ["Female", "Soft"],
        "edge_tts_voice": "te-IN-ShrutiNeural",
        "lang": "te",
        "family": "female-soft",
        "gender": "female",
    },
    {
        "id": "mohan",
        "name": "Mohan",
        "tags": ["Male", "Warm"],
        "edge_tts_voice": "te-IN-MohanNeural",
        "lang": "te",
        "family": "male-warm",
        "gender": "male",
    },
    # ── Tamil (தமிழ்) ─────────────────────────────────────────────────────
    {
        "id": "pallavi",
        "name": "Pallavi",
        "tags": ["Female", "Soft"],
        "edge_tts_voice": "ta-IN-PallaviNeural",
        "lang": "ta",
        "family": "female-soft",
        "gender": "female",
    },
    {
        "id": "valluvar",
        "name": "Valluvar",
        "tags": ["Male", "Deep"],
        "edge_tts_voice": "ta-IN-ValluvarNeural",
        "lang": "ta",
        "family": "male-deep",
        "gender": "male",
    },
]


def get_builtin_voice(voice_id: str) -> dict | None:
    """Return the catalog entry for an app-level voice id or a raw edge-tts
    voice name (e.g. "aria" or "en-US-AriaNeural"), or None."""
    for voice in BUILT_IN_VOICES:
        if voice["id"] == voice_id or voice["edge_tts_voice"] == voice_id:
            return voice
    return None


def get_edge_voice_name(voice_id: str | None) -> str:
    """
    Resolve a voice id to an edge-tts voice name.

    Accepts either an app-level id ("aria") or a direct edge-tts voice name
    ("en-US-AriaNeural"). Unknown ids (e.g. cloned-voice keys handled by the
    separate XTTS engine) fall back to the default voice instead of failing.
    """
    if voice_id:
        for voice in BUILT_IN_VOICES:
            if voice["id"] == voice_id or voice["edge_tts_voice"] == voice_id:
                return voice["edge_tts_voice"]
    return DEFAULT_EDGE_TTS_VOICE


def get_language_default_voice(language: str) -> str:
    """Default Edge TTS voice name for a language code ("en", "hi", "te"...)."""
    return LANGUAGE_DEFAULT_VOICES.get(language, DEFAULT_EDGE_TTS_VOICE)


def match_voice_for_language(voice: dict, target_lang: str) -> dict:
    """
    Keep a voice's character when the reply is in another language.

    Edge TTS voices are language-native, so a voice can only pronounce its own
    language perfectly. When the user picks a voice and the reply is written in
    a different language, pick the closest voice in that language: same
    character family (gender + vibe) first, then same gender, then the
    language's default voice. Falls back to the original voice if the target
    language has no voices.
    """
    if voice.get("lang") == target_lang:
        return voice

    candidates = [v for v in BUILT_IN_VOICES if v.get("lang") == target_lang]
    if not candidates:
        return voice

    family = voice.get("family")
    if family:
        for v in candidates:
            if v.get("family") == family:
                return v

    gender = voice.get("gender")
    if gender:
        for v in candidates:
            if v.get("gender") == gender:
                return v

    default_edge = get_language_default_voice(target_lang)
    for v in candidates:
        if v.get("edge_tts_voice") == default_edge:
            return v
    return candidates[0]


def preview_text_for(voice: dict) -> str:
    """A short self-introduction sample in the voice's own language."""
    name = voice.get("name", "Voice")
    lang = voice.get("lang", "en")
    if lang == "hi":
        return f"नमस्ते! मैं {name} हूँ। चलिए बात करते हैं।"
    if lang == "te":
        return f"నమస్కారం! నేను {name}. మాట్లాడదాం."
    if lang == "ta":
        return f"வணக்கம்! நான் {name}. பேசலாம்."
    return f"Hi, I'm {name}. Let's talk!"
