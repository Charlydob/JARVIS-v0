import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from jarvis_core.tools import Tool, ToolRegistry
from jarvis_core.integrations.bookshell_domains import BookShellDomains, register_domain_tools


LOGGER = logging.getLogger("jarvis-core.bookshell.http")


class BookShellClient:
    def __init__(
        self,
        base_url: str = "https://api-bookshell.charlydob.com",
        token: str = "",
        timezone: str = "Europe/Zurich",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timezone = timezone
        self.transport = transport
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.last_trace: dict[str, Any] = {}

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            transport=self.transport,
            timeout=httpx.Timeout(15.0, connect=5.0),
        ) as client:
            response = await client.request(method, path, **kwargs)
            try:
                raw_payload: Any = response.json()
            except ValueError:
                raw_payload = response.text
            params = kwargs.get("params") or {}
            self.last_trace = {
                "request_path": path, "params": dict(params), "http_status": response.status_code,
                "raw_response": raw_payload,
            }
            LOGGER.info(
                "request_path=%s params=%s http_status=%s raw_response=%s",
                path, json.dumps(dict(params), ensure_ascii=False), response.status_code,
                json.dumps(raw_payload, ensure_ascii=False),
            )
            response.raise_for_status()
            return dict(raw_payload)

    async def data(self, path: str) -> Any:
        return (await self._request("GET", f"/data/{path.strip('/')}" )).get("data")

    async def put_data(self, path: str, value: Any) -> dict[str, Any]:
        return await self._request("PUT", f"/data/{path.strip('/')}", json=value)

    async def patch_data(self, path: str, value: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/data/{path.strip('/')}", json=value)

    async def delete_data(self, path: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/data/{path.strip('/')}")

    async def push_data(self, path: str, value: Any) -> dict[str, Any]:
        return await self._request("POST", f"/data/push/{path.strip('/')}", json=value)

    async def transaction(self, path: str, current: Any, next_value: Any) -> dict[str, Any]:
        return await self._request(
            "POST", f"/data/transaction/{path.strip('/')}",
            json={"currentValue": current, "nextValue": next_value},
        )

    async def books(self) -> dict[str, dict[str, Any]]:
        data = await self.data("books/books") or {}
        return data if isinstance(data, dict) else {}

    async def current_book(self, title: str | None = None) -> dict[str, Any]:
        books = self._ordered_books(await self.books())
        if not books:
            return {"found": False, "message": "BookShell no contiene libros."}
        if title:
            wanted = title.casefold().strip()
            ranked = sorted(
                ((SequenceMatcher(None, wanted, str(book.get("title", "")).casefold()).ratio(), book) for book in books),
                key=lambda pair: pair[0], reverse=True,
            )
            if ranked[0][0] < 0.35:
                return {"found": False, "message": f"No encuentro un libro parecido a {title!r}."}
            if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08:
                return {
                    "found": False,
                    "ambiguous": True,
                    "candidates": [self._summary(item) for _, item in ranked[:3]],
                    "message": "Hay varios libros posibles; pregunta cuál quiere actualizar.",
                }
            chosen = ranked[0][1]
        else:
            reading = [book for book in books if str(book.get("status", "")).lower() == "reading"]
            chosen = (reading or books)[0]
        return {"found": True, "book": await self._book_summary(chosen)}

    async def query_books(self, arguments: dict[str, Any]) -> dict[str, Any]:
        mode = str(arguments.get("mode") or "current")
        title = str(arguments.get("title") or "").strip() or None
        if mode in {"current", "progress"}:
            return await self.current_book(title)
        books = self._ordered_books(await self.books())
        if mode == "search":
            query = (title or "").casefold()
            matches = [await self._book_summary(book) for book in books if query in str(book.get("title", "")).casefold()]
            return {"items": matches[: int(arguments.get("limit") or 10)], "count": len(matches)}
        selection = await self.current_book(title)
        if not selection.get("found"):
            return selection
        book = selection["book"]
        identifier = str(book["id"])
        if mode == "history":
            log = await self.data("books/readingLog") or {}
            entries = [
                {"date": date, "pagesRead": int(values.get(identifier) or 0)}
                for date, values in log.items() if isinstance(values, dict) and values.get(identifier) is not None
            ]
            entries.sort(key=lambda item: item["date"], reverse=True)
            return {"book": book, "history": entries[: int(arguments.get("limit") or 30)]}
        if mode == "notes":
            links = await self.data("books/links") or {}
            items = [
                {"id": key, **value} for key, value in links.items()
                if isinstance(value, dict) and (
                    value.get("bookId") == identifier or value.get("bookKey") == identifier
                    or str(value.get("bookTitle", "")).casefold() == str(book.get("title", "")).casefold()
                )
            ]
            return {"book": book, "notes": items[: int(arguments.get("limit") or 20)]}
        return {"error": "unsupported_mode"}

    async def update_progress(self, page: int, title: str | None = None, book_id: str | None = None) -> dict[str, Any]:
        all_books = await self.books()
        if book_id:
            selected = all_books.get(book_id)
            selection = {"found": bool(selected), "book": await self._book_summary({"id": book_id, **selected}) if selected else None}
        elif title:
            selection = await self.current_book(title)
        else:
            ordered = self._ordered_books(all_books)
            reading = [book for book in ordered if str(book.get("status", "")).lower() == "reading"]
            chosen = (reading or ordered)[0] if ordered else None
            selection = {"found": bool(chosen), "book": self._summary(chosen) if chosen else None}
        if not selection.get("found"):
            return selection
        summary = dict(selection["book"])
        identifier = str(summary["id"])
        current = dict(all_books[identifier])
        old_page = int(current.get("currentPage") or 0)
        total_pages = int(current.get("pages") or 0)
        target = max(0, min(int(page), total_pages)) if total_pages else max(0, int(page))
        updated = {
            **current,
            "currentPage": target,
            "status": "finished" if total_pages and target >= total_pages else "reading",
            "updatedAt": int(time.time() * 1000),
        }
        write_started = time.perf_counter()
        await self.transaction(f"books/books/{identifier}", current, updated)
        write_ms = (time.perf_counter() - write_started) * 1000
        delta = target - old_page
        async def update_log() -> bool:
            if not delta:
                return True
            day = datetime.now(ZoneInfo(self.timezone)).date().isoformat()
            path = f"/data/books/readingLog/{day}/{identifier}"
            try:
                log_payload = await self._request("GET", path)
                current_log = int(log_payload.get("data") or 0)
                await self.transaction(f"books/readingLog/{day}/{identifier}", log_payload.get("data"), current_log + delta)
                return True
            except httpx.HTTPError:
                return False

        readback_started = time.perf_counter()
        persisted_books, log_updated = await asyncio.gather(self.books(), update_log())
        readback_ms = (time.perf_counter() - readback_started) * 1000
        persisted = persisted_books.get(identifier) or {}
        verified = int(persisted.get("currentPage") or -1) == target
        if not verified:
            return {
                "updated": False, "verified": False,
                "message": "La página no aparece guardada al volver a consultar BookShell.",
                "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)},
            }
        return {
            "updated": True,
            "verified": True,
            "book": self._summary({"id": identifier, **persisted}),
            "previousPage": old_page,
            "readingLogUpdated": log_updated,
            "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)},
        }

    async def create_reminder(self, arguments: dict[str, Any]) -> dict[str, Any]:
        minutes = max(0, int(arguments.get("minutes_before") or 0))
        relative_day = str(arguments.get("relative_day") or "")
        target_date = str(arguments.get("target_date") or "")
        if relative_day in {"today", "tomorrow"}:
            offset = timedelta(days=1) if relative_day == "tomorrow" else timedelta()
            target_date = (datetime.now(ZoneInfo(self.timezone)).date() + offset).isoformat()
        if not target_date:
            return {"created": False, "clarificationRequired": True, "message": "¿Para qué fecha creo el recordatorio?"}
        target_time = str(arguments.get("target_time") or "").strip()
        if not target_time:
            return {"created": False, "clarificationRequired": True, "message": "¿A qué hora, señor?"}
        body = {
            "title": str(arguments["title"]).strip(),
            "description": str(arguments.get("description") or "").strip(),
            "emoji": "⏰",
            "type": "normal",
            "targetDate": target_date,
            "targetTime": target_time,
            "timezone": self.timezone,
            "source": {"type": "manual", "metadata": {"createdBy": "jarvis"}},
            "alerts": [{"mode": "relative", "minutesBefore": minutes, "channel": "telegram"}],
            "status": "pending",
        }
        write_started = time.perf_counter()
        idempotency_key = str(arguments.get("idempotency_key") or "").strip()
        request_headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        payload = await self._request("POST", "/reminders", json=body, headers=request_headers)
        write_ms = (time.perf_counter() - write_started) * 1000
        reminder = payload.get("reminder") or {}
        reminder_id = str(reminder.get("id") or payload.get("id") or "")
        readback_started = time.perf_counter()
        persisted = await self._request(
            "GET", "/reminders", params={"from": target_date, "until": target_date, "limit": 100},
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        readback_ms = (time.perf_counter() - readback_started) * 1000
        saved = next(
            (
                item for item in persisted.get("reminders", [])
                if (reminder_id and str(item.get("id")) == reminder_id)
                or (
                    str(item.get("title")) == body["title"]
                    and str(item.get("targetDate")) == target_date
                    and str(item.get("targetTime")) == target_time
                )
            ),
            None,
        )
        verified = bool(saved)
        return {
            "created": bool(payload.get("created", True)) and verified,
            "verified": verified,
            "reminder": saved,
            "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)},
            **({"message": "El recordatorio no aparece al volver a consultar BookShell."} if not verified else {}),
        }

    @staticmethod
    def _ordered_books(books: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        result = [{"id": identifier, **book} for identifier, book in books.items() if isinstance(book, dict)]
        return sorted(result, key=lambda book: int(book.get("updatedAt") or 0), reverse=True)

    @staticmethod
    def _summary(book: dict[str, Any]) -> dict[str, Any]:
        pages = int(book.get("pages") or 0)
        current = int(book.get("currentPage") or 0)
        return {
            "id": book.get("id"),
            "title": book.get("title"),
            "author": book.get("author"),
            "currentPage": current,
            "pages": pages,
            "remainingPages": max(0, pages - current),
            "progressPercent": round((current / pages) * 100, 1) if pages else None,
            "status": book.get("status"),
            "updatedAt": book.get("updatedAt"),
        }

    async def _book_summary(self, book: dict[str, Any]) -> dict[str, Any]:
        summary = self._summary(book)
        log = await self.data("books/readingLog") or {}
        dates = [date for date, values in log.items() if isinstance(values, dict) and values.get(book.get("id"))]
        summary["lastReadingDate"] = max(dates) if dates else None
        summary["daysSinceReading"] = (
            (datetime.now(ZoneInfo(self.timezone)).date() - datetime.fromisoformat(summary["lastReadingDate"]).date()).days
            if summary["lastReadingDate"] else None
        )
        return summary


def register_tools(registry: ToolRegistry) -> None:
    client = BookShellClient(
        base_url=os.getenv("JARVIS_BOOKSHELL_API_URL", "https://api-bookshell.charlydob.com"),
        token=os.getenv("JARVIS_BOOKSHELL_API_TOKEN", ""),
        timezone=os.getenv("JARVIS_BOOKSHELL_TIMEZONE", "Europe/Zurich"),
    )

    domains = BookShellDomains(client)

    registry.register(Tool(
        "bookshell_books_query",
        "Consulta libros en BookShell: libro actual, búsqueda por título, página/progreso/estado, historial de lectura o citas/notas. Úsala también para cuánto queda o cuándo se leyó por última vez.",
        {"type": "object", "properties": {
            "mode": {"type": "string", "enum": ["current", "progress", "search", "history", "notes"]},
            "title": {"type": "string", "description": "Título opcional aproximado"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        }, "required": ["mode"]},
        client.query_books,
    ))
    registry.register(Tool(
        "bookshell_update_progress",
        "Actualiza realmente en BookShell la página de lectura. Úsala para frases como 'voy por la página 33' o 'he avanzado hasta la 120'. Si no se indica libro, usa el libro activo más reciente.",
        {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "minimum": 0},
                "title": {"type": "string", "description": "Título opcional si el usuario lo especifica"},
            },
            "required": ["page"],
        },
        lambda args: client.update_progress(int(args["page"]), args.get("title")),
    ))
    registry.register(Tool(
        "bookshell_create_reminder",
        "Crea un recordatorio real en BookShell cuando el usuario lo pide. La fecha debe ser YYYY-MM-DD y la hora HH:MM; pregunta si falta un dato necesario, no lo inventes.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "target_date": {"type": "string", "description": "Fecha YYYY-MM-DD"},
                "relative_day": {"type": "string", "enum": ["today", "tomorrow"], "description": "Usar si el usuario dice hoy o mañana"},
                "target_time": {"type": "string", "description": "Hora HH:MM"},
                "minutes_before": {"type": "integer", "minimum": 0, "description": "Aviso previo en minutos; 0 si no se pidió antelación"},
                "idempotency_key": {"type": "string", "description": "Clave interna estable para impedir creaciones duplicadas"},
            },
            "required": ["title"],
        },
        client.create_reminder,
    ))
    register_domain_tools(registry, domains)
