"""Voice sharing / permission endpoints — mounted at /voice in main.py."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Security, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth
import firebase_admin
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from chat_service import display_name
from crud import get_or_create_user
from database import get_db
from voice_clone_engine import (
    VoiceCloneUnavailableError,
    clone_voice as xtts_clone_voice,
    delete_voice as xtts_delete_voice,
    engine_available as xtts_engine_available,
    synthesize_cloned_voice as xtts_synthesize_cloned_voice,
)
from omnivoice_engine import (
    VoiceCloneUnavailableError as OmniVoiceCloneUnavailableError,
    clone_voice as omnivoice_clone_voice,
    delete_voice as omnivoice_delete_voice,
    engine_available as omnivoice_engine_available,
    synthesize_cloned_voice as omnivoice_synthesize_cloned_voice,
)
from voice_service import audio_to_base64
from voice_sharing_crud import (
    create_permission_request,
    create_voice_profile,
    delete_voice_profile,
    get_active_voice_profile_for_owner,
    get_approved_permission,
    get_existing_permission,
    get_my_permissions_summary,
    get_permission_by_id,
    get_permission_statuses_for_user,
    get_voice_profile_by_id,
    search_active_voice_profiles,
    update_permission_status,
)

CONSENT_TEXT = (
    "I consent to having my voice cloned and stored locally on this server (free, "
    "no third-party service). I understand that other users I approve may use this "
    "voice for text-to-speech responses. I can revoke access or delete my voice "
    "profile at any time."
)

router = APIRouter(prefix="/voice", tags=["Voice Sharing"])
_security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Auth helper (mirrors main.py — keeps the router self-contained)
# ---------------------------------------------------------------------------


async def _verify_token(
    creds: HTTPAuthorizationCredentials | None = Security(_security),
) -> dict:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Send: Bearer <Firebase ID token>",
        )
    if not firebase_admin._apps:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase is not configured on the server.",
        )
    try:
        return auth.verify_id_token(creds.credentials)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Firebase auth token.",
        )


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class RequestAccessBody(BaseModel):
    voice_profile_id: int


class PermissionActionBody(BaseModel):
    permission_id: int


class VoiceProfileResponse(BaseModel):
    voice_profile_id: int
    cloned_voice_key: str
    status: str
    created_at: str


class PermissionResponse(BaseModel):
    permission_id: int
    status: str
    updated_at: str


class MyPermissionsResponse(BaseModel):
    my_profile_id: int | None
    my_voice_grantees: list[dict]
    voices_i_can_use: list[dict]
    clone_engine_available: bool = False
    clone_engine_message: str = ""


class ClonedPreviewBody(BaseModel):
    voice_profile_id: int


class ClonedPreviewResponse(BaseModel):
    audio_base64: str
    audio_mime_type: str = "audio/wav"


class DiscoverResponse(BaseModel):
    profiles: list[dict]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/record-sample",
    response_model=VoiceProfileResponse,
    summary="Clone your voice and create a VoiceProfile",
    responses={
        400: {"description": "Consent not confirmed or file missing"},
        401: {"description": "Unauthorized"},
        409: {"description": "Active voice profile already exists"},
        502: {"description": "Audio could not be decoded or cloning failed"},
        503: {"description": "Local voice engine not available"},
    },
)
async def record_sample(
    file: UploadFile = File(..., description="Audio sample for voice cloning"),
    consent_confirmed: bool = Form(
        ...,
        description="Must be true — user has read and agreed to the consent text",
    ),
    firebase_user: dict = Depends(_verify_token),
    db: AsyncSession = Depends(get_db),
) -> VoiceProfileResponse:
    """
    Accept an audio sample and clone the voice with the free local XTTS engine,
    saving the voice profile to the database linked to the authenticated user.

    `consent_confirmed` MUST be true or this endpoint rejects with 400.

    Voice cloning runs 100% locally (`voice_clone_engine.py`) — no third-party
    service, no API key, no credit limits.
    """
    if not consent_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "You must confirm consent before your voice can be cloned. "
                f"Consent text: {CONSENT_TEXT}"
            ),
        )

    firebase_uid = firebase_user.get("uid")
    if not firebase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase token is missing a user id (uid).",
        )

    # Resolve or create the DB user
    try:
        user = await get_or_create_user(
            db, firebase_uid=firebase_uid, name=display_name(firebase_user)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while resolving user: {exc}",
        ) from exc

    # One active profile per user
    existing = await get_active_voice_profile_for_owner(db, owner_user_id=user.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"You already have an active voice profile (id={existing.id}). "
                "Delete it first before creating a new one."
            ),
        )

    # Read the uploaded audio
    try:
        audio_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read uploaded audio: {exc}",
        ) from exc

    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file is empty.",
        )
    if len(audio_bytes) > 15 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file too large (max 15 MB).",
        )

    voice_name = f"VoiceLink_{user.id}"

    # Clone the voice locally (prefer OmniVoice, fall back to XTTS) and get a stable local key.
    try:
        if omnivoice_engine_available():
            cloned_voice_key = await omnivoice_clone_voice(
                audio_bytes, voice_name, filename=file.filename or "sample.wav"
            )
        else:
            cloned_voice_key = await xtts_clone_voice(
                audio_bytes, voice_name, filename=file.filename or "sample.wav"
            )
    except (VoiceCloneUnavailableError, OmniVoiceCloneUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    # Persist to DB
    try:
        profile = await create_voice_profile(
            db,
            owner_user_id=user.id,
            cloned_voice_key=cloned_voice_key,
            consent_text=CONSENT_TEXT,
        )
    except Exception as exc:
        # Best-effort cleanup: remove the local clone to avoid orphans
        if omnivoice_engine_available():
            omnivoice_delete_voice(cloned_voice_key)
        else:
            xtts_delete_voice(cloned_voice_key)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Voice cloned successfully but failed to save to database: {exc}",
        ) from exc

    return VoiceProfileResponse(
        voice_profile_id=profile.id,
        cloned_voice_key=profile.cloned_voice_key,
        status=profile.status,
        created_at=profile.created_at.isoformat(),
    )


@router.post(
    "/request-access",
    response_model=PermissionResponse,
    summary="Request access to use another user's cloned voice",
    responses={
        400: {"description": "Already requested"},
        401: {"description": "Unauthorized"},
        404: {"description": "Voice profile not found or deleted"},
    },
)
async def request_access(
    body: RequestAccessBody,
    firebase_user: dict = Depends(_verify_token),
    db: AsyncSession = Depends(get_db),
) -> PermissionResponse:
    """
    Creates a 'pending' VoicePermission row.
    The voice profile owner must call /voice/approve-access to grant TTS usage.
    """
    firebase_uid = firebase_user.get("uid")
    if not firebase_uid:
        raise HTTPException(status_code=401, detail="Token missing uid.")

    try:
        requester = await get_or_create_user(
            db, firebase_uid=firebase_uid, name=display_name(firebase_user)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc}") from exc

    # Validate the target profile
    profile = await get_voice_profile_by_id(db, profile_id=body.voice_profile_id)
    if profile is None or profile.status == "deleted":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voice profile {body.voice_profile_id} not found or has been deleted.",
        )

    # Cannot request access to your own voice
    if profile.owner_user_id == requester.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot request access to your own voice profile.",
        )

    # Idempotency: if a row already exists, return its current state
    existing_perm = await get_existing_permission(
        db,
        voice_profile_id=body.voice_profile_id,
        granted_to_user_id=requester.id,
    )
    if existing_perm:
        if existing_perm.status in ("pending", "approved"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"You already have a '{existing_perm.status}' request for this voice profile. "
                    f"Permission id: {existing_perm.id}."
                ),
            )
        # If previously revoked, re-open as pending
        await update_permission_status(db, permission_id=existing_perm.id, new_status="pending")
        await db.refresh(existing_perm)
        return PermissionResponse(
            permission_id=existing_perm.id,
            status=existing_perm.status,
            updated_at=existing_perm.updated_at.isoformat(),
        )

    try:
        perm = await create_permission_request(
            db,
            voice_profile_id=body.voice_profile_id,
            granted_to_user_id=requester.id,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc}") from exc

    return PermissionResponse(
        permission_id=perm.id,
        status=perm.status,
        updated_at=perm.updated_at.isoformat(),
    )


@router.post(
    "/approve-access",
    response_model=PermissionResponse,
    summary="Approve a pending access request (owner only)",
    responses={
        400: {"description": "Permission not in pending state"},
        401: {"description": "Unauthorized"},
        403: {"description": "Caller is not the voice profile owner"},
        404: {"description": "Permission not found"},
    },
)
async def approve_access(
    body: PermissionActionBody,
    firebase_user: dict = Depends(_verify_token),
    db: AsyncSession = Depends(get_db),
) -> PermissionResponse:
    """
    The owner of the voice profile approves a pending permission request.
    Only the actual profile owner can call this endpoint successfully.
    """
    firebase_uid = firebase_user.get("uid")
    if not firebase_uid:
        raise HTTPException(status_code=401, detail="Token missing uid.")

    try:
        owner = await get_or_create_user(
            db, firebase_uid=firebase_uid, name=display_name(firebase_user)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc}") from exc

    perm = await get_permission_by_id(db, permission_id=body.permission_id)
    if perm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Permission {body.permission_id} not found.",
        )

    # Security: caller must own the voice profile
    if perm.voice_profile is None or perm.voice_profile.owner_user_id != owner.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the owner of this voice profile and cannot approve this request.",
        )

    if perm.voice_profile.status == "deleted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot approve access to a deleted voice profile.",
        )

    if perm.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Permission is already '{perm.status}', not pending.",
        )

    await update_permission_status(db, permission_id=perm.id, new_status="approved")
    await db.refresh(perm)

    return PermissionResponse(
        permission_id=perm.id,
        status=perm.status,
        updated_at=perm.updated_at.isoformat(),
    )


@router.post(
    "/revoke-access",
    response_model=PermissionResponse,
    summary="Revoke an approved or pending access request (owner only)",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Caller is not the voice profile owner"},
        404: {"description": "Permission not found"},
    },
)
async def revoke_access(
    body: PermissionActionBody,
    firebase_user: dict = Depends(_verify_token),
    db: AsyncSession = Depends(get_db),
) -> PermissionResponse:
    """
    The voice profile owner revokes an approved or pending permission.
    After this, the grantee can no longer use the voice for TTS.
    """
    firebase_uid = firebase_user.get("uid")
    if not firebase_uid:
        raise HTTPException(status_code=401, detail="Token missing uid.")

    try:
        owner = await get_or_create_user(
            db, firebase_uid=firebase_uid, name=display_name(firebase_user)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc}") from exc

    perm = await get_permission_by_id(db, permission_id=body.permission_id)
    if perm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Permission {body.permission_id} not found.",
        )

    # Security: caller must own the voice profile
    if perm.voice_profile is None or perm.voice_profile.owner_user_id != owner.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the owner of this voice profile and cannot revoke this permission.",
        )

    if perm.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Permission is already revoked.",
        )

    await update_permission_status(db, permission_id=perm.id, new_status="revoked")
    await db.refresh(perm)

    return PermissionResponse(
        permission_id=perm.id,
        status=perm.status,
        updated_at=perm.updated_at.isoformat(),
    )


@router.delete(
    "/delete-profile",
    status_code=status.HTTP_200_OK,
    summary="Delete your voice profile and revoke all permissions (owner only)",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "No active voice profile found"},
    },
)
async def delete_profile(
    firebase_user: dict = Depends(_verify_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Marks the user's active voice profile as 'deleted', revokes ALL related
    permissions (pending + approved), and removes the voice from ElevenLabs.
    """
    firebase_uid = firebase_user.get("uid")
    if not firebase_uid:
        raise HTTPException(status_code=401, detail="Token missing uid.")

    try:
        user = await get_or_create_user(
            db, firebase_uid=firebase_uid, name=display_name(firebase_user)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc}") from exc

    profile = await get_active_voice_profile_for_owner(db, owner_user_id=user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You do not have an active voice profile to delete.",
        )

    cloned_voice_key = profile.cloned_voice_key
    profile_id = profile.id

    try:
        await delete_voice_profile(db, profile_id=profile_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while deleting voice profile: {exc}",
        ) from exc

    # Best-effort cleanup of the locally stored clone
    if omnivoice_engine_available():
        omnivoice_delete_voice(cloned_voice_key)
    else:
        xtts_delete_voice(cloned_voice_key)

    return {
        "detail": "Voice profile deleted and all permissions revoked.",
        "voice_profile_id": profile_id,
    }


@router.get(
    "/discover",
    response_model=DiscoverResponse,
    summary="Search other users who have a cloned voice, to request access",
    responses={
        401: {"description": "Unauthorized"},
    },
)
async def discover_voices(
    q: str | None = Query(None, max_length=64, description="Name filter"),
    firebase_user: dict = Depends(_verify_token),
    db: AsyncSession = Depends(get_db),
) -> DiscoverResponse:
    """
    Lists other users' active cloned voices (never your own). Each entry
    includes `my_status` so the UI knows whether you already have a pending,
    approved or revoked request for that voice.
    """
    firebase_uid = firebase_user.get("uid")
    if not firebase_uid:
        raise HTTPException(status_code=401, detail="Token missing uid.")

    try:
        user = await get_or_create_user(
            db, firebase_uid=firebase_uid, name=display_name(firebase_user)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc}") from exc

    try:
        rows = await search_active_voice_profiles(
            db, excluding_user_id=user.id, query=q
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while searching voices: {exc}",
        ) from exc

    # Batch-load my current status for all returned profiles (single query).
    status_map = await get_permission_statuses_for_user(
        db,
        voice_profile_ids=[vp.id for vp, _ in rows],
        user_id=user.id,
    )

    profiles = [
        {
            "voice_profile_id": vp.id,
            "owner_name": owner_name or "Unknown",
            "created_at": vp.created_at.isoformat(),
            "my_status": status_map.get(vp.id, "none"),
        }
        for vp, owner_name in rows
    ]

    return DiscoverResponse(profiles=profiles)


@router.post(
    "/preview-cloned",
    response_model=ClonedPreviewResponse,
    summary="Hear a cloned voice (owner or approved grantee only)",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Caller has no approved access to this voice"},
        404: {"description": "Voice profile not found"},
        503: {"description": "Local voice engine not available"},
    },
)
async def preview_cloned(
    body: ClonedPreviewBody,
    firebase_user: dict = Depends(_verify_token),
    db: AsyncSession = Depends(get_db),
) -> ClonedPreviewResponse:
    """
    Synthesizes a short sample with a cloned voice. The profile owner may
    always preview their own voice; anyone else needs approved access.
    """
    firebase_uid = firebase_user.get("uid")
    if not firebase_uid:
        raise HTTPException(status_code=401, detail="Token missing uid.")

    try:
        user = await get_or_create_user(
            db, firebase_uid=firebase_uid, name=display_name(firebase_user)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc}") from exc

    vp = await get_voice_profile_by_id(db, profile_id=body.voice_profile_id)
    if vp is None or vp.status == "deleted":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voice profile {body.voice_profile_id} not found or has been deleted.",
        )

    # Owner can always preview; others need an approved permission.
    if vp.owner_user_id != user.id:
        approved = await get_approved_permission(
            db, voice_profile_id=vp.id, requester_user_id=user.id
        )
        if approved is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "You do not have approved access to this cloned voice. "
                    "Request access from the voice owner and wait for approval."
                ),
            )

    sample = "Hi, this is my cloned voice. How does it sound?"
    try:
        if omnivoice_engine_available():
            audio_data, mime_type = await omnivoice_synthesize_cloned_voice(
                sample, vp.cloned_voice_key
            )
        else:
            audio_data, mime_type = await xtts_synthesize_cloned_voice(
                sample, vp.cloned_voice_key
            )
    except (VoiceCloneUnavailableError, OmniVoiceCloneUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Cloned voice preview failed: {exc}",
        ) from exc

    return ClonedPreviewResponse(
        audio_base64=audio_to_base64(audio_data),
        audio_mime_type=mime_type,
    )


@router.get(
    "/my-permissions",
    response_model=MyPermissionsResponse,
    summary="List who has access to my voice, and what voices I have access to",
    responses={
        401: {"description": "Unauthorized"},
    },
)
async def my_permissions(
    firebase_user: dict = Depends(_verify_token),
    db: AsyncSession = Depends(get_db),
) -> MyPermissionsResponse:
    """
    Returns two lists:
    - `my_voice_grantees`: people who have requested or been approved access to MY cloned voice
    - `voices_i_can_use`: voice profiles that I have a permission row for (any status)
    - `clone_engine_available`: whether the free local XTTS engine can clone right now
    """
    firebase_uid = firebase_user.get("uid")
    if not firebase_uid:
        raise HTTPException(status_code=401, detail="Token missing uid.")

    try:
        user = await get_or_create_user(
            db, firebase_uid=firebase_uid, name=display_name(firebase_user)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc}") from exc

    try:
        summary = await get_my_permissions_summary(db, user_id=user.id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while loading permissions: {exc}",
        ) from exc

    # Check which engine is available (prefer OmniVoice)
    if omnivoice_engine_available():
        summary["clone_engine_available"] = True
        summary["clone_engine_message"] = (
            "Voice cloning is ready — OmniVoice engine is running (600+ languages)."
        )
        summary["clone_engine_type"] = "omnivoice"
    elif xtts_engine_available():
        summary["clone_engine_available"] = True
        summary["clone_engine_message"] = (
            "Voice cloning is ready — XTTS v2 engine is running."
        )
        summary["clone_engine_type"] = "xtts-v2"
    else:
        summary["clone_engine_available"] = False
        summary["clone_engine_message"] = (
            "The local voice engine is not available in this Python environment. "
            "Install OmniVoice (pip install omnivoice) or run the backend from the Python 3.11 venv "
            "(backend/voice-venv) to enable real cloning — voice calls still work with the free Edge TTS voices."
        )
        summary["clone_engine_type"] = "none"

    return MyPermissionsResponse(**summary)
