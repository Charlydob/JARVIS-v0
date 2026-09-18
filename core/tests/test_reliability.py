import base64
import logging
from datetime import datetime
from pathlib import Path

import pytest

from jarvis_core.config import CoreSettings
from jarvis_core.services import JarvisServices
from jarvis_core.tools import Tool


@pytest.mark.asyncio
async def test_exact_reminder_create_resumes_pending_hour_and_executes_once(tmp_path: Path, caplog, monkeypatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = datetime(2026, 9, 18, 8, 30)
            return fixed.replace(tzinfo=tz) if tz else fixed

    monkeypatch.setattr("jarvis_core.services.datetime", FixedDateTime)
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    writes: list[dict] = []

    async def create_reminder(arguments):
        writes.append(dict(arguments))
        return {"created": True, "verified": True, "reminder": {"id": "r1", **arguments}}

    services.tools.register(Tool(
        "bookshell_create_reminder", "create", {"type": "object"}, create_reminder,
    ))
    async def fake_stream(_messages, _context=None):
        yield "No hay ninguna acción pendiente, señor."
    services.ollama.chat_stream = fake_stream
    chunks: list[str] = []

    async def collect(chunk: str) -> None:
        chunks.append(chunk)

    caplog.set_level(logging.INFO, logger="jarvis-core.tools")
    first = await services.chat_stream({
        "message": "¿Podrías añadir como recordatorio hoy que tengo clase de alemán?",
        "conversation_id": "exact-reminder-flow", "turn_id": "exact-reminder-turn-1",
    }, collect)
    second = await services.chat_stream({
        "message": "A las seis.",
        "conversation_id": "exact-reminder-flow", "turn_id": "exact-reminder-turn-2",
    }, collect)
    await services.chat_stream({
        "message": "A las seis.",
        "conversation_id": "exact-reminder-flow", "turn_id": "exact-reminder-turn-3",
    }, collect)

    assert first["message"] == "¿A qué hora, señor?"
    assert second["message"] == "Recordatorio creado, señor."
    assert len(writes) == 1
    assert writes[0]["title"] == "clase de alemán"
    assert writes[0]["target_time"] == "18:00"
    assert writes[0]["idempotency_key"]
    assert "route_domain=reminders route_operation=create" in caplog.text
    assert "missing_fields=time pending_action_created=true" in caplog.text
    assert "pending_action_resumed=true" in caplog.text
    assert "tool=bookshell.reminders.create" in caplog.text
    assert "tool_success=true verification_success=true" in caplog.text


@pytest.mark.asyncio
async def test_complete_new_intent_cancels_incompatible_pending_action(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))

    async def books_query(_arguments):
        return {"found": True, "book": {"title": "Musashi", "currentPage": 33, "pages": 575}}

    services.tools.register(Tool("bookshell_books_query", "query", {"type": "object"}, books_query))

    async def collect(_chunk: str) -> None:
        return None

    first = await services.chat_stream({
        "message": "Crea un recordatorio para hoy", "conversation_id": "pending-switch",
        "turn_id": "pending-switch-1",
    }, collect)
    second = await services.chat_stream({
        "message": "¿Qué libro estoy leyendo?", "conversation_id": "pending-switch",
        "turn_id": "pending-switch-2",
    }, collect)

    assert first["message"] == "¿A qué hora, señor?"
    assert "Musashi" in second["message"]
    assert "pending-switch" not in services._pending_intents


@pytest.mark.asyncio
async def test_silence_and_duplicate_utterance_are_discarded_before_ollama(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    payload = {
        "data": base64.b64encode(b"x" * 2000).decode(), "content_type": "audio/webm",
        "duration_ms": 300, "speech_ms": 100, "max_rms": .005,
        "utterance_id": "utterance-silence-1", "conversation_id": "conversation-1",
    }
    first = await services.dispatch("audio", payload)
    second = await services.dispatch("audio", payload)
    assert first["transcript"] == ""
    assert first["discard_reason"] == "audio_too_short"
    assert second == first


@pytest.mark.asyncio
async def test_repeated_transcript_is_discarded_with_new_audio_id(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))

    async def fake_transcribe(_raw, _content_type):
        return "Hola Jarvis", "es", {"language_probability": .99, "decoded_duration_s": 1, "duration_after_vad_s": 1}

    services.stt.transcribe = fake_transcribe
    base = {
        "data": base64.b64encode(b"x" * 2000).decode(), "content_type": "audio/webm",
        "duration_ms": 1500, "speech_ms": 800, "max_rms": .05, "conversation_id": "conversation-1",
    }
    first = await services.dispatch("audio", {**base, "utterance_id": "utterance-1"})
    second = await services.dispatch("audio", {**base, "utterance_id": "utterance-2"})
    assert first["transcript"] == "Hola Jarvis"
    assert second["transcript"] == ""
    assert second["discard_reason"] == "duplicate_transcript"


@pytest.mark.asyncio
async def test_repeated_phrases_inside_one_utterance_are_collapsed(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))

    async def fake_transcribe(_raw, _content_type):
        return (
            "A las cinco y media, Jarvis. A las cinco y media. A las cinco y media.",
            "es", {"language_probability": .99, "decoded_duration_s": 4, "duration_after_vad_s": 4},
        )

    services.stt.transcribe = fake_transcribe
    result = await services.dispatch("audio", {
        "data": base64.b64encode(b"x" * 3000).decode(), "content_type": "audio/webm",
        "duration_ms": 4500, "speech_ms": 3000, "max_rms": .05,
        "utterance_id": "utterance-repeated-phrases", "conversation_id": "conversation-repeat",
    })
    assert result["transcript"] == "A las cinco y media, Jarvis."


@pytest.mark.asyncio
async def test_duplicate_turn_executes_write_once_and_twenty_turns_have_no_phantoms(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    state = {"page": 221, "writes": 0, "reminders": []}

    async def books_query(_arguments):
        return {"found": True, "book": {"title": "Musashi", "currentPage": state["page"], "pages": 575}}

    async def update_page(arguments):
        state["page"] = int(arguments["page"]); state["writes"] += 1
        return {"updated": True, "verified": True, "book": {"title": "Musashi", "currentPage": state["page"], "pages": 575}}

    async def reminders_query(_arguments):
        return {"items": list(state["reminders"]), "count": len(state["reminders"])}

    async def create_reminder(arguments):
        item = {"title": arguments["title"], "targetDate": arguments.get("target_date"), "targetTime": arguments["target_time"]}
        state["reminders"].append(item); state["writes"] += 1
        return {"created": True, "verified": True, "reminder": item}

    for tool in (
        Tool("bookshell_books_query", "query", {"type": "object"}, books_query),
        Tool("bookshell_update_progress", "update", {"type": "object"}, update_page),
        Tool("bookshell_reminders_query", "query", {"type": "object"}, reminders_query),
        Tool("bookshell_create_reminder", "create", {"type": "object"}, create_reminder),
    ):
        services.tools.register(tool)

    async def fake_stream(_messages, _context=None):
        yield "Estoy bien, señor."

    services.ollama.chat_stream = fake_stream

    messages = ["¿Cómo estás?"] * 16 + [
        "¿Qué libro estoy leyendo?", "¿Por qué página voy?", "Apunta página 220",
        "Recuérdame prueba el viernes a las 18:00",
    ]
    results = []
    for index, message in enumerate(messages):
        async def collect(_chunk: str) -> None:
            return None
        results.append(await services.chat_stream({"message": message, "turn_id": f"stress-turn-{index}"}, collect))

    duplicate = await services.chat_stream({"message": "Apunta página 220", "turn_id": "stress-turn-18"}, collect)
    assert len(results) == 20
    assert state["writes"] == 2
    assert duplicate["message"] == "Anotado, señor."
    assert services.storage.stats()["messages"] == 40
    assert all(result["message"] for result in results)


@pytest.mark.asyncio
async def test_dynamic_reminders_are_read_fresh_and_repair_requeries(tmp_path: Path, caplog) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    state = {"items": [
        {"id": "r1", "title": "Primero", "targetDate": "2026-09-18", "targetTime": "09:00"},
        {"id": "r2", "title": "Segundo", "targetDate": "2026-09-18", "targetTime": "10:00"},
    ], "reads": 0}

    async def reminders_query(_arguments):
        state["reads"] += 1
        return {"items": list(state["items"]), "count": len(state["items"])}

    services.tools.register(Tool(
        "bookshell_reminders_query", "query", {"type": "object"}, reminders_query,
    ))

    async def collect(_chunk: str) -> None:
        return None

    caplog.set_level(logging.INFO, logger="jarvis-core.tools")
    first = await services.chat_stream({
        "message": "¿Qué recordatorios tengo hoy?", "conversation_id": "fresh",
        "turn_id": "fresh-turn-1",
    }, collect)
    second = await services.chat_stream({
        "message": "¿Qué recordatorios tengo hoy?", "conversation_id": "fresh",
        "turn_id": "fresh-turn-2",
    }, collect)
    state["items"].append({"id": "r3", "title": "Tercero", "targetDate": "2026-09-18", "targetTime": "11:00"})
    third = await services.chat_stream({
        "message": "Revisa bien, debería haber tres.", "conversation_id": "fresh",
        "turn_id": "fresh-turn-3",
    }, collect)
    state["items"].pop(0)
    fourth = await services.chat_stream({
        "message": "¿Qué recordatorios tengo hoy?", "conversation_id": "fresh",
        "turn_id": "fresh-turn-4",
    }, collect)

    assert state["reads"] == 4
    assert "Primero" in first["message"] and "Segundo" in second["message"]
    assert "Tercero" in third["message"]
    assert "Primero" not in fourth["message"] and "Tercero" in fourth["message"]
    assert "repair_route=true force_fresh=true" in caplog.text


@pytest.mark.asyncio
async def test_missing_tool_reports_real_registry_state(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))

    async def collect(_chunk: str) -> None:
        return None

    result = await services.chat_stream({
        "message": "¿Qué recordatorios tengo hoy?", "turn_id": "missing-tool-turn",
    }, collect)

    assert "no está configurada en el Core" in result["message"]
    assert "bookshell_reminders_query" in result["message"]
