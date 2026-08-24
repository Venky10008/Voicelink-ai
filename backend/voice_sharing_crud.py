"""Database helpers for the voice permission sharing system."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import User, VoicePermission, VoiceProfile


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# VoiceProfile helpers
# ---------------------------------------------------------------------------


async def search_active_voice_profiles(
    session: AsyncSession,
    *,
    excluding_user_id: int,
    query: str | None = None,
    limit: int = 20,
) -> list[tuple[VoiceProfile, str | None]]:
    """
    Search other users' active voice profiles (never the caller's own).

    Returns a list of (VoiceProfile, owner_name) pairs, most recent first.
    Used by the voice-discovery screen so users can request access to voices.
    """
    conditions = [
        VoiceProfile.status == "active",
        VoiceProfile.owner_user_id != excluding_user_id,
    ]
    q = (query or "").strip()
    if q:
        conditions.append(User.name.ilike(f"%{q}%"))

    stmt = (
        select(VoiceProfile, User.name)
        .join(User, VoiceProfile.owner_user_id == User.id)
        .where(*conditions)
        .order_by(VoiceProfile.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(vp, owner_name) for vp, owner_name in result.all()]


async def get_active_voice_profile_for_owner(
    session: AsyncSession,
    *,
    owner_user_id: int,
) -> VoiceProfile | None:
    """Return the owner's active (non-deleted) voice profile, or None."""
    result = await session.execute(
        select(VoiceProfile).where(
            VoiceProfile.owner_user_id == owner_user_id,
            VoiceProfile.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def get_voice_profile_by_id(
    session: AsyncSession,
    *,
    profile_id: int,
) -> VoiceProfile | None:
    """Fetch a voice profile by its primary key (any status)."""
    result = await session.execute(
        select(VoiceProfile).where(VoiceProfile.id == profile_id)
    )
    return result.scalar_one_or_none()


async def create_voice_profile(
    session: AsyncSession,
    *,
    owner_user_id: int,
    cloned_voice_key: str,
    consent_text: str,
) -> VoiceProfile:
    """Create a new active VoiceProfile. Caller must ensure no active profile exists."""
    profile = VoiceProfile(
        owner_user_id=owner_user_id,
        cloned_voice_key=cloned_voice_key,
        consent_text=consent_text,
        consent_given_at=_utcnow(),
        status="active",
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def delete_voice_profile(
    session: AsyncSession,
    *,
    profile_id: int,
) -> None:
    """Mark profile as 'deleted' and revoke all associated permissions."""
    # Revoke all permissions first (no commit yet, handled below)
    await session.execute(
        update(VoicePermission)
        .where(
            VoicePermission.voice_profile_id == profile_id,
            VoicePermission.status.in_(["pending", "approved"]),
        )
        .values(status="revoked", updated_at=_utcnow())
    )
    await session.execute(
        update(VoiceProfile)
        .where(VoiceProfile.id == profile_id)
        .values(status="deleted")
    )
    await session.commit()


# ---------------------------------------------------------------------------
# VoicePermission helpers
# ---------------------------------------------------------------------------


async def get_permission_by_id(
    session: AsyncSession,
    *,
    permission_id: int,
) -> VoicePermission | None:
    """Fetch a permission row with its voice_profile eager-loaded."""
    result = await session.execute(
        select(VoicePermission)
        .options(selectinload(VoicePermission.voice_profile))
        .where(VoicePermission.id == permission_id)
    )
    return result.scalar_one_or_none()


async def get_existing_permission(
    session: AsyncSession,
    *,
    voice_profile_id: int,
    granted_to_user_id: int,
) -> VoicePermission | None:
    """Return an existing permission row for this profile+user pair (any status)."""
    result = await session.execute(
        select(VoicePermission).where(
            VoicePermission.voice_profile_id == voice_profile_id,
            VoicePermission.granted_to_user_id == granted_to_user_id,
        )
    )
    return result.scalar_one_or_none()


async def create_permission_request(
    session: AsyncSession,
    *,
    voice_profile_id: int,
    granted_to_user_id: int,
) -> VoicePermission:
    """Create a new pending permission request."""
    perm = VoicePermission(
        voice_profile_id=voice_profile_id,
        granted_to_user_id=granted_to_user_id,
        status="pending",
    )
    session.add(perm)
    await session.commit()
    await session.refresh(perm)
    return perm


async def get_permission_statuses_for_user(
    session: AsyncSession,
    *,
    voice_profile_ids: list[int],
    user_id: int,
) -> dict[int, str]:
    """Return {voice_profile_id: status} for one user across many profiles.

    Avoids the N+1 query pattern of calling get_existing_permission per row.
    """
    if not voice_profile_ids:
        return {}
    result = await session.execute(
        select(VoicePermission.voice_profile_id, VoicePermission.status).where(
            VoicePermission.voice_profile_id.in_(voice_profile_ids),
            VoicePermission.granted_to_user_id == user_id,
        )
    )
    return {profile_id: status for profile_id, status in result.all()}


async def update_permission_status(
    session: AsyncSession,
    *,
    permission_id: int,
    new_status: str,
) -> None:
    """Set a permission's status to approved/revoked/pending."""
    await session.execute(
        update(VoicePermission)
        .where(VoicePermission.id == permission_id)
        .values(status=new_status, updated_at=_utcnow())
    )
    await session.commit()


async def get_approved_permission(
    session: AsyncSession,
    *,
    voice_profile_id: int,
    requester_user_id: int,
) -> VoicePermission | None:
    """
    CRITICAL SECURITY CHECK — call this before using any cloned voice for TTS.

    Returns the VoicePermission row only if status is exactly 'approved'.
    Returns None for pending, revoked, or non-existent rows.
    """
    result = await session.execute(
        select(VoicePermission).where(
            VoicePermission.voice_profile_id == voice_profile_id,
            VoicePermission.granted_to_user_id == requester_user_id,
            VoicePermission.status == "approved",
        )
    )
    return result.scalar_one_or_none()


async def revoke_all_permissions_for_profile(
    session: AsyncSession,
    *,
    profile_id: int,
) -> None:
    """Bulk-revoke every permission tied to a profile (used on profile deletion)."""
    await session.execute(
        update(VoicePermission)
        .where(
            VoicePermission.voice_profile_id == profile_id,
            VoicePermission.status.in_(["pending", "approved"]),
        )
        .values(status="revoked", updated_at=_utcnow())
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Summary query for GET /voice/my-permissions
# ---------------------------------------------------------------------------


async def get_my_permissions_summary(
    session: AsyncSession,
    *,
    user_id: int,
) -> dict:
    """
    Returns two lists:
    - my_voice_grantees: people who requested/have access to MY voice
    - voices_i_can_use: voice profiles I have a permission row for
    """
    # 1. My active voice profile and its permissions (grantees)
    profile_result = await session.execute(
        select(VoiceProfile)
        .options(
            selectinload(VoiceProfile.permissions).selectinload(
                VoicePermission.grantee
            )
        )
        .where(
            VoiceProfile.owner_user_id == user_id,
            VoiceProfile.status == "active",
        )
    )
    my_profile = profile_result.scalar_one_or_none()

    my_voice_grantees = []
    my_profile_id = None
    if my_profile:
        my_profile_id = my_profile.id
        for perm in my_profile.permissions:
            grantee = perm.grantee
            my_voice_grantees.append(
                {
                    "permission_id": perm.id,
                    "user_id": grantee.id if grantee else None,
                    "user_name": grantee.name if grantee else "Unknown",
                    "status": perm.status,
                    "created_at": perm.created_at.isoformat(),
                    "updated_at": perm.updated_at.isoformat(),
                }
            )

    # 2. Permissions I have been granted (other voices)
    my_perms_result = await session.execute(
        select(VoicePermission)
        .options(
            selectinload(VoicePermission.voice_profile).selectinload(
                VoiceProfile.owner
            )
        )
        .where(VoicePermission.granted_to_user_id == user_id)
    )
    my_perms = list(my_perms_result.scalars().all())

    voices_i_can_use = []
    for perm in my_perms:
        vp = perm.voice_profile
        if vp is None or vp.status == "deleted":
            continue
        owner = vp.owner
        voices_i_can_use.append(
            {
                "permission_id": perm.id,
                "voice_profile_id": vp.id,
                "owner_name": owner.name if owner else "Unknown",
                "status": perm.status,
                "created_at": perm.created_at.isoformat(),
                "updated_at": perm.updated_at.isoformat(),
            }
        )

    return {
        "my_profile_id": my_profile_id,
        "my_voice_grantees": my_voice_grantees,
        "voices_i_can_use": voices_i_can_use,
    }
