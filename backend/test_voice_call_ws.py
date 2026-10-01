"""Smoke test for the real-time voice call WebSocket protocol.

Runs the full client↔server exchange against a minimal FastAPI app with
mocked transcription / LLM / TTS, so no Firebase, DB, Whisper, Groq or
network access is needed. Verifies the event sequence a browser relies on:

    config → ready
    audio chunks + end_utterance → status(transcribing) → status(thinking,
    transcript) → token… → audio… → done

Plus the hands-free call features:
    discard  — drops buffered audio without starting a reply
    barge-in — cancel + new audio mid-reply starts a fresh turn with only
               the post-cancel audio

Usage:
    voice-venv/Scripts/python.exe test_voice_call_ws.py
"""

import asyncio

import voice_call_ws as vc
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient


async def _fake_resolve(db, firebase_user, voice_profile_id, voice_id):
    return ("en-US-AriaNeural", None)  # (tts_voice_id, cloned_voice_key)


# The server drops audio blobs under 8 KB (ambient-noise guard), so the fake
# chunks below are sized like real MediaRecorder utterances (~9 KB each).
_CHUNK_1 = b"chunk1" * 1500
_CHUNK_2 = b"chunk2" * 1500
_BARGE_1 = b"barge1" * 1500
_BARGE_2 = b"barge2" * 1500


async def _fake_transcribe(audio_bytes, filename, **kwargs):
    if audio_bytes == _CHUNK_1 + _CHUNK_2:
        return "hello there"
    if audio_bytes == _BARGE_1 + _BARGE_2:
        return "never mind"
    raise AssertionError(f"unexpected audio: {audio_bytes!r}")


async def _fake_stream(db, **kwargs):
    yield ("emotion", "happy")
    for token in ("Hi ", "there!", " How are you?"):
        # A real LLM streams slowly — the pause keeps the turn in flight long
        # enough for the barge-in test to interrupt it deterministically.
        yield ("token", token)
        await asyncio.sleep(0.05)


async def _fake_synthesize(text, **kwargs):
    return f"MP3:{text}".encode(), "audio/mpeg"


def _patch_services() -> None:
    vc.resolve_voice_config = _fake_resolve
    vc.transcribe_audio_groq = _fake_transcribe  # Groq-first path
    vc.transcribe_audio = _fake_transcribe  # local fallback path
    vc.stream_chat_reply = _fake_stream
    vc.synthesize_speech = _fake_synthesize
    # Pin DEMO_MODE on so these tests exercise the demo path (Edge TTS only),
    # exactly how the app runs for a live demo.
    vc.DEMO_MODE = True


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.websocket("/ws/voice-call")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        await vc.handle_voice_call(websocket, db=None, firebase_user={"uid": "test"})

    return app


def _receive_until(ws, wanted: set[str]) -> list[dict]:
    """Receive events until `wanted` kinds have all been seen (or a cap)."""
    events: list[dict] = []
    seen: set[str] = set()
    while not wanted.issubset(seen):
        event = ws.receive_json()
        events.append(event)
        seen.add(event["type"])
    return events


def test_happy_path() -> None:
    _patch_services()
    with TestClient(_build_app()) as client:
        with client.websocket_connect("/ws/voice-call") as ws:
            ws.send_json({"type": "config", "voice_id": "aria"})
            assert ws.receive_json() == {"type": "ready"}

            ws.send_bytes(_CHUNK_1)
            ws.send_bytes(_CHUNK_2)
            ws.send_json({"type": "end_utterance"})

            events = _receive_until(ws, {"token", "audio", "done"})
            kinds = [e["type"] for e in events]

            assert any(e.get("state") == "transcribing" for e in events)
            thinking = next(e for e in events if e.get("state") == "thinking")
            assert thinking.get("transcript") == "hello there"
            assert kinds.count("token") == 3
            assert kinds.count("audio") == 2  # "Hi there!" + "How are you?"
            done = events[-1]
            assert done["type"] == "done"
            assert done["emotion"] == "happy"
            assert done["fresh_start"] is False
            print("HAPPY PATH: OK —", kinds)


def test_ping_pong() -> None:
    _patch_services()
    with TestClient(_build_app()) as client:
        with client.websocket_connect("/ws/voice-call") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            print("PING/PONG: OK")


def test_end_utterance_without_audio_is_ignored() -> None:
    _patch_services()
    with TestClient(_build_app()) as client:
        with client.websocket_connect("/ws/voice-call") as ws:
            ws.send_json({"type": "config", "voice_id": "aria"})
            assert ws.receive_json() == {"type": "ready"}
            ws.send_json({"type": "end_utterance"})  # no chunks → must be skipped
            ws.send_json({"type": "ping"})  # if the turn had started, this order breaks
            assert ws.receive_json() == {"type": "pong"}
            print("EMPTY UTTERANCE: OK")


def test_discard_drops_buffered_audio() -> None:
    """discard must clear buffered chunks without ever starting a reply."""
    _patch_services()
    with TestClient(_build_app()) as client:
        with client.websocket_connect("/ws/voice-call") as ws:
            ws.send_json({"type": "config", "voice_id": "aria"})
            assert ws.receive_json() == {"type": "ready"}
            ws.send_bytes(b"noise1")
            ws.send_json({"type": "discard"})
            ws.send_bytes(b"noise2")
            ws.send_json({"type": "discard"})
            ws.send_json({"type": "ping"})  # a turn must NOT have started
            assert ws.receive_json() == {"type": "pong"}
            print("DISCARD: OK")


def test_barge_in_aborts_reply_and_uses_only_new_audio() -> None:
    """A cancel mid-reply kills the turn; the next end_utterance transcribes
    ONLY the audio that arrived after the cancel (the new utterance)."""
    _patch_services()
    with TestClient(_build_app()) as client:
        with client.websocket_connect("/ws/voice-call") as ws:
            ws.send_json({"type": "config", "voice_id": "aria"})
            assert ws.receive_json() == {"type": "ready"}

            # Turn 1 starts...
            ws.send_bytes(_CHUNK_1)
            ws.send_bytes(_CHUNK_2)
            ws.send_json({"type": "end_utterance"})

            # ...the user interrupts mid-reply (barge-in): cancel + new audio.
            ws.send_json({"type": "cancel"})
            ws.send_bytes(_BARGE_1)
            ws.send_bytes(_BARGE_2)
            ws.send_json({"type": "end_utterance"})

            events = _receive_until(ws, {"token", "audio", "done"})
            kinds = [e["type"] for e in events]
            # Only the barge-in turn finishes cleanly; the first was aborted.
            assert kinds.count("done") == 1
            # The LAST thinking event belongs to the barge-in turn, and it must
            # show the transcript of the post-cancel audio, NOT the old chunks.
            thinkings = [e for e in events if e.get("state") == "thinking"]
            assert thinkings[-1].get("transcript") == "never mind"
            # The barge-in reply streams sentence-by-sentence (2 sentences →
            # 2 audio frames in the demo path). Turn 1 may or may not have sent
            # a frame before the cancel landed — that's a scheduling race.
            assert kinds.count("audio") >= 2  # "Hi there!" + "How are you?"
            print("BARGE-IN: OK —", kinds)


if __name__ == "__main__":
    test_ping_pong()
    test_end_utterance_without_audio_is_ignored()
    test_discard_drops_buffered_audio()
    test_barge_in_aborts_reply_and_uses_only_new_audio()
    test_happy_path()
    print("\nVOICE CALL WS PROTOCOL: ALL OK")
