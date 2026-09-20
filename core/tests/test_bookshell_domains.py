import asyncio
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from jarvis_core.integrations.bookshell_domains import BookShellDomains


class FakeClient:
    timezone = "Europe/Zurich"
    headers: dict[str, str] = {}

    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values
        self.writes: list[tuple[str, str, Any]] = []

    async def data(self, path: str) -> Any:
        return self.values.get(path)

    async def put_data(self, path: str, value: Any) -> dict[str, Any]:
        self.writes.append(("put", path, value))
        parts = path.split("/")
        if parts[:2] == ["notes", "notes"]:
            self.values.setdefault("notes/notes", {})[parts[2]] = value
        if parts[:2] == ["notes", "folders"]:
            self.values.setdefault("notes/folders", {})[parts[2]] = value
        if parts[:3] == ["gym", "gym", "workouts"]:
            root = self.values.setdefault("gym/gym", {})
            root.setdefault("workouts", {}).setdefault(parts[3], {})[parts[4]] = value
        if parts[0] == "world":
            self.values.setdefault("world", {}).setdefault(parts[1], {})[parts[2]] = value
        if parts[:2] == ["recipes", "items"]:
            self.values.setdefault("recipes/items", {})[parts[2]] = value
        return {"ok": True}

    async def patch_data(self, path: str, value: Any) -> dict[str, Any]:
        self.writes.append(("patch", path, value))
        parts = path.split("/")
        if parts[0] == "world":
            self.values.setdefault("world", {}).setdefault(parts[1], {}).setdefault(parts[2], {}).update(value)
        if parts[:2] == ["recipes", "items"]:
            self.values.setdefault("recipes/items", {}).setdefault(parts[2], {}).update(value)
        if parts[:2] == ["notes", "notes"]:
            self.values.setdefault("notes/notes", {}).setdefault(parts[2], {}).update(value)
        return {"ok": True}

    async def _request(self, _method: str, _path: str, **_kwargs: Any) -> dict[str, Any]:
        if _path == "/jarvis/habits/mark":
            body = _kwargs["json"]
            return {"updated": True, "verified": True, "habit": {"habit": "Leer", "date": body["date"], "goal": "count", "value": body["value"]}}
        return {"reminders": []}


class FinanceFakeClient(FakeClient):
    headers = {"Authorization": "Bearer fixture-token"}

    def __init__(self, values: dict[str, Any]) -> None:
        super().__init__(values)
        self.request: tuple[str, str, dict[str, Any]] | None = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self.request = (method, path, kwargs)
        return {"ok": True, "movementId": "fixture-movement"}


def test_gym_last_session_and_days_since() -> None:
    client = FakeClient({"gym/gym": {"workouts": {"2026-09-15": {"w1": {"id": "w1", "date": "2026-09-15", "name": "Pecho", "startedAt": 1, "finishedAt": 2, "exercises": {}}}}}})
    result = asyncio.run(BookShellDomains(client).gym_query({"mode": "days_since"}))
    assert result["workout"]["name"] == "Pecho"
    assert result["workout"]["daysSince"] >= 0


def test_habit_status_and_mark_quantitative_value() -> None:
    values = {"habits": {"habits": {"h1": {"name": "Leer", "goal": "count", "schedule": {"type": "daily"}}}, "habitCounts": {"h1": {"2026-09-17": 2}}}}
    client = FakeClient(values)
    domains = BookShellDomains(client)
    status = asyncio.run(domains.habits_query({"mode": "status", "name": "Leer", "date": "2026-09-17"}))
    updated = asyncio.run(domains.habits_mark({"name": "Leer", "date": "2026-09-17", "value": 3}))
    assert status["habit"]["completed"] is True
    assert updated["value"] == 3
    assert updated["verified"] is True


def test_finance_write_fails_closed_without_shortcut_token() -> None:
    client = FakeClient({"finance/finance": {"accounts": {}, "transactions": {}}})
    result = asyncio.run(BookShellDomains(client).finance_write({"type": "expense", "amount": 12}))
    assert result["configurationRequired"] is True
    assert client.writes == []


def test_finance_fixture_write_uses_private_jarvis_api_and_idempotency() -> None:
    root = {
        "accounts": {"a1": {"name": "Principal", "currency": "CHF", "active": True}},
        "catalog": {"categories": {"food": {"name": "Comida", "type": "expense"}}},
        "transactions": {},
    }
    client = FinanceFakeClient({"finance/finance": root})
    result = asyncio.run(BookShellDomains(client).finance_write({
        "type": "expense", "amount": 12, "currency": "CHF", "description": "Fixture",
        "category": "Comida", "account": "Principal", "date": "2026-09-17", "idempotency_key": "fixture-1",
    }))
    assert result["movementId"] == "fixture-movement"
    assert result["verified"] is False
    assert client.request is not None
    assert client.request[1] == "/jarvis/finance/movements"
    assert client.request[2]["headers"]["Idempotency-Key"] == "fixture-1"


def test_world_note_and_recipe_writes_use_existing_data_paths() -> None:
    client = FakeClient({})
    domains = BookShellDomains(client)
    world = asyncio.run(domains.world_write({"action": "create", "scope": "places", "name": "Fixture café"}))
    note = asyncio.run(domains.notes_write({"action": "create", "title": "Fixture", "content": "Text"}))
    recipe = asyncio.run(domains.recipes_write({"action": "create", "title": "Fixture recipe"}))
    assert world["created"] and note["created"] and recipe["created"]
    assert world["verified"] is True and note["verified"] is True and recipe["verified"] is True
    assert [path.split("/")[0] for _, path, _ in client.writes] == ["world", "notes", "notes", "recipes"]
    saved_note = next(iter(client.values["notes/notes"].values()))
    assert saved_note["type"] == "note"
    assert saved_note["noteKind"] == "text"
    assert saved_note["folderId"] in client.values["notes/folders"]


def test_note_followup_and_checklist_use_visible_persisted_content() -> None:
    client = FakeClient({"notes/folders": {"f1": {"name": "JARVIS", "isPrivate": False}}, "notes/notes": {}})
    domains = BookShellDomains(client)
    created = asyncio.run(domains.notes_write({
        "action": "create", "title": "Prueba integración JARVIS", "content": "Primera línea",
    }))
    updated = asyncio.run(domains.notes_write({
        "action": "update", "note_id": created["id"], "append_content": "Segunda línea",
    }))
    checklist = asyncio.run(domains.notes_write({
        "action": "create", "title": "Checklist laboratorio",
        "content": "- [ ] conectar ESP32\n- [ ] probar relé\n- [ ] revisar fuente",
    }))
    marked = asyncio.run(domains.notes_write({
        "action": "update", "note_id": checklist["id"], "check_item": "probar relé",
    }))
    pending = asyncio.run(domains.notes_query({"query": "Checklist laboratorio", "pending_only": True}))
    assert updated["verified"] is True
    assert client.values["notes/notes"][created["id"]]["content"] == "Primera línea\nSegunda línea"
    assert marked["verified"] is True
    assert [item["item"] for item in pending["pendingItems"]] == ["conectar ESP32", "revisar fuente"]


def test_note_folder_create_is_idempotent_and_read_back() -> None:
    client = FakeClient({"notes/folders": {}})
    domains = BookShellDomains(client)
    created = asyncio.run(domains.notes_folder_write({"action": "create", "name": "Mejoras para JARVIS"}))
    repeated = asyncio.run(domains.notes_folder_write({"action": "create", "name": "mejoras para jarvis"}))
    queried = asyncio.run(domains.notes_folders_query({"query": "Mejoras para JARVIS"}))
    assert created["created"] is True and created["verified"] is True
    assert repeated["existing"] is True and repeated["verified"] is True
    assert queried["count"] == 1
    assert queried["items"][0]["name"] == "Mejoras para JARVIS"


def test_note_create_verifies_canonical_visible_fields() -> None:
    client = FakeClient({"notes/folders": {"jarvis": {"name": "Jarvis", "createdAt": 1}}, "notes/notes": {}})
    result = asyncio.run(BookShellDomains(client).notes_write({
        "action": "create", "title": "montaje checkout", "content": "",
    }))
    saved = client.values["notes/notes"][result["id"]]
    assert result["created"] is True and result["verified"] is True
    assert {key: saved[key] for key in ("title", "name", "folderId", "content", "type", "noteKind")} == {
        "title": "montaje checkout", "name": "montaje checkout", "folderId": "jarvis",
        "content": "", "type": "note", "noteKind": "text",
    }


def test_blank_checklist_can_add_mark_and_query_persisted_items() -> None:
    client = FakeClient({"notes/folders": {"jarvis": {"name": "Jarvis"}}, "notes/notes": {}})
    domains = BookShellDomains(client)
    created = asyncio.run(domains.notes_write({
        "action": "create", "title": "Mejoras para JARVIS", "content": "", "tags": ["checklist"],
    }))
    asyncio.run(domains.notes_write({
        "action": "update", "note_id": created["id"], "append_content": "- [ ] mejorar STT",
    }))
    asyncio.run(domains.notes_write({
        "action": "update", "note_id": created["id"], "append_content": "- [ ] wake word",
    }))
    marked = asyncio.run(domains.notes_write({
        "action": "update", "note_id": created["id"], "check_item": "mejorar STT",
    }))
    pending = asyncio.run(domains.notes_query({"query": "Mejoras para JARVIS", "pending_only": True}))
    assert marked["updated"] is True and marked["verified"] is True
    assert [item["item"] for item in pending["pendingItems"]] == ["wake word"]


def test_last_message_title_typo_resolves_to_real_note_uuid() -> None:
    client = FakeClient({
        "notes/folders": {"jarvis": {"name": "Jarvis"}},
        "notes/notes": {"uuid-bux": {
            "folderId": "jarvis", "title": "bux Jarvis", "name": "bux Jarvis",
            "content": "", "tags": [], "createdAt": 1, "updatedAt": 1,
        }},
    })
    result = asyncio.run(BookShellDomains(client).notes_write({
        "action": "update", "title": "bugs Jarvis",
        "append_content": "La nota bux Jarvis se ha creado con éxito.",
    }))
    assert result["updated"] is True and result["verified"] is True
    assert client.writes[-1][1] == "notes/notes/uuid-bux"
    assert client.values["notes/notes"]["uuid-bux"]["content"] == "La nota bux Jarvis se ha creado con éxito."
    assert client.values["notes/notes"]["uuid-bux"]["title"] == "bux Jarvis"


def test_cancel_reminder_requires_explicit_confirmation() -> None:
    result = asyncio.run(BookShellDomains(FakeClient({})).reminder_update({"reminder_id": "r1", "action": "cancel"}))
    assert result["confirmationRequired"] is True


def test_today_reminders_are_fresh_include_overdue_and_exclude_cancelled() -> None:
    class ReminderClient(FakeClient):
        request_kwargs: dict[str, Any] = {}

        async def _request(self, _method: str, _path: str, **kwargs: Any) -> dict[str, Any]:
            self.request_kwargs = kwargs
            target_date = datetime.now(ZoneInfo(self.timezone)).date().isoformat()
            return {"reminders": [
                {"id": "past", "title": "Clase", "targetDate": target_date, "targetTime": "05:30", "status": "pending"},
                {"id": "future", "title": "Dentista", "targetDate": target_date, "targetTime": "23:59", "status": "pending"},
                {"id": "cancelled", "title": "Borrado", "targetDate": target_date, "targetTime": "12:00", "status": "cancelled"},
            ]}

    client = ReminderClient({})
    result = asyncio.run(BookShellDomains(client).reminders_query({"scope": "today"}))
    assert [item["id"] for item in result["items"]] == ["past", "future"]
    assert client.request_kwargs["headers"]["Cache-Control"] == "no-cache"
    assert client.request_kwargs["params"]["range"] == "today"
    assert result["items"][0]["temporalState"] == "vencido"


def test_reminder_scopes_send_distinct_calendar_ranges() -> None:
    class ReminderClient(FakeClient):
        def __init__(self) -> None:
            super().__init__({})
            self.requests: list[dict[str, Any]] = []

        async def _request(self, _method: str, _path: str, **kwargs: Any) -> dict[str, Any]:
            self.requests.append(dict(kwargs["params"]))
            return {"reminders": []}

    client = ReminderClient()
    domains = BookShellDomains(client)
    for scope in ("today", "tomorrow", "this_week", "next_week"):
        result = asyncio.run(domains.reminders_query({"scope": scope}))
        assert result["range"] == scope

    today = datetime.now(ZoneInfo(client.timezone)).date()
    monday = today - timedelta(days=today.weekday())
    assert client.requests == [{"limit": 100, "status": "pending", "range": scope} for scope in ("today", "tomorrow", "this_week", "next_week")]


def test_habits_accepts_model_date_aliases() -> None:
    client = FakeClient({"habits": {"habits": {"habit": {"name": "Leer", "schedule": {"type": "daily"}}}}})
    result = asyncio.run(BookShellDomains(client).habits_query({"mode": "list", "date": "today"}))
    assert result["date"] == BookShellDomains(client).today()
    assert result["items"][0]["name"] == "Leer"
