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
async def test_completed_reminder_cannot_contaminate_next_notes_turn(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    calls: list[tuple[str, dict]] = []

    async def reminder(arguments):
        calls.append(("reminder", dict(arguments)))
        return {"created": True, "verified": True, "reminder": {"id": "r1"}}

    async def note(arguments):
        calls.append(("note", dict(arguments)))
        return {
            "created": True, "verified": True, "id": "n1",
            "note": {"id": "n1", "title": arguments["title"], "content": arguments.get("content", "")},
        }

    services.tools.register(Tool("bookshell_create_reminder", "create", {"type": "object"}, reminder))
    services.tools.register(Tool("bookshell_notes_write", "write", {"type": "object"}, note))

    async def collect(_chunk: str) -> None:
        return None

    first = await services.chat_stream({
        "message": "Recuérdame mañana a las 18:00 comprar leche",
        "conversation_id": "closed-action", "turn_id": "closed-action-1",
    }, collect)
    second = await services.chat_stream({
        "message": "crea una nota Mejoras para Jarvis",
        "conversation_id": "closed-action", "turn_id": "closed-action-2",
    }, collect)
    assert first["message"] == "Recordatorio creado, señor."
    assert second["message"] == "Hecho y verificado en BookShell, señor."
    assert [name for name, _ in calls] == ["reminder", "note"]


@pytest.mark.asyncio
async def test_last_jarvis_message_is_appended_and_internal_json_is_blocked(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    captured: list[dict] = []

    async def note(arguments):
        captured.append(dict(arguments))
        return {"updated": True, "verified": True, "id": "bugs", "note": {"id": "bugs", "title": "Bugs de Jarvis"}}

    services.tools.register(Tool("bookshell_notes_write", "write", {"type": "object"}, note))
    responses = iter(["Mensaje anterior de JARVIS", '{"name":"bookshell_notes_write","parameters":{"action":"create"}}'])

    async def fake_stream(_messages, _context=None):
        yield next(responses)

    services.ollama.chat_stream = fake_stream
    chunks: list[str] = []

    async def collect(chunk: str) -> None:
        chunks.append(chunk)

    await services.chat_stream({
        "message": "dime algo", "conversation_id": "last-message", "turn_id": "last-message-1",
    }, collect)
    saved = await services.chat_stream({
        "message": "anota este último mensaje en la nota Bugs de Jarvis",
        "conversation_id": "last-message", "turn_id": "last-message-2",
    }, collect)
    leaked = await services.chat_stream({
        "message": "otra cosa", "conversation_id": "last-message", "turn_id": "last-message-3",
    }, collect)
    assert captured[0]["append_content"] == "Mensaje anterior de JARVIS"
    assert saved["message"] == "Hecho y verificado en BookShell, señor."
    assert leaked["message"] == "No he podido ejecutar correctamente esa herramienta, señor."
    assert not any('"parameters"' in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_web_search_capability_is_reported_from_registry(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))

    async def collect(_chunk: str) -> None:
        return None

    result = await services.chat_stream({
        "message": "búscalo en Internet", "turn_id": "web-missing-1",
    }, collect)
    assert result["message"] == "La búsqueda web no está disponible ahora mismo, señor."


@pytest.mark.asyncio
async def test_exact_checklist_sequence_always_uses_real_notes_tools(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    note = {"id": "check-1", "title": "mejoras para Jarvis", "content": "", "tags": ["checklist"]}
    calls: list[tuple[str, dict]] = []

    async def write(arguments):
        calls.append(("write", dict(arguments)))
        if arguments["action"] == "create":
            return {"created": True, "verified": True, "id": note["id"], "note": dict(note)}
        if arguments.get("append_content"):
            note["content"] = "\n".join(filter(None, [note["content"], arguments["append_content"]]))
        if arguments.get("check_item"):
            note["content"] = note["content"].replace("- [ ] mejorar STT", "- [x] mejorar STT")
        return {"updated": True, "verified": True, "id": note["id"], "note": dict(note)}

    async def query(arguments):
        calls.append(("query", dict(arguments)))
        return {"items": [dict(note)], "pendingItems": [{"item": "wake word"}], "count": 1}

    services.tools.register(Tool("bookshell_notes_write", "write", {"type": "object"}, write))
    services.tools.register(Tool("bookshell_notes_query", "query", {"type": "object"}, query))

    async def no_llm(*_args, **_kwargs):
        raise AssertionError("clear checklist CRUD must not call Ollama")

    services.ollama.chat_stream = no_llm

    async def collect(_chunk: str) -> None:
        return None

    prompts = [
        "crea un checklist llamado mejoras para Jarvis",
        "añade mejorar STT y wake word",
        "marca mejorar STT como hecho",
        "qué queda",
    ]
    results = []
    for index, prompt in enumerate(prompts):
        results.append(await services.chat_stream({
            "message": prompt, "conversation_id": "real-checklist", "turn_id": f"real-checklist-{index}",
        }, collect))
    assert [name for name, _ in calls] == ["write", "write", "write", "query"]
    assert calls[1][1]["append_content"] == "- [ ] mejorar STT\n- [ ] wake word"
    assert "wake word" in results[-1]["message"]
    assert all(result["message"] for result in results)


@pytest.mark.asyncio
async def test_exact_folder_phrase_queries_then_creates_real_folder(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    calls: list[tuple[str, dict]] = []

    async def query(arguments):
        calls.append(("query", dict(arguments)))
        return {"items": [], "count": 0}

    async def create(arguments):
        calls.append(("create", dict(arguments)))
        return {
            "created": True, "verified": True, "id": "folder-1",
            "folder": {"id": "folder-1", "name": arguments["name"]},
        }

    services.tools.register(Tool("bookshell_notes_folder_query", "query", {"type": "object"}, query))
    services.tools.register(Tool("bookshell_notes_folder_create", "create", {"type": "object"}, create))

    async def collect(_chunk: str) -> None:
        return None

    result = await services.chat_stream({
        "message": "crea una carpeta en notas llamada mejora para Jarvis",
        "turn_id": "real-folder-1",
    }, collect)
    assert calls == [
        ("query", {"query": "mejora para Jarvis", "limit": 10}),
        ("create", {"name": "mejora para Jarvis"}),
    ]
    assert result["message"] == "La carpeta mejora para Jarvis se ha creado y verificado en BookShell, señor."


@pytest.mark.asyncio
async def test_exact_april_reminder_resumes_same_pending_action(tmp_path: Path, monkeypatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = datetime(2026, 9, 20, 12, 0)
            return fixed.replace(tzinfo=tz) if tz else fixed

    monkeypatch.setattr("jarvis_core.services.datetime", FixedDateTime)
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    writes: list[dict] = []

    async def create(arguments):
        writes.append(dict(arguments))
        return {"created": True, "verified": True, "reminder": {"id": "birthday", **arguments}}

    services.tools.register(Tool("bookshell_create_reminder", "create", {"type": "object"}, create))

    async def collect(_chunk: str) -> None:
        return None

    first = await services.chat_stream({
        "message": "crea recordatorio para el 12 de abril llamado mi cumpleaños",
        "conversation_id": "birthday", "turn_id": "birthday-1",
    }, collect)
    second = await services.chat_stream({
        "message": "a las diez de la mañana", "conversation_id": "birthday", "turn_id": "birthday-2",
    }, collect)
    assert first["message"] == "¿A qué hora, señor?"
    assert second["message"] == "Recordatorio creado, señor."
    assert len(writes) == 1
    assert writes[0]["title"] == "mi cumpleaños"
    assert writes[0]["target_date"] == "2027-04-12"
    assert writes[0]["target_time"] == "10:00"


@pytest.mark.asyncio
async def test_pc_url_capability_and_fast_turns_are_deterministic(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    opened: list[str] = []

    async def open_url(arguments):
        opened.append(arguments["url"])
        return {"opened": True, "verified": True, "url": arguments["url"]}

    services.tools.register(Tool("pc_open_url", "open", {"type": "object"}, open_url))
    feedback_calls = 0

    async def feedback(_message):
        nonlocal feedback_calls
        feedback_calls += 1
        return "irrelevant"

    services.feedback.context_for = feedback

    async def fake_stream(_messages, _context=None):
        yield "A su servicio, señor."

    services.ollama.chat_stream = fake_stream

    async def collect(_chunk: str) -> None:
        return None

    capability = await services.chat_stream({"message": "¿tienes internet?", "turn_id": "capability-1"}, collect)
    search = await services.chat_stream({"message": "búscame la página de Wikipedia de Lovecraft", "turn_id": "search-1"}, collect)
    opened_result = await services.chat_stream({"message": "abre https://es.wikipedia.org/ en el ordenador", "turn_id": "open-1"}, collect)
    wake = await services.chat_stream({"message": "JARVIS", "turn_id": "wake-1"}, collect)
    assert "puedo abrir URLs" in capability["message"] and "no tengo búsqueda web general" in capability["message"]
    assert search["message"] == "La búsqueda web no está disponible ahora mismo, señor."
    assert opened_result["message"] == "Fuente abierta en el navegador, señor."
    assert opened == ["https://es.wikipedia.org/"]
    assert wake["message"] == "A su servicio, señor."
    assert feedback_calls == 0


@pytest.mark.asyncio
async def test_fast_path_cannot_claim_external_success_without_tool(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))

    async def fake_stream(_messages, _context=None):
        yield "Hecho, guardado y completado con éxito."

    services.ollama.chat_stream = fake_stream
    chunks: list[str] = []

    async def collect(chunk: str) -> None:
        chunks.append(chunk)

    result = await services.chat_stream({"message": "guarda esto en el sistema", "turn_id": "no-tool-success-1"}, collect)
    assert result["message"] == "No he ejecutado esa acción porque no hay una herramienta adecuada seleccionada, señor."
    assert chunks == [result["message"]]


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


@pytest.mark.asyncio
async def test_unrelated_short_transcript_never_reuses_previous_tool_route(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    reads = 0

    async def reminders_query(_arguments):
        nonlocal reads
        reads += 1
        return {"items": [{"title": "Guardia Laura"}], "count": 1, "range": "today"}

    async def plain_chat(_messages, _context=None):
        yield "No he entendido esa petición."

    services.tools.register(Tool(
        "bookshell_reminders_query", "query", {"type": "object"}, reminders_query,
    ))
    services.ollama.chat_stream = plain_chat

    async def collect(_chunk: str) -> None:
        return None

    conversation_id = "short-transcript-does-not-repeat"
    await services.chat_stream({
        "message": "¿Qué recordatorios tengo hoy?", "conversation_id": conversation_id,
        "turn_id": "short-route-turn-1",
    }, collect)
    second = await services.chat_stream({
        "message": "¡Suscríbete!", "conversation_id": conversation_id,
        "turn_id": "short-route-turn-2",
    }, collect)

    assert reads == 1
    assert second["message"] == "No he entendido esa petición."


@pytest.mark.asyncio
async def test_reminder_delete_searches_then_verifies_one_candidate(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    calls: list[tuple[str, dict]] = []

    async def query(arguments):
        calls.append(("query", dict(arguments)))
        return {"items": [{"id": "apple-1", "title": "Llega el paquete de Apple", "targetDate": "2026-09-21"}], "count": 1}

    async def update(arguments):
        calls.append(("update", dict(arguments)))
        return {"updated": True, "verified": True, "reminder": {"id": "apple-1", "status": "cancelled"}}

    services.tools.register(Tool("bookshell_reminders_query", "query", {"type": "object"}, query))
    services.tools.register(Tool("bookshell_reminder_update", "update", {"type": "object"}, update))

    async def collect(_chunk: str) -> None:
        return None

    result = await services.chat_stream({
        "message": "Elimina el recordatorio del paquete de Apple",
        "conversation_id": "delete-reminder", "turn_id": "delete-reminder-turn",
    }, collect)
    assert result["message"] == "Recordatorio eliminado, señor."
    assert calls[0][0] == "query" and calls[0][1]["query"] == "paquete de Apple"
    assert calls[1] == ("update", {"reminder_id": "apple-1", "action": "cancel", "confirmed": True})
    assert "delete-reminder" not in services._pending_intents


@pytest.mark.asyncio
async def test_reminder_delete_accepts_clear_apple_stt_variant(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    cancelled: list[str] = []

    async def query(_arguments):
        return {"items": [{"id": "apple-1", "title": "Llega el paquete de Apple"}], "count": 1}

    async def update(arguments):
        cancelled.append(arguments["reminder_id"])
        return {"updated": True, "verified": True}

    services.tools.register(Tool("bookshell_reminders_query", "query", {"type": "object"}, query))
    services.tools.register(Tool("bookshell_reminder_update", "update", {"type": "object"}, update))

    async def collect(_chunk: str) -> None:
        return None

    result = await services.chat_stream({
        "message": "elimina el recordatorio del paquete de apel", "turn_id": "delete-apel-1",
    }, collect)
    assert result["message"] == "Recordatorio eliminado, señor."
    assert cancelled == ["apple-1"]


@pytest.mark.asyncio
async def test_guardia_dates_survive_render_and_contextual_followup_requeries(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    reads: list[dict] = []

    async def query(arguments):
        reads.append(dict(arguments))
        return {"items": [
            {"id": "g1", "title": "Guardia Laura", "targetDate": "2026-09-24", "status": "pending"},
            {"id": "g2", "title": "Guardia Laura", "targetDate": "2026-09-27", "status": "pending"},
        ], "count": 2, "range": "custom"}

    services.tools.register(Tool("bookshell_reminders_query", "query", {"type": "object"}, query))

    async def collect(_chunk: str) -> None:
        return None

    first = await services.chat_stream({
        "message": "¿Cuándo tiene Laura guardia?", "conversation_id": "guardias",
        "turn_id": "guardias-1",
    }, collect)
    second = await services.chat_stream({
        "message": "¿Pero qué días?", "conversation_id": "guardias",
        "turn_id": "guardias-2",
    }, collect)

    assert "24 y el 27 de septiembre" in first["message"]
    assert "24 y el 27 de septiembre" in second["message"]
    assert len(reads) == 2
    assert reads[1]["event_type"] == "guardia" and reads[1]["person"] == "laura"
