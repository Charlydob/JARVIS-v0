import asyncio
import json

import httpx

from jarvis_core.integrations.bookshell import BookShellClient


def test_query_update_and_confirm_real_shape() -> None:
    book = {"title": "Musashi", "author": "Eiji", "currentPage": 221, "pages": 575, "status": "reading", "updatedAt": 10}
    requests: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal book
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.url.path == "/jarvis/data/books/books":
            return httpx.Response(200, json={"ok": True, "data": {"book-1": book}})
        if request.url.path == "/jarvis/books/progress":
            previous = book["currentPage"]
            book = {**book, "currentPage": body["page"], "updatedAt": 20}
            return httpx.Response(200, json={"ok": True, "updated": True, "verified": True, "previousPage": previous, "book": {"id": "book-1", **book}})
        if request.url.path == "/jarvis/books":
            return httpx.Response(200, json={"ok": True, "found": True, "book": {"id": "book-1", **book, "lastReadingDate": "2026-09-19"}})
        if request.method == "GET":
            return httpx.Response(200, json={"ok": True, "data": None})
        return httpx.Response(200, json={"ok": True, "data": body["nextValue"]})

    client = BookShellClient(transport=httpx.MockTransport(handler))
    before = asyncio.run(client.current_book())
    changed = asyncio.run(client.update_progress(222))
    after = asyncio.run(client.current_book())

    assert before["book"]["currentPage"] == 221
    assert changed["book"]["currentPage"] == 222
    assert after["book"]["currentPage"] == 222
    assert any(path == "/jarvis/books/progress" for _, path, _ in requests)


def test_reminder_uses_canonical_endpoint() -> None:
    captured = {}
    captured_headers = {}
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.method == "POST":
            captured.update(json.loads(request.content))
            captured_headers.update(request.headers)
            return httpx.Response(201, json={"ok": True, "created": True, "reminder": {"id": "reminder-1", **captured}})
        return httpx.Response(200, json={"reminders": [{"id": "reminder-1", **captured}]})

    client = BookShellClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(client.create_reminder({"title": "Clase de alemán", "target_date": "2026-09-19", "target_time": "18:00", "minutes_before": 60, "idempotency_key": "pending-action-1"}))

    assert result["created"] is True
    assert result["verified"] is True
    assert captured["timezone"] == "Europe/Zurich"
    assert captured["alerts"][0]["minutesBefore"] == 60
    assert captured_headers["idempotency-key"] == "pending-action-1"
    assert paths == ["/jarvis/reminders", "/jarvis/reminders"]


def test_reminder_without_time_asks_and_does_not_write() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = BookShellClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(client.create_reminder({"title": "Clase de alemán", "target_date": "2026-09-19"}))

    assert result == {"created": False, "clarificationRequired": True, "message": "¿A qué hora, señor?"}
    assert calls == 0
