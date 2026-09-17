import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class DirectIntent:
    kind: str
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    clarification: str | None = None


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode()


def _next_weekday(today: date, weekday: int) -> str:
    days = (weekday - today.weekday()) % 7
    return (today + timedelta(days=days or 7)).isoformat()


def _reminder_title(message: str) -> str:
    title = re.sub(r"(?i)^.*?\b(?:recu[eé]rdame|crea|a[nñ]ade|apunta)\b(?:\s+un\s+recordatorio)?(?:\s+de|\s+para)?\s*", "", message).strip()
    title = re.split(r"(?i)\b(?:hoy|mañana|este\s+viernes|el\s+viernes|a\s+las?\s+\d{1,2})\b", title, maxsplit=1)[0].strip(" ,.-")
    return title or "Recordatorio"


def route_direct_intent(message: str, today: date) -> DirectIntent | None:
    text = normalize(message)
    page = re.search(r"\bpagina\s+(\d{1,5})\b", text)
    write_page = page and re.search(r"\b(apunta|anota|actualiza|pon|voy por|he llegado|marca)\b", text)
    if write_page:
        return DirectIntent("book_update", "bookshell_update_progress", {"page": int(page.group(1))})
    if re.search(r"\b(que|cual|por)\b.*\bpagina\b|\bpagina\b.*\b(voy|actual)\b", text):
        return DirectIntent("book_progress", "bookshell_books_query", {"mode": "progress", "limit": 1})
    if re.search(r"\b(que|cual)\b.*\blibro\b.*\b(leo|leyendo|actual)\b|\blibro actual\b", text):
        return DirectIntent("book_current", "bookshell_books_query", {"mode": "current", "limit": 1})
    if re.search(r"\b(que tengo|recordatorios?)\b.*\b(hoy|today)\b", text):
        return DirectIntent("reminders_today", "bookshell_reminders_query", {"scope": "today"})

    reminder_topic = re.search(r"\b(recordatorio|recuerdame|clase|cita|dentista|guardia)\b", text)
    question = re.search(r"\b(cuando|que tengo|cual)\b", text)
    creation = re.search(r"\b(recuerdame|crea|anade|apunta)\b", text) or ("clase" in text and not question)
    if reminder_topic and creation:
        arguments: dict[str, Any] = {"title": _reminder_title(message), "minutes_before": 0}
        target_date: str | None = None
        relative_day: str | None = None
        explicit_date = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
        if explicit_date:
            target_date = explicit_date.group(1)
        elif "manana" in text:
            relative_day = "tomorrow"
        elif re.search(r"\bhoy\b", text):
            relative_day = "today"
        else:
            weekdays = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
            target = next((number for name, number in weekdays.items() if re.search(rf"\b{name}\b", text)), None)
            if target is not None:
                target_date = _next_weekday(today, target)
        if not target_date and not relative_day:
            clock = re.search(r"\ba\s+las?\s+(\d{1,2})(?::(\d{2}))?\b", text)
            if clock:
                arguments["target_time"] = f"{int(clock.group(1)):02d}:{int(clock.group(2) or 0):02d}"
            return DirectIntent("reminder_create", "bookshell_create_reminder", arguments, "¿Para qué fecha, señor?")
        if target_date:
            arguments["target_date"] = target_date
        if relative_day:
            arguments["relative_day"] = relative_day
        clock = re.search(r"\ba\s+las?\s+(\d{1,2})(?::(\d{2}))?\b", text)
        if not clock:
            return DirectIntent("reminder_create", "bookshell_create_reminder", arguments, "¿A qué hora, señor?")
        hour, minute = int(clock.group(1)), int(clock.group(2) or 0)
        if hour > 23 or minute > 59:
            return DirectIntent("reminder_create", "bookshell_create_reminder", arguments, "¿A qué hora, señor?")
        arguments["target_time"] = f"{hour:02d}:{minute:02d}"
        return DirectIntent("reminder_create", "bookshell_create_reminder", arguments)
    return None


def continue_direct_intent(pending: DirectIntent, message: str, today: date) -> DirectIntent | None:
    if pending.kind != "reminder_create":
        return None
    arguments = dict(pending.arguments or {})
    pieces = [f"Recuérdame {arguments.get('title') or 'recordatorio'}", message]
    if arguments.get("target_date"):
        pieces.append(str(arguments["target_date"]))
    elif arguments.get("relative_day") == "tomorrow":
        pieces.append("mañana")
    elif arguments.get("relative_day") == "today":
        pieces.append("hoy")
    if arguments.get("target_time"):
        pieces.append(f"a las {arguments['target_time']}")
    completed = route_direct_intent(" ".join(pieces), today)
    if completed and completed.kind == pending.kind:
        return completed
    return pending


def render_direct_result(kind: str, result: dict[str, Any]) -> str:
    if kind in {"book_current", "book_progress"}:
        book = result.get("book") or {}
        if not result.get("found") or not book:
            return str(result.get("message") or "No encuentro el libro actual, señor.")
        title, page, pages = book.get("title"), book.get("currentPage"), book.get("pages")
        return f"Está leyendo {title} y va por la página {page} de {pages}, señor."
    if kind == "book_update":
        return "Anotado, señor." if result.get("updated") and result.get("verified") else "No se pudo guardar, señor."
    if kind == "reminders_today":
        items = list(result.get("items") or [])
        if not items:
            return "No tiene recordatorios para hoy, señor."
        descriptions = [
            f"{item.get('title')}{' a las ' + str(item.get('targetTime')) if item.get('targetTime') else ''}"
            for item in items[:5]
        ]
        return "; ".join(descriptions) + ", señor."
    if kind == "reminder_create":
        return "Recordatorio creado, señor." if result.get("created") and result.get("verified") else "No se pudo guardar, señor."
    return "Hecho, señor."
