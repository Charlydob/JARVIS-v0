import json
import logging
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from jarvis_core.tools import Tool, ToolRegistry
from jarvis_core.config import CoreSettings
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
            request_json = kwargs.get("json")
            count = len(raw_payload) if isinstance(raw_payload, list) else None
            if isinstance(raw_payload, dict):
                for key in ("items", "results", "reminders"):
                    if isinstance(raw_payload.get(key), list):
                        count = len(raw_payload[key])
                        break
            self.last_trace = {
                "request_path": path, "params": dict(params), "http_status": response.status_code,
                "raw_result_summary": {"keys": sorted(raw_payload) if isinstance(raw_payload, dict) else [], "count": count},
            }
            LOGGER.info(
                "method=%s endpoint=%s params=%s request_json=%s http_status=%s raw_result_summary=%s",
                method, path, json.dumps(dict(params), ensure_ascii=False),
                json.dumps(request_json, ensure_ascii=False)[:2000] if request_json is not None else "null",
                response.status_code,
                json.dumps(self.last_trace["raw_result_summary"], ensure_ascii=False),
            )
            if not response.is_success:
                api_error = str(raw_payload.get("error") or raw_payload.get("detail") or "unknown_error") if isinstance(raw_payload, dict) else str(raw_payload)
                LOGGER.error("endpoint=%s http_status=%s bookshell_error=%s", path, response.status_code, api_error)
                raise RuntimeError(f"BookShell HTTP {response.status_code}: {api_error}")
            return dict(raw_payload)

    async def data(self, path: str) -> Any:
        return (await self._request("GET", f"/jarvis/data/{path.strip('/')}" )).get("data")

    async def put_data(self, path: str, value: Any) -> dict[str, Any]:
        return await self._request("PUT", f"/jarvis/data/{path.strip('/')}", json=value)

    async def patch_data(self, path: str, value: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/jarvis/data/{path.strip('/')}", json=value)

    async def delete_data(self, path: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/jarvis/data/{path.strip('/')}")

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
        if mode != "notes":
            return await self._request("GET", "/jarvis/books", params={
                "mode": mode, "title": title or "", "limit": int(arguments.get("limit") or 10),
            })
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
        write_started = time.perf_counter()
        result = await self._request("PATCH", "/jarvis/books/progress", json={
            "page": int(page), "title": title or "", "bookId": book_id or "",
        })
        write_ms = (time.perf_counter() - write_started) * 1000
        readback_started = time.perf_counter()
        readback = await self._request("GET", "/jarvis/books", params={"mode": "current", "title": title or result.get("book", {}).get("title", "")})
        readback_ms = (time.perf_counter() - readback_started) * 1000
        verified = bool(result.get("verified")) and int(readback.get("book", {}).get("currentPage", -1)) == int(result.get("book", {}).get("currentPage", -2))
        return {**result, "updated": bool(result.get("updated")) and verified, "verified": verified,
                "book": readback.get("book") or result.get("book"),
                "_timings": {"write_ms": round(write_ms, 1), "readback_ms": round(readback_ms, 1)},
                **({"message": "La página no aparece guardada al volver a consultar BookShell."} if not verified else {})}

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
        payload = await self._request("POST", "/jarvis/reminders", json=body, headers=request_headers)
        write_ms = (time.perf_counter() - write_started) * 1000
        reminder = payload.get("reminder") or {}
        reminder_id = str(reminder.get("id") or payload.get("id") or "")
        readback_started = time.perf_counter()
        persisted = await self._request(
            "GET", "/jarvis/reminders", params={"from": target_date, "until": target_date, "limit": 100},
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
    settings = CoreSettings()
    client = BookShellClient(
        base_url=settings.bookshell_api_url,
        token=settings.bookshell_api_token,
        timezone=settings.bookshell_timezone,
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
