"""VoiceLink AI — FastAPI backend with Groq chat, Firebase auth, and Postgres."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import firebase_admin
from dotenv import load_dotenv

load_dotenv()
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Security,
    UploadFile,
    WebSocket,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth, credentials
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from chat_service import (
    CONVERSATION_LIMIT_NOTICE,
    GROQ_API_KEY,
    PERSONALITIES,
    display_name,
    emotion_voice_params,
    generate_chat_reply,
    stream_chat_reply,
)
from crud import (
    delete_memory,
    get_all_messages,
    get_or_create_user,
    get_or_create_user_settings,
    get_recent_messages,
    get_user_memories,
    update_user_name,
    update_user_settings,
    upsert_memory,
)
from database import get_db, init_db
from voice_catalog import (
    BUILT_IN_VOICES,
    LANGUAGE_META,
    get_builtin_voice,
    get_language_default_voice,
    preview_text_for,
)
from voice_clone_engine import (
    VoiceCloneUnavailableError,
    engine_available as xtts_engine_available,
    synthesize_cloned_voice as xtts_synthesize_cloned_voice,
)
from chatterbox_engine import (
    VoiceCloneUnavailableError as ChatterboxCloneUnavailableError,
    engine_available as chatterbox_engine_available,
    synthesize_cloned_voice as chatterbox_synthesize_cloned_voice,
)
from voice_service import (
    audio_to_base64,
    detect_language,
    synthesize_speech,
    transcribe_audio,
    transcribe_audio_groq,
)
from voice_call_ws import handle_voice_call, resolve_voice_config
from voice_sharing_router import router as voice_sharing_router

FIREBASE_CREDENTIALS_PATH = os.getenv(
    "FIREBASE_CREDENTIALS_PATH", "./firebase-service-account.json"
).strip()

_db_ready = False


def _init_firebase() -> None:
    if firebase_admin._apps:
        return

    cred_path = Path(FIREBASE_CREDENTIALS_PATH)
    if not cred_path.is_file():
        raise RuntimeError(
            f"Firebase credentials file not found at '{cred_path}'. "
            "Set FIREBASE_CREDENTIALS_PATH in .env to your service account JSON."
        )

    cred = credentials.Certificate(str(cred_path))
    firebase_admin.initialize_app(cred)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _db_ready
    try:
        _init_firebase()
    except Exception as exc:
        print(f"[startup] Firebase init failed: {exc}")

    try:
        await init_db()
        _db_ready = True
        print("[startup] Database tables ready.")
    except Exception as exc:
        _db_ready = False
        print(f"[startup] Database init failed: {exc}")

    yield


app = FastAPI(title="VoiceLink AI", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voice_sharing_router)

security = HTTPBearer(auto_error=False)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request, exc: RequestValidationError):
    errors = exc.errors()
    if errors:
        first = errors[0]
        loc = " → ".join(str(part) for part in first.get("loc", []) if part != "body")
        msg = first.get("msg", "Invalid request")
        detail = f"Invalid request ({loc}): {msg}" if loc else f"Invalid request: {msg}"
    else:
        detail = "Invalid request body."
    return JSONResponse(status_code=400, content={"detail": detail})


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    personality: str | None = None


class ChatResponse(BaseModel):
    reply: str
    emotion: str = "neutral"
    fresh_start: bool = False
    notice: str | None = None


class VoiceChatResponse(BaseModel):
    transcript: str
    reply: str
    emotion: str = "neutral"
    audio_base64: str
    audio_mime_type: str = "audio/mpeg"
    fresh_start: bool = False
    notice: str | None = None


class MemoryRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=128)
    value: str = Field(..., min_length=1)


class MemoryResponse(BaseModel):
    key: str
    value: str
    updated_at: str


class ErrorResponse(BaseModel):
    detail: str


class VoicePreviewRequest(BaseModel):
    voice_id: str = Field(..., min_length=1)
    speed: float | None = Field(None, ge=0.5, le=2.0)
    pitch: float | None = Field(None, ge=0.5, le=2.0)


class VoicePreviewResponse(BaseModel):
    audio_base64: str
    audio_mime_type: str = "audio/mpeg"


class ProfileSettingsRequest(BaseModel):
    voice_id: str | None = Field(None, max_length=64)
    speed: float | None = Field(None, ge=0.5, le=2.0)
    pitch: float | None = Field(None, ge=0.5, le=2.0)
    personality_id: str | None = Field(None, max_length=64)


class ProfileSettingsResponse(BaseModel):
    voice_id: str | None
    speed: float
    pitch: float
    personality_id: str | None
    updated_at: str


class ProfileUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class ProfileResponse(BaseModel):
    name: str | None
    email: str | None
    settings: ProfileSettingsResponse


class HistoryMessageResponse(BaseModel):
    role: str
    content: str
    created_at: str
    source: str = "chat"


class RecentMessagesResponse(BaseModel):
    messages: list[HistoryMessageResponse]


class MemoryListResponse(BaseModel):
    memories: list[MemoryResponse]


class ConversationResponse(BaseModel):
    id: int
    title: str
    preview: str
    type: str
    date: str
    messages: list[HistoryMessageResponse]


class HistoryResponse(BaseModel):
    conversations: list[ConversationResponse]


def verify_firebase_token_str(token: str | None) -> dict:
    """Validate a raw Firebase ID token string (HTTP header or WS query param)."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing auth token. Send: Bearer <Firebase ID token>",
        )

    if not firebase_admin._apps:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase is not configured on the server. Check FIREBASE_CREDENTIALS_PATH.",
        )

    try:
        return auth.verify_id_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Firebase auth token.",
        )


async def verify_firebase_token(
    credentials_header: HTTPAuthorizationCredentials | None = Security(security),
) -> dict:
    if credentials_header is None or not credentials_header.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Send: Bearer <Firebase ID token>",
        )
    return verify_firebase_token_str(credentials_header.credentials)


def _require_db() -> None:
    if not _db_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available. Check DATABASE_URL and restart the backend.",
        )


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    db_ok = False
    if _db_ready:
        try:
            await db.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False

    # Check which voice cloning engine is available
    voice_clone_status = "not installed (falls back to edge-tts)"
    if chatterbox_engine_available():
        voice_clone_status = "chatterbox (local, free, 23+ languages)"
    elif xtts_engine_available():
        voice_clone_status = "xtts-v2 (local, free)"

    return {
        "status": "ok",
        "firebase_ready": bool(firebase_admin._apps),
        "groq_key_set": bool(GROQ_API_KEY),
        "tts_engine": "edge-tts (free, no API key)",
        "voice_clone_engine": voice_clone_status,
        "chatterbox_available": chatterbox_engine_available(),
        "xtts_available": xtts_engine_available(),
        "database_ready": db_ok,
    }


@app.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def chat(
    body: ChatRequest,
    firebase_user: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    _require_db()

    message = body.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'message' must not be empty.",
        )

    _, reply, emotion, fresh_start = await generate_chat_reply(
        db,
        firebase_user=firebase_user,
        message=message,
        personality=body.personality,
        source="chat",
    )
    return ChatResponse(
        reply=reply,
        emotion=emotion,
        fresh_start=fresh_start,
        notice=CONVERSATION_LIMIT_NOTICE if fresh_start else None,
    )


@app.post(
    "/chat/stream",
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Stream a chat reply token-by-token (SSE: emotion event, then token events)",
)
async def chat_stream(
    body: ChatRequest,
    firebase_user: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Server-sent events:

    - `{"type": "emotion", "emotion": "happy"}` — detected mood, sent first
    - `{"type": "token", "content": "..."}` — one per reply chunk
    - `{"type": "fresh_start", "notice": "..."}` — sent when the user hit the
      conversation quota and their history was reset (rare)
    - `{"type": "done"}` — stream finished (messages saved)
    - `{"type": "error", "detail": "..."}` — an error occurred mid-stream
    """
    _require_db()

    message = body.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'message' must not be empty.",
        )

    async def event_stream():
        try:
            async for kind, value in stream_chat_reply(
                db,
                firebase_user=firebase_user,
                message=message,
                personality=body.personality,
                source="chat",
            ):
                if kind == "emotion":
                    yield f"data: {json.dumps({'type': 'emotion', 'emotion': value})}\n\n"
                elif kind == "fresh_start":
                    yield f"data: {json.dumps({'type': 'fresh_start', 'notice': CONVERSATION_LIMIT_NOTICE})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'token', 'content': value})}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
        except HTTPException as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': exc.detail})}\n\n"
        except Exception as exc:
            print(f"[chat/stream] unexpected error: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Something went wrong while streaming the reply.'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post(
    "/voice-chat",
    response_model=VoiceChatResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def voice_chat(
    file: UploadFile = File(...),
    voice_profile_id: int | None = None,
    voice_id: str | None = None,
    personality: str | None = None,
    language: str | None = None,
    firebase_user: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
) -> VoiceChatResponse:
    _require_db()

    if not file.content_type and not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing audio file upload (field name: file).",
        )

    try:
        audio_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read uploaded audio: {exc}",
        ) from exc

    if len(audio_bytes) > 15 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file too large (max 15 MB).",
        )

    # Resolve which voice speaks the reply. Cloned voices verify live
    # permission; built-in voices must exist. Same rules as the WebSocket call.
    tts_voice_id, cloned_voice_key = await resolve_voice_config(
        db,
        firebase_user,
        voice_profile_id=voice_profile_id,
        voice_id=voice_id,
    )

    # Groq cloud Whisper first (fast); local CPU Whisper as a fallback. An
    # explicit `language` hint stops Whisper mis-guessing Indic languages.
    transcript = await transcribe_audio_groq(
        audio_bytes, file.filename or "audio.wav", language=language
    )
    if not transcript:
        transcript = await transcribe_audio(audio_bytes, file.filename or "audio.wav")
    _, reply, emotion, fresh_start = await generate_chat_reply(
        db,
        firebase_user=firebase_user,
        message=transcript,
        personality=personality,
        source="call",
        language=language,
    )
    # Apply the user's saved voice settings (speed/pitch) to the TTS response,
    # then nudge them subtly so the voice matches the detected mood.
    speed: float | None = None
    pitch: float | None = None
    try:
        settings = await get_or_create_user_settings(
            db, user_id=(await get_or_create_user(
                db,
                firebase_uid=firebase_user.get("uid"),
                name=display_name(firebase_user),
            )).id
        )
        speed = settings.speed
        pitch = settings.pitch
    except Exception:
        pass  # Settings are best-effort; fall back to defaults on failure.
    speed, pitch = emotion_voice_params(emotion, speed or 1.0, pitch or 1.0)

    # Detect the reply's language once — it decides which voice speaks.
    reply_lang = detect_language(reply)

    if cloned_voice_key is not None:
        # Always try OmniVoice first for cloned voices (regardless of language).
        # Only fall back to XTTS v2 or Edge TTS if both cloning engines fail.
        audio_data = None
        mime_type = "audio/wav"
        if chatterbox_engine_available():
            try:
                audio_data, mime_type = await chatterbox_synthesize_cloned_voice(
                    reply, cloned_voice_key, language=reply_lang, speed=speed
                )
            except (ChatterboxCloneUnavailableError,) as exc:
                print(f"[voice-chat] Chatterbox failed, trying XTTS: {exc}", flush=True)
        if audio_data is None and xtts_engine_available():
            try:
                audio_data, mime_type = await xtts_synthesize_cloned_voice(
                    reply, cloned_voice_key, language=reply_lang, speed=speed
                )
            except (VoiceCloneUnavailableError,) as exc:
                print(f"[voice-chat] XTTS failed, falling back to Edge TTS: {exc}", flush=True)
        if audio_data is None:
            audio_data, mime_type = await synthesize_speech(
                reply, voice_id=None, speed=speed, pitch=pitch
            )
    else:
        # An explicit built-in voice is respected as-is; with no voice chosen,
        # synthesize_speech picks a voice that matches the reply's language.
        audio_data, mime_type = await synthesize_speech(
            reply,
            voice_id=tts_voice_id,
            speed=speed,
            pitch=pitch,
            language=reply_lang,
        )

    return VoiceChatResponse(
        transcript=transcript,
        reply=reply,
        emotion=emotion,
        audio_base64=audio_to_base64(audio_data),
        audio_mime_type=mime_type,
        fresh_start=fresh_start,
        notice=CONVERSATION_LIMIT_NOTICE if fresh_start else None,
    )


@app.websocket("/ws/voice-call")
async def voice_call_websocket(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Real-time voice call — a single WebSocket for the whole conversation.

    The client streams audio up while the user talks and the server streams
    the reply back sentence-by-sentence so audio starts playing in seconds.
    See voice_call_ws.handle_voice_call for the full message protocol.

    Auth: the Firebase ID token is passed as a query parameter (?token=...)
    because browsers cannot set Authorization headers on WebSocket connections.
    """
    await websocket.accept()
    try:
        _require_db()
        firebase_user = verify_firebase_token_str(websocket.query_params.get("token"))
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "detail": exc.detail})
        await websocket.close(code=1008)
        return
    await handle_voice_call(websocket, db, firebase_user)


@app.post(
    "/memory",
    response_model=MemoryResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def save_user_memory(
    body: MemoryRequest,
    firebase_user: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    _require_db()

    key = body.key.strip()
    value = body.value.strip()
    if not key or not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both 'key' and 'value' must be non-empty.",
        )

    firebase_uid = firebase_user.get("uid")
    if not firebase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase token is missing a user id (uid).",
        )

    try:
        user = await get_or_create_user(
            db,
            firebase_uid=firebase_uid,
            name=display_name(firebase_user),
        )
        memory = await upsert_memory(db, user_id=user.id, key=key, value=value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while saving memory: {exc}",
        ) from exc

    return MemoryResponse(
        key=memory.key,
        value=memory.value,
        updated_at=memory.updated_at.isoformat(),
    )


@app.get(
    "/memory",
    response_model=MemoryListResponse,
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="List everything VoiceLink remembers about the user",
)
async def list_user_memories(
    firebase_user: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
) -> MemoryListResponse:
    _require_db()
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
        memories = await get_user_memories(db, user_id=user.id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while loading memories: {exc}",
        ) from exc

    return MemoryListResponse(
        memories=[
            MemoryResponse(
                key=m.key,
                value=m.value,
                updated_at=m.updated_at.isoformat(),
            )
            for m in memories
        ]
    )


@app.delete(
    "/memory",
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Delete a fact VoiceLink remembers about the user",
)
async def delete_user_memory(
    key: str = Query(..., min_length=1, max_length=128),
    firebase_user: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_db()
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
        deleted = await delete_memory(db, user_id=user.id, key=key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while deleting memory: {exc}",
        ) from exc

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No memory found with key '{key}'.",
        )
    return {"detail": "Memory deleted."}


@app.get(
    "/voices",
    summary="List built-in voices for the Voice Library",
)
async def list_voices() -> dict:
    voices = [
        {
            "id": v["id"],
            "name": v["name"],
            "tags": v["tags"],
            "lang": v.get("lang", "en"),
        }
        for v in BUILT_IN_VOICES
    ]
    return {"voices": voices, "languages": LANGUAGE_META}



@app.post(
    "/voices/preview",
    response_model=VoicePreviewResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Synthesize a short sample of a built-in voice",
)
async def preview_voice(
    body: VoicePreviewRequest,
    firebase_user: dict = Depends(verify_firebase_token),
) -> VoicePreviewResponse:
    builtin = get_builtin_voice(body.voice_id)
    if builtin is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown voice id '{body.voice_id}'.",
        )
    sample = preview_text_for(builtin)
    audio_data, mime_type = await synthesize_speech(
        sample,
        voice_id=builtin["edge_tts_voice"],
        speed=body.speed,
        pitch=body.pitch,
    )
    return VoicePreviewResponse(
        audio_base64=audio_to_base64(audio_data),
        audio_mime_type=mime_type,
    )


def _profile_settings_response(settings) -> ProfileSettingsResponse:
    return ProfileSettingsResponse(
        voice_id=settings.voice_id,
        speed=settings.speed,
        pitch=settings.pitch,
        personality_id=settings.personality_id,
        updated_at=settings.updated_at.isoformat(),
    )


@app.get(
    "/profile",
    response_model=ProfileResponse,
    summary="Current user info (Firebase + Supabase) with saved settings",
)
async def profile(
    firebase_user: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    _require_db()
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
        settings = await get_or_create_user_settings(db, user_id=user.id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while loading profile: {exc}",
        ) from exc

    email = firebase_user.get("email")
    return ProfileResponse(
        name=user.name,
        email=email if isinstance(email, str) else None,
        settings=_profile_settings_response(settings),
    )


@app.put(
    "/profile",
    response_model=ProfileResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Update the current user's display name",
)
async def update_profile(
    body: ProfileUpdateRequest,
    firebase_user: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    """Update the user's display name (email comes from Firebase and is read-only)."""
    _require_db()
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
        user = await update_user_name(db, user_id=user.id, name=body.name.strip())
        settings = await get_or_create_user_settings(db, user_id=user.id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while updating profile: {exc}",
        ) from exc

    email = firebase_user.get("email")
    return ProfileResponse(
        name=user.name,
        email=email if isinstance(email, str) else None,
        settings=_profile_settings_response(settings),
    )


@app.get(
    "/profile/settings",
    response_model=ProfileSettingsResponse,
    summary="Read saved voice/personality preferences",
)
async def get_profile_settings(
    firebase_user: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
) -> ProfileSettingsResponse:
    _require_db()
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
        settings = await get_or_create_user_settings(db, user_id=user.id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while loading settings: {exc}",
        ) from exc
    return _profile_settings_response(settings)


@app.put(
    "/profile/settings",
    response_model=ProfileSettingsResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Save voice/personality preferences",
)
async def put_profile_settings(
    body: ProfileSettingsRequest,
    firebase_user: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
) -> ProfileSettingsResponse:
    _require_db()
    if body.voice_id is not None and get_builtin_voice(body.voice_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown voice id '{body.voice_id}'.",
        )
    if body.personality_id is not None and body.personality_id not in PERSONALITIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown personality id '{body.personality_id}'.",
        )

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
        settings = await update_user_settings(
            db,
            user_id=user.id,
            voice_id=body.voice_id,
            speed=body.speed,
            pitch=body.pitch,
            personality_id=body.personality_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while saving settings: {exc}",
        ) from exc
    return _profile_settings_response(settings)


CONVERSATION_GAP_MINUTES = 30


def _truncate(text: str, length: int = 60) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= length:
        return cleaned
    return cleaned[: length - 1].rstrip() + "…"


def _group_conversations(messages) -> list[list]:
    """Group messages into conversations using a time-gap + turn heuristic."""
    conversations: list[list] = []
    current: list = []
    prev = None
    for msg in messages:
        start_new = False
        if prev is not None:
            gap_minutes = (msg.created_at - prev.created_at).total_seconds() / 60
            if gap_minutes > CONVERSATION_GAP_MINUTES:
                start_new = True
            elif prev.role == "assistant" and msg.role == "user":
                start_new = True
        if start_new and current:
            conversations.append(current)
            current = []
        current.append(msg)
        prev = msg
    if current:
        conversations.append(current)
    return conversations


def _conversation_response(messages) -> ConversationResponse:
    first_user = next((m for m in messages if m.role == "user"), messages[0])
    last = messages[-1]
    preview_source = last if last.role == "assistant" else first_user
    conv_type = "call" if any(getattr(m, "source", None) == "call" for m in messages) else "chat"
    return ConversationResponse(
        id=last.id,
        title=_truncate(first_user.content, 60),
        preview=_truncate(preview_source.content, 80),
        type=conv_type,
        date=last.created_at.isoformat(),
        messages=[
            HistoryMessageResponse(
                role=m.role,
                content=m.content,
                created_at=m.created_at.isoformat(),
                source=m.source,
            )
            for m in messages
        ],
    )


@app.get(
    "/history",
    response_model=HistoryResponse,
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Conversation history grouped into conversations",
)
async def history(
    firebase_user: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    _require_db()
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
        messages = await get_all_messages(db, user_id=user.id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while loading history: {exc}",
        ) from exc

    groups = _group_conversations(messages)
    conversations = [_conversation_response(g) for g in groups]
    conversations.reverse()  # most recent first
    return HistoryResponse(conversations=conversations)


@app.get(
    "/messages",
    response_model=RecentMessagesResponse,
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Recent messages for the chat screen (newest context first)",
)
async def recent_messages(
    firebase_user: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db),
) -> RecentMessagesResponse:
    _require_db()
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
        messages = await get_recent_messages(db, user_id=user.id, limit=60)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while loading messages: {exc}",
        ) from exc

    return RecentMessagesResponse(
        messages=[
            HistoryMessageResponse(
                role=m.role,
                content=m.content,
                created_at=m.created_at.isoformat(),
                source=m.source,
            )
            for m in messages
        ]
    )
