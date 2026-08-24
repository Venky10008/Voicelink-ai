"""SQLAlchemy models for VoiceLink AI."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list[Message]] = relationship(back_populates="user")
    memories: Mapped[list[UserMemory]] = relationship(back_populates="user")
    settings: Mapped[UserSettings | None] = relationship(back_populates="user", uselist=False)
    voice_profiles: Mapped[list[VoiceProfile]] = relationship(back_populates="owner")
    voice_permissions: Mapped[list[VoicePermission]] = relationship(
        back_populates="grantee", foreign_keys="VoicePermission.granted_to_user_id"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="chat")  # "chat" | "call"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="messages")


class UserMemory(Base):
    __tablename__ = "user_memory"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_memory_user_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    user: Mapped[User] = relationship(back_populates="memories")


class VoiceProfile(Base):
    """A cloned voice owned by one user, created via the free local XTTS engine."""

    __tablename__ = "voice_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # The physical DB column keeps its legacy name ("elevenlabs_voice_id") so no
    # migration is needed. ElevenLabs was fully removed from this project; this
    # column now stores a LOCAL cloned-voice key for the free XTTS engine.
    cloned_voice_key: Mapped[str] = mapped_column("elevenlabs_voice_id", String(256))
    consent_text: Mapped[str] = mapped_column(Text)
    consent_given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # status: "active" | "deleted"
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User] = relationship(back_populates="voice_profiles")
    permissions: Mapped[list[VoicePermission]] = relationship(
        back_populates="voice_profile", cascade="all, delete-orphan"
    )


class VoicePermission(Base):
    """Tracks which user has (or requested) access to use a cloned voice for TTS."""

    __tablename__ = "voice_permissions"
    __table_args__ = (
        UniqueConstraint(
            "voice_profile_id",
            "granted_to_user_id",
            name="uq_voice_permission_profile_user",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    voice_profile_id: Mapped[int] = mapped_column(
        ForeignKey("voice_profiles.id", ondelete="CASCADE"), index=True
    )
    granted_to_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # status: "pending" | "approved" | "revoked"
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    voice_profile: Mapped[VoiceProfile] = relationship(back_populates="permissions")
    grantee: Mapped[User] = relationship(
        back_populates="voice_permissions", foreign_keys=[granted_to_user_id]
    )


class UserSettings(Base):
    """Per-user frontend preferences (active voice, speed/pitch, personality)."""

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    voice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    speed: Mapped[float] = mapped_column(Float, default=1.0)
    pitch: Mapped[float] = mapped_column(Float, default=1.0)
    personality_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    user: Mapped[User] = relationship(back_populates="settings")
