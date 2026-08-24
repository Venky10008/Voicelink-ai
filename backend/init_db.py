"""Create tables on the configured database (Supabase).

Usage (from backend/, with venv active):
  python init_db.py
"""

from __future__ import annotations

import asyncio

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()


async def main() -> None:
    from database import DATABASE_URL, engine, init_db

    # Mask password in logs
    display = DATABASE_URL
    if "@" in display and "://" in display:
        scheme, rest = display.split("://", 1)
        userinfo, hostpart = rest.rsplit("@", 1)
        user = userinfo.split(":", 1)[0]
        display = f"{scheme}://{user}:***@{hostpart}"

    print(f"Connecting to: {display}")
    await init_db()
    print("Tables created (or already existed).")

    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' "
                "AND table_name IN ('users', 'messages', 'user_memory') "
                "ORDER BY table_name"
            )
        )
        tables = [row[0] for row in result.fetchall()]
        print("Found tables:", ", ".join(tables) if tables else "(none)")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
