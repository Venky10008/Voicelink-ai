"""Real-time voice call over WebSocket — the "phone call" experience.

The client opens ONE WebSocket for the whole call. While the user talks,
recorded audio chunks stream up to the server (250 ms MediaRecorder slices),
and the server streams the AI reply back sentence-by-sentence so audio
playback starts ~1-2 s after the LLM begins answering instead of waiting for
the whole reply to be generated (the old /voice-chat endpoint made users wait
for transcription + full LLM + full TTS + base64 download before playing
anything).

Protocol (JSON text frames + binary audio frames)
-------------------------------------------------

The call is HANDS-FREE: the mic stays open for the whole call. The client
only sends audio while its VAD believes the user is speaking (pre-roll +
live chunks), so it can interrupt a reply mid-stream exactly like a real
phone call (barge-in). The server buffers every chunk it receives and turns
them into an utterance only when told to.

Client → server:
    {"type": "config", "voice_profile_id"?, "voice_id"?, "personality"?, "language"?}
    <binary>: one webm audio chunk from the MediaRecorder timeslice
    {"type": "end_utterance"}  — transcribe the buffered audio & reply
    {"type": "cancel"}         — abort the in-flight turn AND drop the audio
                                buffered so far (barge-in / hang up)
    {"type": "discard"}        — drop the buffered audio WITHOUT replying
                                (client decided it was noise / too short)
    {"type": "ping"}           — keepalive

Server → client:
    {"type": "ready"}                                          — config accepted
    {"type": "status", "state": "transcribing", "transcript"}  — user's words
    {"type": "status", "state": "thinking"}                    — LLM working
    {"type": "token", "content": "..."}                        — LLM stream token
    {"type": "audio", "audio_base64": "...", "mime": "..."}    — one TTS chunk
    {"type": "voice_fallback_notice", "detail": "..."}         — cloned voice could
                                                                 NOT be used this turn;
                                                                 a default voice spoke
                                                                 instead (never silent)
    {"type": "done", "emotion", "fresh_start", "notice"}
    {"type": "error", "detail": "..."}
    {"type": "pong"}

Demo mode (DEMO_MODE=true)
--------------------------
Set DEMO_MODE=true in backend/.env for a bullet-proof live demo: every reply
is synthesized by Microsoft Edge TTS (fast, free, no model downloads) and the
local cloning engines (Chatterbox / OmniVoice / XTTS) are never touched.
Cloned "My Voice" profiles stay selectable in the UI — they simply route
through Edge TTS behind the scenes — and every failure (STT, LLM, TTS, voice
resolution) falls back to a safe default instead of erroring mid-call.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv

# Load the backend .env before reading DEMO_MODE so the flag is correct no
# matter how this module gets imported (main.py also calls this — repeated
# loads are harmless and never override already-set environment variables).
load_dotenv()


def _env_flag(name: str, default: str = "false") -> bool:
    """Parse a boolean env flag ("1/true/yes/on" → True)."""
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


# DEMO_MODE=true → every reply is spoken by Microsoft Edge TTS (fast, free,
# reliable). Chatterbox / OmniVoice / XTTS are skipped entirely, and cloned
# voices ("My Voice") stay selectable but route through Edge TTS behind the
# scenes — so a live demo can never hang inside a GPU model or crash on stage.
DEMO_MODE = _env_flag("DEMO_MODE", "false")

from fastapi import HTTPException, WebSocket, WebSocketDisconnect

from chat_service import (
    CONVERSATION_LIMIT_NOTICE,
    display_name,
    emotion_voice_params,
    stream_chat_reply,
)
from crud import get_or_create_user, get_or_create_user_settings
from voice_catalog import get_builtin_voice
from voice_clone_engine import (
    VoiceCloneUnavailableError,
    VoiceSynthesisError as XTTSVoiceSynthesisError,
    engine_available as xtts_engine_available,
    synthesize_cloned_voice as xtts_synthesize_cloned_voice,
)
from chatterbox_engine import (
    VoiceCloneUnavailableError as ChatterboxCloneUnavailableError,
    VoiceSynthesisError as ChatterboxSynthesisError,
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
from voice_sharing_crud import get_approved_permission, get_voice_profile_by_id

# Sentence-ending punctuation for English + the Indian languages the app speaks.
_SENTENCE_ENDINGS = ".!?।？！…"
_SENTENCE_SPLIT_RE = re.compile(rf"([{_SENTENCE_ENDINGS}]+\s*|\n+)")

# TEMPORARY diagnostic: when set, every received utterance is written to this
# folder so the raw audio bytes can be inspected (e.g. with PyAV) when STT
# rejects the file. Remove once transcription is stable.
DEBUG_AUDIO_DIR = os.getenv("VOICELINK_DEBUG_AUDIO_DIR", "").strip()

# Shown to the user whenever the requested cloned voice could NOT be used and a
# default voice spoke instead — the fallback is never silent.
VOICE_FALLBACK_NOTICE_DETAIL = "Voice cloning failed, using default voice"

# Spoken instead of an error frame when the LLM stream fails before producing
# any tokens — the call keeps going instead of showing "Something went wrong".
LLM_FALLBACK_REPLY = (
    "Sorry, I had a small hiccup just now. Could you say that again?"
)

# Hard ceilings so a stalled STT provider can never freeze a turn: the turn is
# dropped with status "idle" and the user simply speaks again.
STT_GROQ_TIMEOUT_S = 20.0
STT_LOCAL_TIMEOUT_S = 60.0


async def send_voice_fallback_notice(websocket: WebSocket) -> None:
    """Tell the client the cloned voice could not be used for this turn."""
    try:
        await websocket.send_json(
            {
                "type": "voice_fallback_notice",
                "detail": VOICE_FALLBACK_NOTICE_DETAIL,
            }
        )
    except Exception:
        pass  # best-effort — the audio fallback itself still proceeds


class _TurnCancelled(Exception):
    """Raised inside a turn when the client asks to cancel it (hung up)."""


async def resolve_voice_config(
    db,
    firebase_user: dict,
    voice_profile_id: int | None,
    voice_id: str | None,
) -> tuple[str | None, str | None]:
    """Resolve which voice a call speaks with. Mirrors /voice-chat's rules.

    Cloned voices verify live permission; built-in voices must exist.
    Returns (tts_voice_id, cloned_voice_key) — exactly what synthesis needs.

    DEMO_MODE: a cloned "My Voice" profile that cannot be resolved (DB down,
    lost permission, deleted profile…) must never fail the call — it logs and
    falls back to the default Edge voice instead (the cloning engines are
    skipped in the synthesis path anyway).
    """
    tts_voice_id: str | None = None
    cloned_voice_key: str | None = None

    if voice_profile_id is not None:
        try:
            vp = await get_voice_profile_by_id(db, profile_id=voice_profile_id)
            if vp is None or vp.status == "deleted":
                raise HTTPException(
                    status_code=404,
                    detail=f"Voice profile {voice_profile_id} not found or has been deleted.",
                )
            firebase_uid = firebase_user.get("uid")
            if not firebase_uid:
                raise HTTPException(
                    status_code=401,
                    detail="Firebase token is missing a user id (uid).",
                )
            try:
                requester = await get_or_create_user(
                    db,
                    firebase_uid=firebase_uid,
                    name=display_name(firebase_user),
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail=f"Database error while resolving user: {exc}",
                ) from exc

            cloned_voice_key = vp.cloned_voice_key
            if vp.owner_user_id != requester.id:
                approved = await get_approved_permission(
                    db,
                    voice_profile_id=voice_profile_id,
                    requester_user_id=requester.id,
                )
                if approved is None:
                    raise HTTPException(
                        status_code=403,
                        detail=(
                            "You do not have approved access to this cloned voice. "
                            "Request access from the voice owner and wait for approval."
                        ),
                    )
        except HTTPException:
            if not DEMO_MODE:
                raise
            print(
                f"[voice-call] DEMO_MODE: cloned voice profile {voice_profile_id} "
                "unavailable — speaking with the default Edge voice instead",
                flush=True,
            )
            return None, None
        except Exception as exc:
            if not DEMO_MODE:
                raise HTTPException(
                    status_code=503,
                    detail=f"Database error while resolving voice: {exc}",
                ) from exc
            print(
                f"[voice-call] DEMO_MODE: voice lookup failed ({exc}) — "
                "speaking with the default Edge voice instead",
                flush=True,
            )
            return None, None
    elif voice_id is not None:
        builtin = get_builtin_voice(voice_id)
        if builtin is None:
            if not DEMO_MODE:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown voice id '{voice_id}'.",
                )
            print(
                f"[voice-call] DEMO_MODE: unknown voice id '{voice_id}' — "
                "speaking with the default Edge voice instead",
                flush=True,
            )
            return None, None
        tts_voice_id = builtin["edge_tts_voice"]

    return tts_voice_id, cloned_voice_key


def split_sentences(text: str, max_chars: int = 200) -> list[str]:
    """Split a reply into TTS-sized sentences (punctuation stays attached).

    Newlines become sentence breaks (they read as pauses), and any sentence
    longer than ``max_chars`` is hard-cut at a word boundary so a single
    synthesis call never takes too long.
    """
    pieces = _SENTENCE_SPLIT_RE.split(text)
    sentences: list[str] = []
    i = 0
    while i < len(pieces):
        chunk = (pieces[i] + (pieces[i + 1] if i + 1 < len(pieces) else "")).strip()
        i += 2
        if not chunk:
            continue
        if len(chunk) <= max_chars:
            sentences.append(chunk)
            continue
        remainder = chunk
        while len(remainder) > max_chars:
            cut = remainder[:max_chars]
            space = cut.rfind(" ")
            if space > max_chars // 2:
                sentences.append(cut[:space])
                remainder = remainder[space:].lstrip()
            else:
                sentences.append(cut)
                remainder = remainder[max_chars:].lstrip()
        if remainder:
            sentences.append(remainder)
    return sentences


async def _handle_turn(
    websocket: WebSocket,
    db,
    firebase_user: dict,
    session: dict,
    chunks: list[bytes],
) -> None:
    """One user utterance → transcribe → stream LLM → stream TTS audio.

    Sentences are synthesized AS THEY ARRIVE from the LLM stream (a background
    worker drains a queue), so audio playback starts after the FIRST completed
    sentence instead of waiting for the whole reply.
    """
    config = session["config"]
    # Language resolution order: explicit picker > session auto-lock > "en".
    # Defaulting to "en" (instead of None) stops Whisper from auto-detecting
    # English speech as Hindi/Telugu/Tamil — the root cause of wrong-language
    # transcripts and wrong-language AI replies.
    lang = config.get("language") or session.get("language_lock") or "en"
    # ---- timing instrumentation -------------------------------------------
    # Marks: user audio received → STT done → first LLM token → first complete
    # sentence → first audio chunk sent. Printed before every "done" frame.
    t_audio_received = time.perf_counter()

    def _ms(a: float | None, b: float | None) -> str:
        return "n/a" if a is None or b is None else f"{(b - a) * 1000:.0f}ms"

    try:
        # ---- resolve voice (same permission rules as /voice-chat).
        # Belt-and-braces: even if resolution somehow raises, DEMO_MODE must
        # keep the call alive — fall back to the default Edge voice. ----
        try:
            tts_voice_id, cloned_voice_key = await resolve_voice_config(
                db,
                firebase_user,
                voice_profile_id=config.get("voice_profile_id"),
                voice_id=config.get("voice_id"),
            )
        except Exception:
            if not DEMO_MODE:
                raise
            print(
                "[voice-call] DEMO_MODE: voice resolution failed — "
                "using the default Edge voice",
                flush=True,
            )
            tts_voice_id, cloned_voice_key = None, None
        if session["cancelled"]:
            return

        audio_bytes = b"".join(chunks)
        if DEBUG_AUDIO_DIR:
            try:
                Path(DEBUG_AUDIO_DIR).mkdir(parents=True, exist_ok=True)
                name = f"utt_{int(time.time() * 1000)}_{len(audio_bytes)}.webm"
                (Path(DEBUG_AUDIO_DIR) / name).write_bytes(audio_bytes)
            except Exception as exc:
                print(f"[voice-call] debug audio dump failed: {exc}", flush=True)
        if not audio_bytes:
            await websocket.send_json({"type": "status", "state": "idle"})
            return

        # Guard: a webm/opus blob under ~8 KB is almost always ambient noise,
        # a recorder flush with no real speech, or under ~0.4 s of audio.
        # Sending it to Whisper causes hallucinations like "Thank you", "Okay",
        # or random words — the root cause of the phantom-utterance bug.
        MIN_AUDIO_BYTES = 8_000
        if len(audio_bytes) < MIN_AUDIO_BYTES:
            print(
                f"[voice-call] dropped tiny audio blob ({len(audio_bytes)} bytes "
                f"< {MIN_AUDIO_BYTES} B minimum) — likely ambient noise",
                flush=True,
            )
            await websocket.send_json({"type": "status", "state": "idle"})
            return

        # ---- transcribe (Groq cloud Whisper first — local CPU Whisper takes
        # ~40s on this machine, Groq ~3s). Falls back to local if the key is
        # missing or the request fails. Both paths receive the SAME explicit
        # language so neither can mis-detect. ----
        await websocket.send_json({"type": "status", "state": "transcribing"})
        transcript = None
        try:
            # Hard timeout: a stalled Groq request must never freeze the turn.
            transcript = await asyncio.wait_for(
                transcribe_audio_groq(audio_bytes, "recording.webm", language=lang),
                timeout=STT_GROQ_TIMEOUT_S,
            )
        except Exception as exc:
            print(f"[stt] Groq transcription error: {exc}", flush=True)
        if not transcript:
            try:
                transcript = (
                    await asyncio.wait_for(
                        transcribe_audio(
                            audio_bytes,
                            "recording.webm",
                            beam_size=1,
                            condition_on_previous_text=False,
                            language=lang,
                        ),
                        timeout=STT_LOCAL_TIMEOUT_S,
                    )
                ).strip()
            except Exception as exc:
                print(f"[stt] Local Whisper error: {exc}", flush=True)
        t_stt_done = time.perf_counter()
        if session["cancelled"]:
            return
        if not transcript:
            await websocket.send_json({"type": "status", "state": "idle"})
            return

        # Auto-lock: when the user hasn't picked a language, a single turn's
        # script guess could be WRONG (Whisper hears Telugu as Tamil), so we
        # only lock after TWO consecutive turns agree on the same script.
        # Once locked, later turns get the right hint AND the AI reply is
        # pinned to that language for the rest of the call (self-correcting).
        if not config.get("language"):
            detected = detect_language(transcript)
            if detected in ("hi", "te", "ta"):
                if session.get("prev_detected") == detected:
                    session["language_lock"] = detected
                    lang = detected
                else:
                    session["prev_detected"] = detected

        await websocket.send_json(
            {"type": "status", "state": "thinking", "transcript": transcript}
        )

        # ---- resolve saved speed/pitch BEFORE streaming: the TTS worker runs
        # WHILE the LLM generates, so these must already be known ----
        base_speed: float = 1.0
        base_pitch: float = 1.0
        try:
            user = await get_or_create_user(
                db,
                firebase_uid=firebase_user.get("uid"),
                name=display_name(firebase_user),
            )
            settings = await get_or_create_user_settings(db, user_id=user.id)
            base_speed = settings.speed
            base_pitch = settings.pitch
        except Exception:
            pass  # settings are best-effort; fall back to defaults

        # ---- stream the LLM reply; synthesize each completed sentence in a
        # background worker so playback starts while the LLM keeps generating ----
        emotion = "neutral"
        fresh_start = False
        tokens: list[str] = []
        sentence_buf = ""
        t_first_token: float | None = None
        t_first_sentence: float | None = None
        t_first_audio: float | None = None
        fallback_notified = False
        sentence_queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def synthesize_and_send(sentence: str) -> None:
            """TTS one sentence with the resolved voice and stream it back."""
            nonlocal t_first_audio, fallback_notified
            # Saved speed/pitch + a subtle mood nudge (like /voice-chat).
            s_speed, s_pitch = emotion_voice_params(emotion, base_speed, base_pitch)
            # Per-sentence script detection: mixed-language replies pick the
            # right voice/phonemes sentence-by-sentence.
            s_lang = detect_language(sentence)

            if DEMO_MODE:
                # Demo mode: Edge TTS only — fast, reliable, free.
                # Cloned voices route here too, so "My Voice" stays selectable
                # but can never fail live (cloning runs locally on GPU; this
                # is the lighter demo-stability fallback).
                try:
                    audio_data, mime_type = await synthesize_speech(
                        sentence,
                        voice_id=tts_voice_id,
                        speed=s_speed,
                        pitch=s_pitch,
                        language=s_lang,
                    )
                except Exception as exc:
                    # One quiet retry with the explicit default voice — a
                    # transient Edge TTS hiccup must not lose a sentence.
                    print(
                        f"[voice-call] DEMO_MODE Edge TTS failed "
                        f"({type(exc).__name__}: {exc}) — retrying once",
                        flush=True,
                    )
                    await asyncio.sleep(0.25)
                    audio_data, mime_type = await synthesize_speech(
                        sentence,
                        voice_id=None,
                        speed=s_speed,
                        pitch=s_pitch,
                        language=s_lang,
                    )
            elif cloned_voice_key is not None:
                # Chatterbox preferred (500M model, 23+ languages);
                # XTTS v2 fallback for unsupported languages (te/ta) or failures.
                try:
                    if chatterbox_engine_available():
                        audio_data, mime_type = await chatterbox_synthesize_cloned_voice(
                            sentence, cloned_voice_key, language=s_lang, speed=s_speed
                        )
                    else:
                        audio_data, mime_type = await xtts_synthesize_cloned_voice(
                            sentence, cloned_voice_key, language=s_lang, speed=s_speed
                        )
                except (
                    VoiceCloneUnavailableError,
                    ChatterboxCloneUnavailableError,
                    ChatterboxSynthesisError,
                    XTTSVoiceSynthesisError,
                ) as exc:
                    print(
                        f"[CHATTERBOX_SYNTHESIS_FAILURE] {type(exc).__name__}: {exc!r}",
                        flush=True,
                    )
                    # NEVER swap voices silently — runtime failures were already
                    # retried + tagged-logged server-side ([OMNIVOICE|XTTS]_SYNTHESIS_
                    # FAILURE). Tell the client once, then use the free default
                    # voice so the turn still produces audio.
                    if not fallback_notified:
                        fallback_notified = True
                        print(
                            "[voice-call] cloned voice unavailable this turn → "
                            "default voice fallback (client notified)",
                            flush=True,
                        )
                        await send_voice_fallback_notice(websocket)
                    audio_data, mime_type = await synthesize_speech(
                        sentence,
                        voice_id=None,
                        speed=s_speed,
                        pitch=s_pitch,
                        language=s_lang,
                    )
            else:
                audio_data, mime_type = await synthesize_speech(
                    sentence,
                    voice_id=tts_voice_id,
                    speed=s_speed,
                    pitch=s_pitch,
                    language=s_lang,
                )

            if session["cancelled"]:
                raise _TurnCancelled()
            if t_first_audio is None:
                t_first_audio = time.perf_counter()
            await websocket.send_json(
                {
                    "type": "audio",
                    "audio_base64": audio_to_base64(audio_data),
                    "mime": mime_type,
                }
            )

        async def tts_worker() -> None:
            while True:
                sentence = await sentence_queue.get()
                if sentence is None:
                    return
                try:
                    await synthesize_and_send(sentence)
                except _TurnCancelled:
                    return  # barged in mid-turn — stop quietly
                except Exception as exc:
                    # One bad sentence must not kill the rest of the reply.
                    print(
                        f"[voice-call] sentence TTS failed ({type(exc).__name__}): {exc}",
                        flush=True,
                    )

        def enqueue_sentence(sentence: str) -> None:
            nonlocal t_first_sentence
            if t_first_sentence is None:
                t_first_sentence = time.perf_counter()
            sentence_queue.put_nowait(sentence)

        worker_task = asyncio.create_task(tts_worker())

        try:
            async for kind, value in stream_chat_reply(
                db,
                firebase_user=firebase_user,
                message=transcript,
                personality=config.get("personality"),
                source="call",
                fast_emotion=True,  # skip the extra Groq emotion round-trip in calls
                language=lang,
            ):
                if session["cancelled"]:
                    raise _TurnCancelled()
                if kind == "emotion":
                    emotion = value
                elif kind == "fresh_start":
                    fresh_start = True
                else:
                    if t_first_token is None:
                        t_first_token = time.perf_counter()
                    tokens.append(value)
                    await websocket.send_json({"type": "token", "content": value})

                    # Hand every COMPLETE sentence to the TTS worker immediately;
                    # synthesis overlaps the remaining LLM generation.
                    sentence_buf += value
                    while True:
                        match = _SENTENCE_SPLIT_RE.search(sentence_buf)
                        if match is None:
                            break
                        candidate = sentence_buf[: match.end()].strip()
                        sentence_buf = sentence_buf[match.end():]
                        if candidate:
                            enqueue_sentence(candidate)
                    # Force-cut pathological run-on text so no single queued
                    # chunk grows unbounded while waiting for punctuation.
                    if len(sentence_buf) > 200:
                        cut = sentence_buf.rfind(" ", 100, 200)
                        if cut > 0:
                            candidate = sentence_buf[:cut].strip()
                            sentence_buf = sentence_buf[cut:].lstrip()
                            if candidate:
                                enqueue_sentence(candidate)

            # Flush what's left after the final token (split_sentences also
            # hard-cuts overlong remainders at word boundaries).
            tail = sentence_buf.strip()
            if tail:
                for piece in split_sentences(tail):
                    if piece:
                        enqueue_sentence(piece)
        except _TurnCancelled:
            worker_task.cancel()
            raise  # client hung up mid-reply — drop the turn silently
        except Exception as exc:
            # The LLM stream failed (Groq outage/timeout, DB hiccup…). Never
            # surface a raw error mid-call: if nothing has been said yet, speak
            # a short canned recovery line through Edge TTS so the turn still
            # produces audio; otherwise finish with whatever already streamed.
            print(
                f"[voice-call] LLM stream failed ({type(exc).__name__}): {exc}",
                flush=True,
            )
            if not tokens:
                tokens.append(LLM_FALLBACK_REPLY)
                try:
                    await websocket.send_json(
                        {"type": "token", "content": LLM_FALLBACK_REPLY}
                    )
                except Exception:
                    pass  # socket gone — the reply just isn't shown
                for piece in split_sentences(LLM_FALLBACK_REPLY):
                    if piece:
                        enqueue_sentence(piece)
        except BaseException:
            worker_task.cancel()
            raise

        # Drain remaining queued sentences BEFORE "done" so audio frames always
        # precede the frame that arms the client's post-reply VAD cooldown.
        await sentence_queue.put(None)
        await worker_task

        t_done = time.perf_counter()
        reply = "".join(tokens).strip()

        print(
            "[voice-call timing] "
            f"user_audio→stt_done={_ms(t_audio_received, t_stt_done)} | "
            f"stt→first_llm_token={_ms(t_stt_done, t_first_token)} | "
            f"first_llm_token→first_sentence={_ms(t_first_token, t_first_sentence)} | "
            f"first_sentence→first_audio_sent={_ms(t_first_sentence, t_first_audio)} | "
            f"E2E user_audio→first_audio={_ms(t_audio_received, t_first_audio)} | "
            f"total_turn={_ms(t_audio_received, t_done)}",
            flush=True,
        )

        if not reply:
            await websocket.send_json(
                {
                    "type": "done",
                    "emotion": emotion,
                    "fresh_start": fresh_start,
                    "notice": None,
                }
            )
            return

        await websocket.send_json(
            {
                "type": "done",
                "emotion": emotion,
                "fresh_start": fresh_start,
                "notice": CONVERSATION_LIMIT_NOTICE if fresh_start else None,
            }
        )
    except _TurnCancelled:
        pass  # client hung up mid-reply — drop the turn silently
    except HTTPException as exc:
        try:
            if DEMO_MODE:
                # Never surface setup errors mid-demo — just keep listening.
                print(f"[voice-call] DEMO_MODE: turn error ({exc.detail}) — back to listening", flush=True)
                await websocket.send_json({"type": "status", "state": "idle"})
            else:
                await websocket.send_json({"type": "error", "detail": exc.detail})
        except Exception:
            pass
    except WebSocketDisconnect:
        pass  # connection gone — clean up silently, don't send over dead socket
    except Exception as exc:
        print(f"[voice-call] turn failed: {exc}", flush=True)
        try:
            if DEMO_MODE:
                # The demo must never show "Something went wrong" on stage.
                # Fall back to listening; the user simply speaks again.
                await websocket.send_json({"type": "status", "state": "idle"})
            else:
                await websocket.send_json(
                    {"type": "error", "detail": "Something went wrong during the call."}
                )
        except Exception:
            pass


async def handle_voice_call(websocket: WebSocket, db, firebase_user: dict) -> None:
    """Main WebSocket loop — accepts a config, buffers audio, runs turns.

    The connection is already accepted by the caller (so auth failures can be
    reported before this runs). One turn at a time; turns run as background
    tasks so a "cancel" can interrupt a reply mid-stream.
    """
    session: dict = {
        "config": None,
        "chunks": [],
        "cancelled": False,
        "turn_task": None,
        "language_lock": None,
        "prev_detected": None,
    }

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            data = message.get("text") if message["type"] == "websocket.receive" else None
            if data is None:
                data = message.get("bytes")

            if isinstance(data, bytes):
                # Buffer EVERY chunk — even while a turn is running. In the
                # hands-free call the client only streams audio while its VAD
                # hears the user, so chunks that arrive mid-reply belong to the
                # NEXT utterance (the user interrupted — barge-in).
                if session["config"] is not None:
                    session["chunks"].append(data)
                continue

            if not isinstance(data, str):
                continue

            try:
                payload = json.loads(data)
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue

            kind = payload.get("type")
            if kind == "config":
                session["config"] = {
                    "voice_profile_id": payload.get("voice_profile_id"),
                    "voice_id": payload.get("voice_id"),
                    "personality": payload.get("personality"),
                    "language": payload.get("language"),
                }
                # A turn is in flight — defer the (DB-backed) voice check until
                # the turn starts; _handle_turn resolves the latest config and
                # re-uses this same AsyncSession (never two DB users at once).
                if session["turn_task"] is not None:
                    continue
                # Resolve the voice up-front so permission problems surface
                # immediately instead of after the user has spoken.
                try:
                    await resolve_voice_config(
                        db,
                        firebase_user,
                        voice_profile_id=session["config"]["voice_profile_id"],
                        voice_id=session["config"]["voice_id"],
                    )
                    await websocket.send_json({"type": "ready"})
                except HTTPException as exc:
                    if not DEMO_MODE:
                        await websocket.send_json({"type": "error", "detail": exc.detail})
                        break
                    # DEMO_MODE: a voice that can't be resolved must not kill
                    # the call — the turn speaks with the default Edge voice.
                    print(
                        f"[voice-call] DEMO_MODE: config voice unavailable "
                        f"({exc.detail}) — default Edge voice will be used",
                        flush=True,
                    )
                    await websocket.send_json({"type": "ready"})
            elif kind == "end_utterance":
                if session["config"] is None:
                    continue
                # A previous turn may still be winding down (barge-in): abort it
                # and wait for it to finish — turns share one DB session, so
                # they must never overlap. Audio keeps flowing into the buffer
                # while we wait, so nothing of the new utterance is lost.
                if session["turn_task"] is not None:
                    session["cancelled"] = True
                    while session["turn_task"] is not None:
                        try:
                            msg = await asyncio.wait_for(
                                websocket.receive(), timeout=0.05
                            )
                        except asyncio.TimeoutError:
                            continue
                        if msg["type"] == "websocket.disconnect":
                            raise WebSocketDisconnect()
                        data = msg.get("bytes") if msg["type"] == "websocket.receive" else None
                        if isinstance(data, bytes):
                            session["chunks"].append(data)
                chunks = session["chunks"]
                session["chunks"] = []  # own the audio so later turns start clean
                if not chunks:
                    continue
                session["cancelled"] = False
                session["turn_task"] = asyncio.create_task(
                    _handle_turn(websocket, db, firebase_user, session, chunks)
                )
                session["turn_task"].add_done_callback(
                    lambda _t: session.update(turn_task=None)
                )
            elif kind == "cancel":
                # Abort the in-flight reply AND drop the audio buffered so far
                # (the tail of the interrupted utterance). Chunks that arrive
                # AFTER this message belong to the user's next utterance.
                session["cancelled"] = True
                session["chunks"] = []
            elif kind == "discard":
                # The client decided the captured audio was noise/too short —
                # drop it without starting a reply.
                session["chunks"] = []
            elif kind == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[voice-call] connection error: {exc}", flush=True)
    finally:
        session["cancelled"] = True
        task = session["turn_task"]
        if task is not None and not task.done():
            task.cancel()
