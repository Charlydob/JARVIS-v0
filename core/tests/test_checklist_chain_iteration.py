import asyncio
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from jarvis_core.config import CoreSettings
from jarvis_core.intents import repair_direct_intent, route_direct_intent
from jarvis_core.services import JarvisServices, render_weather_forecast
from jarvis_core.tools import Tool, ToolRegistry


def test_shared_name_parser_and_reminder_stopwords() -> None:
    checklist = route_direct_intent("crea un checklist que se llame Mejoras", date(2026, 9, 21))
    assert checklist is not None
    assert checklist.arguments["title"] == "Mejoras"
    reminder = route_direct_intent("Oye, ¿tengo algo para mañana?", date(2026, 9, 21))
    assert reminder is not None
    assert reminder.arguments == {"scope": "tomorrow"}
    today = route_direct_intent("hoy tengo recordatorios", date(2026, 9, 21))
    assert today is not None and today.arguments == {"scope": "today"}


def test_reminder_repair_overlays_explicit_today() -> None:
    now = datetime(2026, 9, 21, 12, tzinfo=ZoneInfo("Europe/Madrid"))
    repaired = repair_direct_intent(
        "Oye, ¿tengo algo para mañana?", "No, perdona, quería decir hoy", now.date(), now,
    )
    assert repaired is not None
    assert repaired.arguments == {"scope": "today"}


def test_tool_argument_types_are_normalized_before_validation() -> None:
    captured = {}

    async def handler(arguments):
        captured.update(arguments)
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(Tool("typed", "typed", {"type": "object", "properties": {
        "pending_only": {"type": "boolean"}, "limit": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}}, "optional": {"type": "string"},
    }}, handler))
    asyncio.run(registry.execute("typed", {
        "pending_only": "false", "limit": "1", "tags": "['mejoras']", "optional": "undefined",
    }))
    assert captured == {"pending_only": False, "limit": 1, "tags": ["mejoras"]}


def test_weather_formatter_is_brief_natural_and_omits_irrelevant_wind() -> None:
    answer = render_weather_forecast({
        "available": True, "scope": "tomorrow", "days": [{
            "weather_code": 0, "temperature_2m_min": 9.4, "temperature_2m_max": 21.2,
            "precipitation_sum": 0, "precipitation_probability_max": 0,
            "wind_speed_10m_max": 8.7,
        }],
    })
    assert "Mañana estará despejado" in answer
    assert "entre los 9 y los 21 grados" in answer
    assert "No se espera lluvia" in answer
    assert "viento" not in answer


def _checklist_services(tmp_path: Path, titles: list[str] | None = None):
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    notes = {
        f"id-{index}": {"id": f"id-{index}", "title": title, "content": "", "tags": ["checklist"]}
        for index, title in enumerate(titles or ["Mejoras"], 1)
    }
    calls: list[tuple[str, dict]] = []

    async def query(arguments):
        calls.append(("query", dict(arguments)))
        return {"items": [dict(note) for note in notes.values()], "count": len(notes)}

    async def write(arguments):
        calls.append(("write", dict(arguments)))
        note = notes[arguments["note_id"]]
        if arguments.get("append_content"):
            note["content"] = "\n".join(filter(None, [note["content"], arguments["append_content"]]))
        return {"updated": True, "verified": True, "id": note["id"], "note": dict(note)}

    services.tools.register(Tool("bookshell_notes_query", "query", {"type": "object"}, query))
    services.tools.register(Tool("bookshell_notes_write", "write", {"type": "object"}, write))
    return services, notes, calls


@pytest.mark.asyncio
async def test_explicit_checklist_identity_uses_real_query_and_uuid_after_unrelated_turn(tmp_path: Path) -> None:
    services, notes, calls = _checklist_services(tmp_path)

    async def chat(_messages, _context=None):
        yield "Conversación intermedia."

    services.ollama.chat_stream = chat
    collect = lambda _chunk: asyncio.sleep(0)
    exists = await services.chat_stream({
        "message": "Jarvis confírmame si existe el checklist Mejoras Jarvis",
        "conversation_id": "identity", "turn_id": "identity-0001",
    }, collect)
    assert "Sí, existe" in exists["message"]
    await services.chat_stream({
        "message": "cuéntame algo breve", "conversation_id": "identity", "turn_id": "identity-0002",
    }, collect)
    await services.chat_stream({
        "message": "añade al checklist Mejoras revisar el icono",
        "conversation_id": "identity", "turn_id": "identity-0003",
    }, collect)
    assert calls[-2] == ("query", {"limit": 50})
    assert calls[-1][0] == "write"
    assert calls[-1][1] == {"action": "update", "note_id": "id-1", "append_content": "- [ ] revisar el icono"}
    assert notes["id-1"]["content"] == "- [ ] revisar el icono"
    await services.chat_stream({
        "message": "añade revisar el contraste al checklist Mejoras",
        "conversation_id": "identity", "turn_id": "identity-0003b",
    }, collect)
    assert notes["id-1"]["content"].endswith("- [ ] revisar el contraste")
    await services.chat_stream({
        "message": "añade mejoras el cambiar el icono de la pw a",
        "conversation_id": "identity-2", "turn_id": "identity-0004",
    }, collect)
    assert notes["id-1"]["content"].endswith("- [ ] cambiar el icono de la PWA")


@pytest.mark.asyncio
async def test_similar_checklists_require_clarification(tmp_path: Path) -> None:
    services, _notes, calls = _checklist_services(tmp_path, ["Mejoras Jarvis", "Mejoras Hotel"])
    result = await services.chat_stream({
        "message": "confírmame si existe el checklist Mejora",
        "conversation_id": "ambiguous", "turn_id": "ambiguous-0001",
    }, lambda _chunk: asyncio.sleep(0))
    assert "Mejoras Jarvis" in result["message"] and "Mejoras Hotel" in result["message"]
    assert "¿A cuál" in result["message"]
    assert [name for name, _ in calls] == ["query"]


@pytest.mark.asyncio
async def test_checklist_item_keeps_internal_conjunction_and_incomplete_item_waits(tmp_path: Path) -> None:
    services, notes, calls = _checklist_services(tmp_path)
    collect = lambda _chunk: asyncio.sleep(0)
    await services.chat_stream({
        "message": "en Mejoras añade que sea capaz de identificar cuál es la checklist y cuál es la carpeta y no solo dependa del contexto reciente",
        "conversation_id": "content", "turn_id": "content-0001",
    }, collect)
    assert notes["id-1"]["content"].count("- [ ]") == 1
    assert "checklist y cuál es la carpeta y no solo" in notes["id-1"]["content"]
    services._recent_notes["content"] = (dict(notes["id-1"]), 10**20)
    writes_before = len([call for call in calls if call[0] == "write"])
    incomplete = await services.chat_stream({
        "message": "añade que pueda", "conversation_id": "content", "turn_id": "content-0002",
    }, collect)
    assert incomplete["message"] == "¿Qué quiere que pueda hacer, señor?"
    assert len([call for call in calls if call[0] == "write"]) == writes_before
    await services.chat_stream({
        "message": "identificar acciones encadenadas", "conversation_id": "content", "turn_id": "content-0003",
    }, collect)
    assert "- [ ] que pueda identificar acciones encadenadas" in notes["id-1"]["content"]
    for index, fragment in enumerate(("que sea capaz de", "para", "y", "que pueda hacer"), 4):
        writes_before = len([call for call in calls if call[0] == "write"])
        waiting = await services.chat_stream({
            "message": f"añade {fragment}", "conversation_id": f"incomplete-{index}",
            "turn_id": f"content-000{index}",
        }, collect)
        assert waiting["message"].startswith("¿Qué quiere")
        assert len([call for call in calls if call[0] == "write"]) == writes_before


@pytest.mark.asyncio
async def test_web_chains_show_sources_and_open_wikipedia(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    opened: list[str] = []

    async def search(_arguments):
        return {"available": True, "results": [{
            "title": "H. P. Lovecraft - Wikipedia", "url": "https://es.wikipedia.org/wiki/H._P._Lovecraft",
            "content": "Howard Phillips Lovecraft fue un escritor estadounidense.", "domain": "es.wikipedia.org",
        }]}

    async def open_url(arguments):
        opened.append(arguments["url"])
        return {"opened": True, "verified": True}

    async def synthesize(_messages, _context=None):
        yield "Lovecraft fue un escritor estadounidense, señor."

    services.tools.register(Tool("web_search", "search", {"type": "object"}, search))
    services.tools.register(Tool("pc_open_url", "open", {"type": "object"}, open_url))
    services.ollama.chat_stream = synthesize
    collect = lambda _chunk: asyncio.sleep(0)
    shown = await services.chat_stream({
        "message": "Jarvis, búscame información sobre Lovecraft y muéstrame las fuentes en pantalla",
        "conversation_id": "web-chain", "turn_id": "web-chain-0001",
    }, collect)
    assert shown["message"] == "Lovecraft fue un escritor estadounidense, señor."
    assert shown["sources"] == [{
        "title": "H. P. Lovecraft - Wikipedia", "domain": "es.wikipedia.org",
        "url": "https://es.wikipedia.org/wiki/H._P._Lovecraft",
    }]
    assert "Wikipedia" not in shown["message"]
    await services.chat_stream({
        "message": "busca la Wikipedia de Lovecraft y ábrela",
        "conversation_id": "web-chain", "turn_id": "web-chain-0002",
    }, collect)
    assert opened == ["https://es.wikipedia.org/wiki/H._P._Lovecraft"]


@pytest.mark.asyncio
async def test_web_entity_guard_does_not_silently_change_lozca_to_mosca(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))

    async def search(_arguments):
        return {"available": True, "results": [{
            "title": "Mosca - Wikipedia", "url": "https://es.wikipedia.org/wiki/Mosca",
            "content": "Mosca es el nombre común de varias especies de insectos.", "domain": "es.wikipedia.org",
        }]}

    services.tools.register(Tool("web_search", "search", {"type": "object"}, search))
    result = await services.chat_stream({
        "message": "busca información sobre lozca", "conversation_id": "guard", "turn_id": "guard-0001",
    }, lambda _chunk: asyncio.sleep(0))
    assert result["message"] == "He encontrado resultados sobre «mosca». ¿Se refería a eso, señor?"


def test_pwa_icon_reuses_the_face_geometry() -> None:
    icon = Path("web/public/icon.svg").read_text(encoding="utf-8")
    assert 'cx="350" cy="360" r="60"' in icon
    assert 'cx="650" cy="360" r="60"' in icon
    assert 'x="410" y="520" width="180" height="40"' in icon
    assert 'viewBox="0 0 1000 1000"' in icon
