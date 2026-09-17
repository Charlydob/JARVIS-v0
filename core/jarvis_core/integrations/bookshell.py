import os
import time
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from jarvis_core.tools import Tool, ToolRegistry


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

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            transport=self.transport,
            timeout=httpx.Timeout(15.0, connect=5.0),
        ) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return dict(response.json())

    async def books(self) -> dict[str, dict[str, Any]]:
        payload = await self._request("GET", "/data/books/books")
        data = payload.get("data") or {}
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
        return {"found": True, "book": self._summary(chosen)}

    async def update_progress(self, page: int, title: str | None = None, book_id: str | None = None) -> dict[str, Any]:
        all_books = await self.books()
        if book_id:
            selected = all_books.get(book_id)
            selection = {"found": bool(selected), "book": self._summary({"id": book_id, **selected}) if selected else None}
        else:
            selection = await self.current_book(title)
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
        await self._request(
            "POST", f"/data/transaction/books/books/{identifier}",
            json={"currentValue": current, "nextValue": updated},
        )
        log_updated = True
        delta = target - old_page
        if delta:
            day = datetime.now(ZoneInfo(self.timezone)).date().isoformat()
            path = f"/data/books/readingLog/{day}/{identifier}"
            try:
                log_payload = await self._request("GET", path)
                current_log = int(log_payload.get("data") or 0)
                await self._request(
                    "POST", f"/data/transaction/books/readingLog/{day}/{identifier}",
                    json={"currentValue": log_payload.get("data"), "nextValue": current_log + delta},
                )
            except httpx.HTTPError:
                log_updated = False
        return {
            "updated": True,
            "book": self._summary({"id": identifier, **updated}),
            "previousPage": old_page,
            "readingLogUpdated": log_updated,
        }

    async def create_reminder(self, arguments: dict[str, Any]) -> dict[str, Any]:
        minutes = max(0, int(arguments.get("minutes_before") or 0))
        body = {
            "title": str(arguments["title"]).strip(),
            "description": str(arguments.get("description") or "").strip(),
            "emoji": "⏰",
            "type": "normal",
            "targetDate": str(arguments["target_date"]),
            "targetTime": str(arguments.get("target_time") or "") or None,
            "timezone": str(arguments.get("timezone") or self.timezone),
            "source": {"type": "manual", "metadata": {"createdBy": "jarvis"}},
            "alerts": [{"mode": "relative", "minutesBefore": minutes, "channel": "telegram"}],
            "status": "pending",
        }
        payload = await self._request("POST", "/reminders", json=body)
        return {"created": bool(payload.get("created", True)), "reminder": payload.get("reminder")}

    @staticmethod
    def _ordered_books(books: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        result = [{"id": identifier, **book} for identifier, book in books.items() if isinstance(book, dict)]
        return sorted(result, key=lambda book: int(book.get("updatedAt") or 0), reverse=True)

    @staticmethod
    def _summary(book: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": book.get("id"),
            "title": book.get("title"),
            "author": book.get("author"),
            "currentPage": int(book.get("currentPage") or 0),
            "pages": int(book.get("pages") or 0),
            "status": book.get("status"),
            "updatedAt": book.get("updatedAt"),
        }


def register_tools(registry: ToolRegistry) -> None:
    client = BookShellClient(
        base_url=os.getenv("JARVIS_BOOKSHELL_API_URL", "https://api-bookshell.charlydob.com"),
        token=os.getenv("JARVIS_BOOKSHELL_API_TOKEN", ""),
        timezone=os.getenv("JARVIS_BOOKSHELL_TIMEZONE", "Europe/Zurich"),
    )

    registry.register(Tool(
        "bookshell_get_current_book",
        "Consulta BookShell cuando el usuario pregunta qué libro estaba leyendo, cuál fue el último libro o por qué página iba. Se puede indicar un título aproximado.",
        {"type": "object", "properties": {"title": {"type": "string", "description": "Título opcional, puede ser aproximado"}}},
        lambda args: client.current_book(args.get("title")),
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
                "target_time": {"type": "string", "description": "Hora HH:MM"},
                "timezone": {"type": "string", "default": "Europe/Zurich"},
                "minutes_before": {"type": "integer", "minimum": 0, "description": "Aviso previo en minutos; 0 si no se pidió antelación"},
            },
            "required": ["title", "target_date"],
        },
        client.create_reminder,
    ))
