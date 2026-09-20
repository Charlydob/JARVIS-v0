import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis_core.config import CoreSettings
from jarvis_core.integrations.bookshell_domains import BookShellDomains
from jarvis_core.integrations.web import TavilySearch, register_tools
from jarvis_core.intents import route_direct_intent
from jarvis_core.services import JarvisServices
from jarvis_core.tools import Tool, ToolRegistry


class NotesClient:
    timezone = "Europe/Zurich"

    def __init__(self, folders: dict[str, Any], notes: dict[str, Any]) -> None:
        self.values = {"notes/folders": folders, "notes/notes": notes}
        self.writes: list[tuple[str, str, Any]] = []

    async def data(self, path: str) -> Any:
        return self.values.get(path)

    async def put_data(self, path: str, value: Any) -> dict[str, Any]:
        self.writes.append(("put", path, value))
        root, item_id = path.rsplit("/", 1)
        self.values.setdefault(root, {})[item_id] = value
        return {"ok": True}

    async def patch_data(self, path: str, value: Any) -> dict[str, Any]:
        self.writes.append(("patch", path, value))
        root, item_id = path.rsplit("/", 1)
        self.values.setdefault(root, {}).setdefault(item_id, {}).update(value)
        return {"ok": True}

    async def delete_data(self, path: str) -> dict[str, Any]:
        self.writes.append(("delete", path, None))
        root, item_id = path.rsplit("/", 1)
        self.values.setdefault(root, {}).pop(item_id, None)
        return {"ok": True}


@pytest.mark.asyncio
async def test_a_note_is_created_inside_real_existing_folder(tmp_path: Path) -> None:
    client = NotesClient({"folder-personas": {"name": "Personas", "createdAt": 1}}, {})
    domains = BookShellDomains(client)
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    services.tools.register(Tool("bookshell_notes_folder_query", "query", {"type": "object"}, domains.notes_folders_query))
    services.tools.register(Tool("bookshell_notes_write", "write", {"type": "object"}, domains.notes_write))

    async def collect(_chunk: str) -> None:
        pass

    result = await services.chat_stream({
        "message": "crea una nota en la carpeta Personas llamada Dayana",
        "conversation_id": "notes-a", "turn_id": "notes-a-1",
    }, collect)
    saved = next(iter(client.values["notes/notes"].values()))
    assert saved["title"] == "Dayana" and saved["folderId"] == "folder-personas"
    assert result["message"] == "Hecho y verificado en BookShell, señor."


@pytest.mark.asyncio
async def test_b_existing_folder_is_not_duplicated(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    writes = 0

    async def query(_arguments: dict[str, Any]) -> dict[str, Any]:
        return {"items": [{"id": "p1", "name": "Personas"}], "count": 1}

    async def create(_arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal writes
        writes += 1
        return {"created": True, "verified": True}

    services.tools.register(Tool("bookshell_notes_folder_query", "query", {"type": "object"}, query))
    services.tools.register(Tool("bookshell_notes_folder_create", "create", {"type": "object"}, create))
    result = await services.chat_stream({
        "message": "crea una carpeta que se llame personas", "turn_id": "folder-b-1",
    }, lambda _chunk: asyncio.sleep(0))
    assert writes == 0
    assert result["message"] == "La carpeta Personas ya existe, señor."


def test_c_d_e_note_and_folder_deletes_verify_and_never_cascade() -> None:
    client = NotesClient(
        {"empty": {"name": "Temporal"}, "full": {"name": "Personas"}},
        {"note-x": {"title": "Test checklist", "folderId": "full"}},
    )
    domains = BookShellDomains(client)
    note = asyncio.run(domains.notes_delete({"title": "test checklist"}))
    empty = asyncio.run(domains.notes_folder_delete({"name": "Temporal"}))
    full_client = NotesClient(
        {"full": {"name": "Personas"}, "child": {"name": "Hijas", "parentId": "full"}},
        {"note-y": {"title": "Dayana", "folderId": "full"}},
    )
    refused = asyncio.run(BookShellDomains(full_client).notes_folder_delete({"name": "personas"}))
    assert note["deleted"] and note["verified"] and "note-x" not in client.values["notes/notes"]
    assert empty["deleted"] and empty["verified"] and "empty" not in client.values["notes/folders"]
    assert refused["confirmationRequired"] is True
    assert refused["noteCount"] == 1 and refused["subfolderCount"] == 1
    assert not [write for write in full_client.writes if write[0] == "delete"]


@pytest.mark.parametrize(
    ("message", "title", "folder"),
    [
        ("crea una nota Dayana en Personas", "Dayana", "Personas"),
        ("crea una nota en la carpeta Personas llamada Dayana", "Dayana", "Personas"),
        ("en Personas crea una nota llamada Dayana", "Dayana", "Personas"),
        ("añade Dayana a la carpeta Personas", "Dayana", "Personas"),
        ("crea una nota con el nombre Dayana dentro de Personas", "Dayana", "Personas"),
        ("¿Podrías crear una nota en la carpeta de personas con el nombre Dayana?", "Dayana", "personas"),
    ],
)
def test_note_folder_natural_formulations(message: str, title: str, folder: str) -> None:
    intent = route_direct_intent(message, date(2026, 9, 20))
    assert intent is not None and intent.kind == "note_create_in_folder"
    assert intent.arguments["title"] == title
    assert intent.arguments["folder_name"] == folder


@pytest.mark.asyncio
async def test_f_tavily_basic_search_returns_structured_real_urls() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-fixture"
        payload = json.loads(request.content)
        assert payload["search_depth"] == "basic" and payload["max_results"] == 5
        return httpx.Response(200, json={
            "results": [{
                "title": "H. P. Lovecraft", "url": "https://en.wikipedia.org/wiki/H._P._Lovecraft",
                "content": "American writer born in 1890.", "score": 0.99,
            }], "response_time": "0.4",
        })

    search = TavilySearch("secret-fixture", transport=httpx.MockTransport(handler))
    result = await search.search({"query": "H. P. Lovecraft", "max_results": 5, "topic": "general"})
    assert result["provider"] == "tavily" and result["count"] == 1
    assert result["results"][0]["url"].startswith("https://")


@pytest.mark.asyncio
async def test_tavily_failure_is_fail_closed_and_registry_depends_on_key(monkeypatch) -> None:
    async def failure(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": {"error": "invalid key"}})

    search = TavilySearch("not-a-real-key", transport=httpx.MockTransport(failure))
    result = await search.search({"query": "Lovecraft"})
    assert result == {
        "available": False, "error": "provider_unavailable",
        "message": "La búsqueda web no está disponible ahora mismo, señor.",
    }
    monkeypatch.delenv("JARVIS_TAVILY_API_KEY", raising=False)
    registry = ToolRegistry()
    register_tools(registry)
    assert not registry.has("web_search")
    monkeypatch.setenv("JARVIS_TAVILY_API_KEY", "fixture-key")
    configured = ToolRegistry()
    register_tools(configured)
    assert configured.has("web_search")


def test_g_explicit_search_routes_to_web_not_books() -> None:
    for message in (
        "búscame su página de Wikipedia", "busca información sobre Lovecraft",
        "investiga el MG90S", "busca cuánto consume el MG90S",
    ):
        intent = route_direct_intent(message, date(2026, 9, 20))
        assert intent is not None and intent.tool == "web_search" and intent.domain == "web"


@pytest.mark.asyncio
async def test_h_i_sources_open_from_previous_search_and_same_turn(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    opened: list[str] = []

    async def search(_arguments: dict[str, Any]) -> dict[str, Any]:
        return {"available": True, "results": [{
            "title": "H. P. Lovecraft - Wikipedia",
            "url": "https://es.wikipedia.org/wiki/H._P._Lovecraft", "content": "Escritor estadounidense.",
        }], "count": 1}

    async def open_url(arguments: dict[str, Any]) -> dict[str, Any]:
        opened.append(arguments["url"])
        return {"opened": True, "verified": True, "url": arguments["url"]}

    services.tools.register(Tool("web_search", "search", {"type": "object"}, search))
    services.tools.register(Tool("pc_open_url", "open", {"type": "object"}, open_url))
    conversation = "web-open"
    await services.chat_stream({
        "message": "búscame la página de Wikipedia de Lovecraft",
        "conversation_id": conversation, "turn_id": "web-h-1",
    }, lambda _chunk: asyncio.sleep(0))
    await services.chat_stream({
        "message": "muéstrame la fuente", "conversation_id": conversation, "turn_id": "web-h-2",
    }, lambda _chunk: asyncio.sleep(0))
    same_turn = await services.chat_stream({
        "message": "busca y abre la Wikipedia de Lovecraft en el ordenador",
        "conversation_id": "web-open-now", "turn_id": "web-i-1",
    }, lambda _chunk: asyncio.sleep(0))
    assert opened == [
        "https://es.wikipedia.org/wiki/H._P._Lovecraft",
        "https://es.wikipedia.org/wiki/H._P._Lovecraft",
    ]
    assert "abierto" in same_turn["message"]


@pytest.mark.asyncio
async def test_j_internet_answer_reflects_registry(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    services.tools.register(Tool("pc_open_url", "open", {"type": "object"}, lambda _args: asyncio.sleep(0)))
    missing = await services.chat_stream(
        {"message": "¿tienes Internet?", "turn_id": "cap-j-1"}, lambda _chunk: asyncio.sleep(0),
    )

    async def search(_arguments: dict[str, Any]) -> dict[str, Any]:
        return {"available": True, "results": []}

    services.tools.register(Tool("web_search", "search", {"type": "object"}, search))
    available = await services.chat_stream(
        {"message": "¿tienes Internet?", "turn_id": "cap-j-2"}, lambda _chunk: asyncio.sleep(0),
    )
    assert "puedo abrir URLs" in missing["message"] and "no tengo búsqueda web general" in missing["message"]
    assert "búsqueda web disponible" in available["message"] and "abrir páginas" in available["message"]
