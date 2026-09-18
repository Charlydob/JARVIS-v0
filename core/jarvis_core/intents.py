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
    domain: str | None = None
    operation: str | None = None
    missing_fields: tuple[str, ...] = ()


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode()


def _next_weekday(today: date, weekday: int) -> str:
    days = (weekday - today.weekday()) % 7
    return (today + timedelta(days=days or 7)).isoformat()


CREATE_PATTERN = r"(?:recu[eé]rdame|a[nñ]ad(?:e|ir|as|a|eme)?|agreg\w*|cre\w*|apunt\w*|anot\w*|ponme\s+un\s+recordatorio|quiero\s+recordar)"
CREATE_PATTERN_NORMALIZED = r"(?:recuerdame|anad(?:e|ir|as|a|eme)?|agreg\w*|cre\w*|apunt\w*|anot\w*|ponme\s+un\s+recordatorio|quiero\s+recordar)"
WEEKDAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
HOUR_WORDS = {
    "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuna": 21, "veintiuno": 21,
    "veintidos": 22, "veintitres": 23,
}


def _extract_time(text: str) -> str | None:
    clock = re.search(r"\ba\s+las?\s+(\d{1,2})(?::(\d{2}))?\b", text)
    if clock:
        hour, minute = int(clock.group(1)), int(clock.group(2) or 0)
    else:
        spoken = re.search(r"\ba\s+las?\s+(" + "|".join(HOUR_WORDS) + r")(?:\s+y\s+(media|cuarto))?\b", text)
        if not spoken:
            return None
        hour = HOUR_WORDS[spoken.group(1)]
        minute = 30 if spoken.group(2) == "media" else 15 if spoken.group(2) == "cuarto" else 0
    return f"{hour:02d}:{minute:02d}" if hour <= 23 and minute <= 59 else None


def _extract_date(text: str, today: date) -> str | None:
    explicit = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if explicit:
        return explicit.group(1)
    if "manana" in text:
        return (today + timedelta(days=1)).isoformat()
    if re.search(r"\bhoy\b", text):
        return today.isoformat()
    target = next((number for name, number in WEEKDAYS.items() if re.search(rf"\b{name}\b", text)), None)
    return _next_weekday(today, target) if target is not None else None


def _reminder_title(message: str) -> str:
    title = re.sub(rf"(?is)^.*?\b{CREATE_PATTERN}\b", "", message, count=1).strip()
    title = re.sub(r"(?i)^\s*(?:como\s+)?(?:un\s+)?recordatorio(?:\s+para)?\s*", "", title)
    title = re.sub(r"(?i)\b(?:hoy|mañana|este\s+|el\s+)?(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)\b", " ", title)
    title = re.sub(r"(?i)\b(?:hoy|mañana)\b|\b20\d{2}-\d{2}-\d{2}\b", " ", title)
    title = re.sub(r"(?i)\ba\s+las?\s+(?:\d{1,2}(?::\d{2})?|[a-záéíóúñ]+)(?:\s+y\s+(?:media|cuarto))?\b", " ", title)
    title = re.sub(r"(?i)^\s*(?:para\s+)?(?:que\s+tengo\s+)?", "", title)
    title = re.sub(r"\s+", " ", title).strip(" ¿?¡!,.-")
    return title or "Recordatorio"


def _reminder_query(text: str) -> str:
    query = re.sub(
        r"\b(?:que|tengo|algo|para|hoy|manana|este|el|lunes|martes|miercoles|jueves|viernes|sabado|domingo|recordatorios?|hay|cuando)\b",
        " ", text,
    )
    return re.sub(r"\s+", " ", query).strip(" ¿?¡!,.-")


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
    reminder_topic = re.search(r"\b(recordatorio|recuerdame|clase|cita|dentista|guardia)\b", text)
    creation = re.search(rf"\b{CREATE_PATTERN_NORMALIZED}\b", text)
    reminder_context = reminder_topic or re.search(r"\b(hoy|manana|lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b", text)

    # Explicit write intent must win before any read pattern such as "hoy que tengo".
    if creation and reminder_context:
        arguments: dict[str, Any] = {"title": _reminder_title(message), "minutes_before": 0}
        target_date = _extract_date(text, today)
        target_time = _extract_time(text)
        missing = tuple(field for field, value in (("date", target_date), ("time", target_time)) if not value)
        if target_date:
            arguments["target_date"] = target_date
        if target_time:
            arguments["target_time"] = target_time
        clarification = "¿Para qué fecha, señor?" if "date" in missing else "¿A qué hora, señor?" if "time" in missing else None
        return DirectIntent(
            "reminder_create", "bookshell_create_reminder", arguments, clarification,
            "reminders", "create", missing,
        )

    if reminder_topic or re.search(r"\b(que tengo|tengo algo)\b", text):
        operation = "update" if re.search(r"\b(cambia|mueve|reprograma|actualiza)\b", text) else (
            "delete" if re.search(r"\b(cancela|elimina|borra)\b", text) else (
                "complete" if re.search(r"\b(hecho|completa|terminado)\b", text) else "read"
            )
        )
        if operation != "read":
            return DirectIntent(f"reminder_{operation}", domain="reminders", operation=operation)
        target_date = _extract_date(text, today)
        query = _reminder_query(text)
        arguments: dict[str, Any] = {}
        if target_date:
            arguments.update({"from": target_date, "until": target_date})
        if query:
            arguments["query"] = query
        read_operation = "search" if query else "list"
        return DirectIntent(
            f"reminder_{read_operation}", "bookshell_reminders_query", arguments,
            domain="reminders", operation=read_operation,
        )
    return None


def continue_direct_intent(pending: DirectIntent, message: str, today: date) -> DirectIntent | None:
    if pending.kind != "reminder_create":
        return None
    arguments = dict(pending.arguments or {})
    candidate = route_direct_intent(message, today)
    if candidate and candidate.kind == pending.kind:
        candidate_arguments = dict(candidate.arguments or {})
        if candidate_arguments.get("title") not in {None, "Recordatorio"}:
            arguments["title"] = candidate_arguments["title"]
        for field in ("target_date", "target_time"):
            if candidate_arguments.get(field):
                arguments[field] = candidate_arguments[field]
    else:
        text = normalize(message)
        target_date = _extract_date(text, today)
        target_time = _extract_time(text)
        if target_date:
            arguments["target_date"] = target_date
        if target_time:
            arguments["target_time"] = target_time
    missing = tuple(field for field in ("date", "time") if not arguments.get(f"target_{field}"))
    clarification = "¿Para qué fecha, señor?" if "date" in missing else "¿A qué hora, señor?" if "time" in missing else None
    return DirectIntent(
        "reminder_create", "bookshell_create_reminder", arguments, clarification,
        "reminders", "create", missing,
    )


def is_pending_followup(message: str) -> bool:
    text = normalize(message)
    return bool(
        _extract_time(text)
        or _extract_date(text, date.today())
        or re.search(r"\b(eso no|no es lo que|te he pedido|te he dicho|no crealo|quiero que lo|anadelo|apuntalo)\b", text)
    )


def render_direct_result(kind: str, result: dict[str, Any]) -> str:
    if kind in {"book_current", "book_progress"}:
        book = result.get("book") or {}
        if not result.get("found") or not book:
            return str(result.get("message") or "No encuentro el libro actual, señor.")
        title, page, pages = book.get("title"), book.get("currentPage"), book.get("pages")
        return f"Está leyendo {title} y va por la página {page} de {pages}, señor."
    if kind == "book_update":
        return "Anotado, señor." if result.get("updated") and result.get("verified") else "No se pudo guardar, señor."
    if kind in {"reminders_today", "reminder_list", "reminder_search"}:
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
