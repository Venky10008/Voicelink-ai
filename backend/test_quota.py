"""Logic test for the 100-conversation prototype quota (no real DB needed).

Monkeypatches chat_service's DB helpers with fakes, then simulates 100
exchanges and asserts that exactly the 100th exchange triggers a wipe
(fresh_start=True) and that memory extraction is skipped on the wipe.

Usage:
    voice-venv/Scripts/python.exe test_quota.py
"""

import asyncio
from unittest.mock import patch

import chat_service


def _make_fakes(saved: list, extracted_calls: list):
    """Return fake DB helpers that operate on the provided lists."""

    async def fake_save_message(db, *, user_id, role, content, source="chat"):
        saved.append((role, content))

    async def fake_count(db, *, user_id, role="user"):
        return len([s for s in saved if s[0] == "user"])

    async def fake_reset(db, *, user_id):
        saved.clear()

    def fake_schedule(user_id, user_message, ai_reply):
        extracted_calls.append(user_message)

    return fake_save_message, fake_count, fake_reset, fake_schedule


class FakeDB:
    pass


async def main() -> None:
    saved: list[tuple[str, str]] = []
    extracted_calls: list[str] = []
    fake_save_message, fake_count, fake_reset, fake_schedule = _make_fakes(
        saved, extracted_calls
    )

    db = FakeDB()

    original_limit = chat_service.CONVERSATION_LIMIT
    try:
        chat_service.CONVERSATION_LIMIT = 100
        with patch.object(chat_service, "save_message", fake_save_message), \
             patch.object(chat_service, "count_user_messages", fake_count), \
             patch.object(chat_service, "reset_user_conversation_data", fake_reset), \
             patch.object(chat_service, "schedule_memory_extraction", fake_schedule):

            # Exchanges 1..99 must NOT wipe and must schedule memory extraction.
            for i in range(99):
                fresh = await chat_service._save_exchange(
                    db, user_id=1, user_message=f"msg-{i+1}", reply="ok", source="chat"
                )
                assert fresh is False, f"exchange {i+1} should not be fresh_start"
            assert len(extracted_calls) == 99, "memory extraction should run for 1..99"

            # The 100th exchange MUST wipe and skip memory extraction.
            fresh = await chat_service._save_exchange(
                db, user_id=1, user_message="msg-100", reply="ok", source="chat"
            )
            assert fresh is True, "the 100th exchange must trigger a fresh start"
            assert len(saved) == 0, "history should be wiped after the 100th exchange"
            assert len(extracted_calls) == 99, "no memory extraction on the wipe exchange"

            # After the wipe, the count restarts: exchange 101 behaves like #1.
            fresh = await chat_service._save_exchange(
                db, user_id=1, user_message="msg-101", reply="ok", source="chat"
            )
            assert fresh is False, "exchange 101 starts a fresh cycle"
    finally:
        chat_service.CONVERSATION_LIMIT = original_limit

    print("QUOTA LOGIC TEST: OK")


if __name__ == "__main__":
    asyncio.run(main())
