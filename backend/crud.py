"""Database helpers for users, messages, and memory."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models import Message, User, UserMemory, UserSettings, utcnow


async def get_or_create_user(
    session: AsyncSession,
    *,
    firebase_uid: str,
    name: str | None,
) -> User:
    result = await session.execute(
        select(User).where(User.firebase_uid == firebase_uid)
    )
    user = result.scalar_one_or_none()
    if user is not None:
        # Do NOT overwrite the stored name: the user may have customized it via
        # PUT /profile. The Firebase-derived name is only used when creating.
        return user

    user = User(firebase_uid=firebase_uid, name=name)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_recent_messages(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int = 10,
) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.user_id == user_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()  # chronological order for the prompt
    return rows


async def save_message(
    session: AsyncSession,
    *,
    user_id: int,
    role: str,
    content: str,
    source: str = "chat",
) -> Message:
    msg = Message(user_id=user_id, role=role, content=content, source=source)
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return msg


async def get_all_messages(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int = 500,
) -> list[Message]:
    """All of a user's messages, oldest first (for history grouping)."""
    result = await session.execute(
        select(Message)
        .where(Message.user_id == user_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_user_messages(
    session: AsyncSession,
    *,
    user_id: int,
    role: str = "user",
) -> int:
    """Count how many messages of a role a user has (used for the 100-conversation limit)."""
    result = await session.execute(
        select(func.count())
        .select_from(Message)
        .where(Message.user_id == user_id, Message.role == role)
    )
    return int(result.scalar_one() or 0)


async def reset_user_conversation_data(
    session: AsyncSession,
    *,
    user_id: int,
) -> None:
    """Delete all of a user's messages + memories (fresh start).

    Keeps the account, profile name, settings, and cloned voice — only chat
    history and "what I remember" facts are cleared.
    """
    await session.execute(delete(Message).where(Message.user_id == user_id))
    await session.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
    await session.commit()


async def get_user_memories(
    session: AsyncSession,
    *,
    user_id: int,
) -> list[UserMemory]:
    result = await session.execute(
        select(UserMemory)
        .where(UserMemory.user_id == user_id)
        .order_by(UserMemory.key.asc())
    )
    return list(result.scalars().all())


async def upsert_memory(
    session: AsyncSession,
    *,
    user_id: int,
    key: str,
    value: str,
) -> UserMemory:
    result = await session.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == key,
        )
    )
    memory = result.scalar_one_or_none()
    if memory is None:
        memory = UserMemory(user_id=user_id, key=key, value=value)
        session.add(memory)
    else:
        memory.value = value
        memory.updated_at = utcnow()

    await session.commit()
    await session.refresh(memory)
    return memory


async def delete_memory(
    session: AsyncSession,
    *,
    user_id: int,
    key: str,
) -> bool:
    """Delete one memory. Returns True if a row was deleted."""
    result = await session.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == key,
        )
    )
    memory = result.scalar_one_or_none()
    if memory is None:
        return False
    await session.delete(memory)
    await session.commit()
    return True


async def get_or_create_user_settings(
    session: AsyncSession,
    *,
    user_id: int,
) -> UserSettings:
    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if settings is not None:
        return settings

    settings = UserSettings(user_id=user_id)
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings


async def update_user_name(
    session: AsyncSession,
    *,
    user_id: int,
    name: str | None,
) -> User:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.name = name
    await session.commit()
    await session.refresh(user)
    return user


async def update_user_settings(
    session: AsyncSession,
    *,
    user_id: int,
    voice_id: str | None = None,
    speed: float | None = None,
    pitch: float | None = None,
    personality_id: str | None = None,
) -> UserSettings:
    settings = await get_or_create_user_settings(session, user_id=user_id)
    if voice_id is not None:
        settings.voice_id = voice_id
    if speed is not None:
        settings.speed = speed
    if pitch is not None:
        settings.pitch = pitch
    if personality_id is not None:
        settings.personality_id = personality_id
    settings.updated_at = utcnow()
    await session.commit()
    await session.refresh(settings)
    return settings


def is_db_error(exc: BaseException) -> bool:
    return isinstance(exc, SQLAlchemyError)
