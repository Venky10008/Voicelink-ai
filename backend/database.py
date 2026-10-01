"""Async SQLAlchemy engine and session helpers (Supabase Postgres)."""

from __future__ import annotations

import asyncio
import os
import ssl
from urllib.parse import quote, urlparse

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

load_dotenv()

# DEMO_MODE read straight from the env (importing voice_call_ws here would be
# circular). When true, an unreachable Postgres falls back to local SQLite so
# a live demo never depends on the Supabase project being awake.
DEMO_MODE = os.getenv("DEMO_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
DEMO_SQLITE_URL = os.getenv("DEMO_SQLITE_URL", "sqlite+aiosqlite:///demo.db")
# Hard cap (seconds) for the startup Postgres probe in DEMO_MODE.
DEMO_DB_PROBE_TIMEOUT_S = float(os.getenv("DB_PROBE_TIMEOUT_S", "6"))

_DEFAULT_URL = (
    "postgresql+asyncpg://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres"
)


def _normalize_database_url(raw: str) -> str:
    """Ensure asyncpg scheme and URL-encode password special characters."""
    url = raw.strip().strip('"').strip("'")
    if not url:
        return _DEFAULT_URL

    # Supabase dashboard often copies postgresql:// — async SQLAlchemy needs +asyncpg.
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    elif url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]

    # Encode password if it contains reserved characters like @ : / ( ) etc.
    # Split manually so passwords containing '@' still work when wrapped correctly.
    if "://" not in url:
        return url

    scheme, rest = url.split("://", 1)
    if "@" not in rest or ":" not in rest.split("@", 1)[0]:
        return f"{scheme}://{rest}"

    # Find credentials vs host: last '@' before host is safer when password has '@'
    # Format: user:password@host:port/db
    creds_and_host = rest
    # Use rsplit once from the right for host part after final @ that starts the host.
    # If password contains @ and was NOT encoded, parsing is ambiguous — prefer
    # user-provided already-encoded passwords.
    userinfo, hostpart = creds_and_host.rsplit("@", 1)
    if ":" not in userinfo:
        return f"{scheme}://{rest}"

    username, password = userinfo.split(":", 1)
    # Only re-encode if it looks unencoded (contains raw reserved chars).
    if any(ch in password for ch in ("@", "/", "?", "#", "%", " ", "(", ")")):
        # Avoid double-encoding if already percent-encoded.
        if "%" not in password:
            password = quote(password, safe="")

    return f"{scheme}://{username}:{password}@{hostpart}"


def _needs_ssl(url: str) -> bool:
    host = urlparse(url.replace("postgresql+asyncpg", "postgresql", 1)).hostname or ""
    return "supabase.co" in host or os.getenv("DATABASE_SSL", "").lower() in {
        "1",
        "true",
        "require",
    }


DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL", _DEFAULT_URL))

_connect_args: dict = {}
if _needs_ssl(DATABASE_URL):
    # Supabase requires TLS. CERT_NONE avoids local CA issues on some Windows setups.
    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE
    _connect_args["ssl"] = _ssl_ctx
if DEMO_MODE:
    # Bound the startup probe: a paused/unreachable Supabase project must not
    # stall the demo boot — fail fast (default asyncpg connect timeout is 60s)
    # and drop straight to the local SQLite fallback.
    _connect_args["timeout"] = float(os.getenv("DB_PROBE_TIMEOUT_S", "5"))

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency — yields a session and always closes it."""
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()


async def init_db() -> None:
    """Create tables if they do not exist (works on Supabase).

    DEMO_MODE: when Postgres is unreachable (paused Supabase project, broken
    URL…), fall back to a local SQLite database so the demo still runs
    end-to-end — chat history, memory and voice profiles all keep working.
    """
    global engine
    from models import Message, User, UserMemory  # noqa: F401
    from models import UserSettings  # noqa: F401
    from models import VoicePermission, VoiceProfile  # noqa: F401

    try:
        if DEMO_MODE:
            # Bound the WHOLE startup probe. asyncpg applies its own `timeout`
            # to EVERY resolved IP, so a broken pooler host can otherwise burn
            # 5-10× the per-attempt timeout before failing. wait_for caps the
            # total — the demo boot never waits on a dead database.
            conn = await asyncio.wait_for(
                engine.connect(), timeout=DEMO_DB_PROBE_TIMEOUT_S
            )
            await conn.close()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if engine.dialect.name == "postgresql":
                # Idempotent migration for the pre-existing `messages` table
                # (Postgres-only syntax — skipped on the SQLite fallback).
                await conn.execute(
                    text(
                        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS source "
                        "VARCHAR(16) NOT NULL DEFAULT 'chat'"
                    )
                )
        return
    except Exception as exc:
        if not DEMO_MODE:
            raise
        print(
            f"[db] DEMO_MODE: Postgres unavailable ({type(exc).__name__}: {exc}) — "
            f"falling back to local SQLite ({DEMO_SQLITE_URL})",
            flush=True,
        )

    engine = create_async_engine(DEMO_SQLITE_URL, echo=False)
    AsyncSessionLocal.configure(bind=engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[db] DEMO_MODE: local SQLite database ready.", flush=True)
