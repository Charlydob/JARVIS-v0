import asyncio
from typing import Any

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
        if parts[:3] == ["gym", "gym", "workouts"]:
            root = self.values.setdefault("gym/gym", {})
            root.setdefault("workouts", {}).setdefault(parts[3], {})[parts[4]] = value
        return {"ok": True}

    async def patch_data(self, path: str, value: Any) -> dict[str, Any]:
        self.writes.append(("patch", path, value)); return {"ok": True}

    async def _request(self, _method: str, _path: str, **_kwargs: Any) -> dict[str, Any]:
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
    assert client.writes[0][:2] == ("put", "habits/habitCounts/h1/2026-09-17")


def test_finance_write_fails_closed_without_shortcut_token() -> None:
    client = FakeClient({"finance/finance": {"accounts": {}, "transactions": {}}})
    result = asyncio.run(BookShellDomains(client).finance_write({"type": "expense", "amount": 12}))
    assert result["configurationRequired"] is True
    assert client.writes == []


def test_finance_fixture_write_uses_shortcut_and_idempotency() -> None:
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
    assert client.request[1] == "/shortcuts/finance/movements"
    assert client.request[2]["headers"]["Idempotency-Key"] == "fixture-1"


def test_world_note_and_recipe_writes_use_existing_data_paths() -> None:
    client = FakeClient({})
    domains = BookShellDomains(client)
    world = asyncio.run(domains.world_write({"action": "create", "scope": "places", "name": "Fixture café"}))
    note = asyncio.run(domains.notes_write({"action": "create", "title": "Fixture", "content": "Text"}))
    recipe = asyncio.run(domains.recipes_write({"action": "create", "title": "Fixture recipe"}))
    assert world["created"] and note["created"] and recipe["created"]
    assert note["verified"] is True
    assert [path.split("/")[0] for _, path, _ in client.writes] == ["world", "notes", "recipes"]


def test_cancel_reminder_requires_explicit_confirmation() -> None:
    result = asyncio.run(BookShellDomains(FakeClient({})).reminder_update({"reminder_id": "r1", "action": "cancel"}))
    assert result["confirmationRequired"] is True


def test_today_reminders_are_fresh_include_overdue_and_exclude_cancelled() -> None:
    class ReminderClient(FakeClient):
        request_kwargs: dict[str, Any] = {}

        async def _request(self, _method: str, _path: str, **kwargs: Any) -> dict[str, Any]:
            self.request_kwargs = kwargs
            return {"reminders": [
                {"id": "past", "title": "Clase", "targetTime": "05:30", "status": "pending"},
                {"id": "future", "title": "Dentista", "targetTime": "17:30", "status": "pending"},
                {"id": "cancelled", "title": "Borrado", "targetTime": "12:00", "status": "cancelled"},
            ]}

    client = ReminderClient({})
    result = asyncio.run(BookShellDomains(client).reminders_query({"scope": "today"}))
    assert [item["id"] for item in result["items"]] == ["past", "future"]
    assert client.request_kwargs["headers"]["Cache-Control"] == "no-cache"
    assert client.request_kwargs["params"]["from"] == client.request_kwargs["params"]["until"]
