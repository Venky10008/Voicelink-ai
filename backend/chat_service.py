"""Shared Groq chat logic used by /chat, /chat/stream and /voice-chat.

Includes emotion awareness (the AI adapts its tone to how the user feels) and
automatic memory extraction (durable facts are saved to user_memory in the
background so the companion remembers across sessions).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crud import (
    count_user_messages,
    get_or_create_user,
    get_recent_messages,
    get_user_memories,
    reset_user_conversation_data,
    save_message,
    upsert_memory,
)
from models import UserMemory

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
GROQ_FAST_MODEL = os.getenv("GROQ_FAST_MODEL", "openai/gpt-oss-20b").strip()

# Each account gets this many conversations before its history + memories are
# wiped for a fresh start (prototype quota). Configurable via env. Guarded so
# a bad env value (0/negative) can never wipe on every message.
CONVERSATION_LIMIT = max(1, int(os.getenv("CONVERSATION_LIMIT", "100").strip() or "100"))
CONVERSATION_LIMIT_NOTICE = (
    "Prototype limit: this account gets "
    f"{CONVERSATION_LIMIT} conversations. You've reached the limit, so your "
    "chat history and memories were reset for a fresh start. Thanks for trying "
    "VoiceLink!"
)

# Language code → display name used in the system prompt and for TTS.
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "te": "Telugu",
    "ta": "Tamil",
}

# App-level personality id → persona instruction injected into the system prompt.
PERSONALITIES: dict[str, str] = {
    "friend": "You are a warm, supportive friend. Keep it casual, caring, and encouraging.",
    "girlfriend": "You are a warm, caring, loving girlfriend. Be affectionate, playful, and supportive — speak to your partner with love and tenderness, keep it natural and personal.",
    "mentor": "You are a wise mentor. Offer thoughtful, guiding advice for life and career.",
    "teacher": "You are a patient teacher. Explain concepts clearly, one step at a time.",
    "coach": "You are an interview coach. Practice interview questions and give constructive, honest feedback.",
    "study": "You are a study partner. Run focus sessions, quick quizzes, and reinforce learning.",
    "travel": "You are a travel guide. Share places, tips, and local secrets.",
    "language": "You are a language tutor. Help the user speak and learn a language, correcting mistakes gently.",
}

# Emotion id → tone guidance injected into the system prompt so the AI matches the mood.
EMOTION_TONES: dict[str, str] = {
    "happy": "The user is feeling happy right now. Match their bright, upbeat energy and share in their joy.",
    "sad": "The user is feeling down. Be warm, gentle, and supportive. Offer quiet comfort and let them know you're here — don't try to fix it.",
    "angry": "The user is frustrated or angry. Stay calm and patient. Acknowledge their feeling instead of dismissing it.",
    "anxious": "The user seems anxious or worried. Be reassuring, calm, and grounding. Keep your reply simple and steady.",
    "excited": "The user is excited. Match their enthusiasm — be energetic and celebratory.",
    "tired": "The user sounds tired. Be gentle, low-key, and caring. Keep it short and don't pile on questions.",
    "neutral": "Match the user's natural tone — friendly, warm, and concise.",
}

# Fast, offline emotion guess used for short messages and as a fallback.
EMOTION_LEXICON: dict[str, tuple[str, ...]] = {
    "happy": ("happy", "great", "awesome", "amazing", "wonderful", "fantastic", "love", "joy", "glad", "yay", "woohoo", "best day", "good news", "😊", "😄", "🎉", "✨"),
    "sad": ("sad", "down", "depressed", "cry", "crying", "lonely", "miss", "missing", "heartbroken", "unhappy", "grief", "miserable", "😢", "😭", "💔", "☹"),
    "angry": ("angry", "mad", "furious", "annoyed", "hate", "hated", "frustrated", "irritated", "pissed", "fuming", "😠", "😡", "🤬"),
    "anxious": ("anxious", "nervous", "worried", "scared", "afraid", "stress", "stressed", "panic", "overwhelmed", "dread", "😰", "😨", "😟"),
    "excited": ("excited", "thrilled", "pumped", "can't wait", "cant wait", "so happy", "hyped", "🤩", "🥳", "😆", "🎊"),
    "tired": ("tired", "exhausted", "sleepy", "drained", "burned out", "worn out", "no energy", "wiped", "😴", "🥱"),
}

MAX_AUTO_MEMORIES = 60
MIN_MEMORY_EXTRACT_LENGTH = 12


def _groq_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }


def _groq_error_detail(response) -> str:
    detail = "Groq API request failed."
    try:
        err = response.json()
        if isinstance(err, dict):
            detail = err.get("error", {}).get("message") or err.get("message") or detail
    except Exception:
        detail = response.text or detail
    return detail


async def _groq_json(
    messages: list[dict[str, str]],
    *,
    model: str = GROQ_MODEL,
    max_tokens: int | None = None,
    temperature: float = 0.7,
    response_format: dict | None = None,
) -> str:
    """POST messages to Groq and return the assistant's text content."""
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if response_format is not None:
        payload["response_format"] = response_format

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(GROQ_URL, json=payload, headers=_groq_headers())
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Groq API request timed out. Please try again.",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach Groq API: {exc}",
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_groq_error_detail(response),
        )

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("non-string content")
        return content.strip()
    except (KeyError, IndexError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected response format from Groq API.",
        )


# ---------------------------------------------------------------------------
# Emotion awareness
# ---------------------------------------------------------------------------


def _classify_lexicon(message: str) -> str:
    """Cheap keyword-based emotion guess (always returns a valid emotion id)."""
    lowered = message.lower()
    scores: dict[str, int] = {}
    for emotion, words in EMOTION_LEXICON.items():
        scores[emotion] = sum(lowered.count(word) for word in words)
    best, best_score = "neutral", 0
    for emotion, score in scores.items():
        if score > best_score:
            best, best_score = emotion, score
    return best


async def _classify_with_groq(message: str) -> str | None:
    """Best-effort Groq classification; returns None on any failure."""
    if not GROQ_API_KEY:
        return None
    system = (
        "You are an emotion classifier for a voice companion. "
        "Classify the emotion of the user's message. Reply with EXACTLY ONE word "
        "from this list: happy, sad, angry, anxious, excited, tired, neutral. "
        "Nothing else — no punctuation, no explanation."
    )
    try:
        content = await _groq_json(
            [{"role": "system", "content": system}, {"role": "user", "content": message}],
            model=GROQ_FAST_MODEL,
            max_tokens=8,
            temperature=0.0,
        )
        emotion = content.strip().lower().rstrip(".")
        return emotion if emotion in EMOTION_TONES else None
    except Exception as exc:
        print(f"[groq] emotion classification failed, falling back to lexicon: {exc}", flush=True)
        return None


async def classify_emotion(message: str) -> str:
    """Detect the user's emotion. Short messages use the free lexicon; longer
    ones ask Groq (fast model) and fall back to the lexicon on failure."""
    text = message.strip()
    if not text:
        return "neutral"
    if len(text.split()) <= 6 or len(text) <= 24:
        return _classify_lexicon(text)
    return (await _classify_with_groq(text)) or _classify_lexicon(text)


def emotion_voice_params(emotion: str, speed: float = 1.0, pitch: float = 1.0) -> tuple[float, float]:
    """Subtle speed/pitch adjustments so the spoken voice matches the mood."""
    factors = {
        "happy": (1.06, 1.04),
        "excited": (1.08, 1.05),
        "sad": (0.92, 0.94),
        "tired": (0.94, 0.96),
        "anxious": (1.02, 1.02),
        "angry": (1.04, 1.02),
    }
    factor_speed, factor_pitch = factors.get(emotion, (1.0, 1.0))
    return round(speed * factor_speed, 2), round(pitch * factor_pitch, 2)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


def build_system_prompt(
    memories: list,
    personality: str | None = None,
    emotion: str | None = None,
    language: str | None = None,
) -> str:
    base = (
        "You are VoiceLink AI, a friendly, concise voice companion. "
        "Reply in clear, natural language. "
        "Always reply in the SAME LANGUAGE the user writes in — if they write "
        "in Hindi, reply in Hindi; if Telugu, reply in Telugu; if English, "
        "reply in English. Never switch languages mid-conversation."
    )
    # An explicit user preference (voice-call language picker) overrides the
    # "same language as the message" rule — voice transcription can garble the
    # script (e.g. Telugu audio detected as Tamil), so once the user says they
    # speak Telugu, the AI must never drift to another language.
    if language and language in LANGUAGE_NAMES:
        name = LANGUAGE_NAMES[language]
        base = (
            f"{base}\n\n"
            f"The user's preferred language is {name}. ALWAYS reply in {name}, "
            f"no matter what language their latest message appears to be written "
            f"in — voice transcription can garble the script. Never switch away "
            f"from {name}. If a message looks garbled or is in the wrong script, "
            f"NEVER point that out or correct the user's language/spelling — "
            f"just understand what you can and answer helpfully in {name}."
        )
    if personality:
        persona = PERSONALITIES.get(personality)
        if persona:
            base = f"{base}\n\n{persona}"

    if emotion and emotion in EMOTION_TONES:
        base = f"{base}\n\nMood awareness: {EMOTION_TONES[emotion]}"

    if not memories:
        return base

    lines = [f"- {mem.value}" for mem in memories]
    facts = "\n".join(lines)
    return (
        f"{base}\n\n"
        "Known facts about this user (use them naturally when relevant):\n"
        f"{facts}"
    )


def display_name(firebase_user: dict) -> str | None:
    name = firebase_user.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    email = firebase_user.get("email")
    if isinstance(email, str) and email.strip():
        return email.strip()
    return None


# ---------------------------------------------------------------------------
# Chat context + Groq call helpers
# ---------------------------------------------------------------------------


async def _load_chat_context(
    db: AsyncSession, firebase_user: dict
) -> tuple[object, list, list]:
    """Return (user, history, memories). Creates the user row if needed."""
    firebase_uid = firebase_user.get("uid")
    if not firebase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase token is missing a user id (uid).",
        )
    try:
        user = await get_or_create_user(
            db, firebase_uid=firebase_uid, name=display_name(firebase_user)
        )
        history = await get_recent_messages(db, user_id=user.id, limit=10)
        memories = await get_user_memories(db, user_id=user.id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while loading chat context: {exc}",
        ) from exc
    return user, history, memories


def _groq_messages(
    history,
    message,
    memories,
    personality,
    emotion,
    language: str | None = None,
) -> list[dict[str, str]]:
    groq_messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": build_system_prompt(
                memories,
                personality=personality,
                emotion=emotion,
                language=language,
            ),
        }
    ]
    for row in history:
        role = row.role if row.role in ("user", "assistant") else "user"
        groq_messages.append({"role": role, "content": row.content})
    groq_messages.append({"role": "user", "content": message})
    return groq_messages


async def _maybe_reset_for_limit(db: AsyncSession, user_id: int) -> bool:
    """If the user has hit the conversation quota, wipe their chat history +
    memories so they get a fresh start. Returns True when a wipe happened."""
    try:
        count = await count_user_messages(db, user_id=user_id, role="user")
    except Exception as exc:
        print(f"[quota] count failed for user {user_id}: {exc}", flush=True)
        return False
    if count < CONVERSATION_LIMIT:
        return False
    try:
        # Stop any in-flight background memory-extraction tasks for this user so
        # they can't re-insert memories AFTER the wipe below.
        cancel_pending_memory_tasks(user_id)
        await reset_user_conversation_data(db, user_id=user_id)
    except Exception as exc:
        print(f"[quota] reset failed for user {user_id}: {exc}", flush=True)
        return False
    return True


async def _save_exchange(
    db: AsyncSession,
    *,
    user_id: int,
    user_message: str,
    reply: str,
    source: str,
) -> bool:
    """Save the exchange. Returns True when the conversation quota was hit and
    the user's history + memories were wiped for a fresh start."""
    try:
        await save_message(db, user_id=user_id, role="user", content=user_message, source=source)
        await save_message(db, user_id=user_id, role="assistant", content=reply, source=source)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Chat succeeded but failed to save messages: {exc}",
        ) from exc

    fresh_start = await _maybe_reset_for_limit(db, user_id)
    if not fresh_start:
        schedule_memory_extraction(user_id, user_message, reply)
    return fresh_start


async def generate_chat_reply(
    db: AsyncSession,
    *,
    firebase_user: dict,
    message: str,
    save_to_db: bool = True,
    personality: str | None = None,
    source: str = "chat",
    language: str | None = None,
) -> tuple[str, str, str, bool]:
    """Returns (transcript/message, reply, emotion, fresh_start).

    `fresh_start` is True when the 100-conversation prototype quota was hit and
    the user's history + memories were wiped for a fresh start.
    """
    message = message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message must not be empty.",
        )

    if not GROQ_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROQ_API_KEY is not set on the server.",
        )

    user, history, memories = await _load_chat_context(db, firebase_user)
    emotion = await classify_emotion(message)
    reply = await _groq_json(
        _groq_messages(history, message, memories, personality, emotion, language=language)
    )
    if not reply:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Groq returned an empty reply.",
        )

    fresh_start = False
    if save_to_db:
        fresh_start = await _save_exchange(
            db,
            user_id=user.id,
            user_message=message,
            reply=reply,
            source=source,
        )

    return message, reply, emotion, fresh_start


async def stream_chat_reply(
    db: AsyncSession,
    *,
    firebase_user: dict,
    message: str,
    personality: str | None = None,
    source: str = "chat",
    fast_emotion: bool = False,
    language: str | None = None,
):
    """Yield ("emotion", emotion) first, then ("token", chunk) for each token.

    Saves the exchange to the database after the stream completes.

    `fast_emotion=True` skips the extra Groq emotion-classification round-trip
    and uses the instant offline keyword check — used by voice calls, where
    every second of latency is felt.
    """
    message = message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message must not be empty.",
        )

    if not GROQ_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROQ_API_KEY is not set on the server.",
        )

    user, history, memories = await _load_chat_context(db, firebase_user)
    emotion = _classify_lexicon(message) if fast_emotion else await classify_emotion(message)
    yield ("emotion", emotion)

    groq_messages = _groq_messages(
        history, message, memories, personality, emotion, language=language
    )
    payload = {
        "model": GROQ_MODEL,
        "messages": groq_messages,
        "temperature": 0.7,
        "stream": True,
    }

    chunks: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", GROQ_URL, json=payload, headers=_groq_headers()
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    detail = "Groq API request failed."
                    try:
                        err = json.loads(body)
                        if isinstance(err, dict):
                            detail = err.get("error", {}).get("message") or err.get("message") or detail
                    except Exception:
                        if body:
                            detail = body.decode("utf-8", "replace")[:300] or detail
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=detail,
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        delta = data["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError, TypeError, ValueError):
                        continue
                    if delta:
                        chunks.append(delta)
                        yield ("token", delta)
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Groq API request timed out. Please try again.",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach Groq API: {exc}",
        )

    reply = "".join(chunks).strip()
    if not reply:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Groq returned an empty reply.",
        )

    fresh_start = await _save_exchange(
        db,
        user_id=user.id,
        user_message=message,
        reply=reply,
        source=source,
    )
    if fresh_start:
        yield ("fresh_start", True)


# ---------------------------------------------------------------------------
# Automatic memory extraction
# ---------------------------------------------------------------------------


async def extract_facts(user_message: str, ai_reply: str) -> list[str]:
    """Best-effort Groq extraction of durable user facts. Returns [] on failure."""
    if not GROQ_API_KEY:
        return []
    system = (
        "You extract durable, personal facts about a user from a conversation. "
        'Reply with ONLY valid JSON in this exact shape: {"facts": ["fact", "fact"]}. '
        "Include at most 3 facts. Rules for a good fact: it is about the user, it is durable "
        "(not a one-time event), it would be useful later, and it is concrete and specific "
        "(names, occupations, activities, locations, preferences, relationships, goals, "
        "health, likes and dislikes). Avoid vague or generic statements such as "
        "'The user enjoys celebrating successes'. Keep each fact under 15 words, phrased "
        "as 'The user ...'. Skip greetings, questions, thanks, and small talk."
    )
    user_prompt = f'User: "{user_message}"\n\nAssistant: "{ai_reply}"'
    try:
        content = await _groq_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            model=GROQ_FAST_MODEL,
            max_tokens=240,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        # Defensively strip markdown code fences in case the model wraps the JSON.
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()
        data = json.loads(content)
        facts = data.get("facts")
        if not isinstance(facts, list):
            facts = []
    except Exception as exc:
        print(f"[groq] memory extraction failed: {exc}", flush=True)
        return []

    out: list[str] = []
    for fact in facts:
        cleaned = " ".join(str(fact).split())
        if len(cleaned) >= 6 and len(cleaned) <= 200 and cleaned not in out:
            out.append(cleaned)
    return out[:3]


def _normalize_fact(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


async def _trim_auto_memories(db: AsyncSession, user_id: int) -> None:
    """Keep at most MAX_AUTO_MEMORIES auto- memories (oldest dropped)."""
    result = await db.execute(
        select(UserMemory)
        .where(UserMemory.user_id == user_id, UserMemory.key.like("auto-%"))
        .order_by(UserMemory.updated_at.desc())
    )
    rows = list(result.scalars().all())
    if len(rows) > MAX_AUTO_MEMORIES:
        for row in rows[MAX_AUTO_MEMORIES:]:
            await db.delete(row)
        await db.commit()


async def save_auto_memories(
    db: AsyncSession,
    *,
    user_id: int,
    user_message: str,
    ai_reply: str,
) -> int:
    """Extract durable facts and store them as auto- memories (deduped, capped)."""
    if len(user_message.strip()) < MIN_MEMORY_EXTRACT_LENGTH:
        return 0
    facts = await extract_facts(user_message, ai_reply)
    if not facts:
        return 0

    existing = await get_user_memories(db, user_id=user_id)
    existing_norms = [n for n in (_normalize_fact(m.value) for m in existing) if n]

    added = 0
    for fact in facts:
        norm = _normalize_fact(fact)
        if not norm:
            continue
        duplicate = False
        for existing_norm in existing_norms:
            if norm == existing_norm or (
                len(norm) >= 12 and (norm in existing_norm or existing_norm in norm)
            ):
                duplicate = True
                break
        if duplicate:
            continue
        key = "auto-" + hashlib.md5(norm.encode("utf-8")).hexdigest()[:10]
        await upsert_memory(db, user_id=user_id, key=key, value=fact)
        existing_norms.append(norm)
        added += 1

    if added:
        await _trim_auto_memories(db, user_id)
    return added


_memory_tasks: set[tuple[int, asyncio.Task]] = set()


def cancel_pending_memory_tasks(user_id: int) -> None:
    """Cancel any still-running background memory-extraction tasks for a user.

    Called before a conversation-quota wipe so a late extraction cannot
    re-insert memories after the reset. Safe: the runner wraps everything in
    try/except and closes its own DB session.
    """
    for uid, task in list(_memory_tasks):
        if uid == user_id and not task.done():
            task.cancel()


def schedule_memory_extraction(user_id: int, user_message: str, ai_reply: str) -> None:
    """Run fact extraction in the background so replies aren't slowed down."""
    from database import AsyncSessionLocal

    async def _runner() -> None:
        try:
            async with AsyncSessionLocal() as db:
                await save_auto_memories(
                    db, user_id=user_id, user_message=user_message, ai_reply=ai_reply
                )
        except Exception as exc:
            print(f"[memory] auto-extraction failed: {exc}")

    task = asyncio.create_task(_runner())
    _memory_tasks.add((user_id, task))
    task.add_done_callback(lambda t: _memory_tasks.discard((user_id, t)))
