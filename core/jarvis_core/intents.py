import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time, timedelta
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


CREATE_PATTERN = r"(?:recu[eé]rdame|a[nñ]ad(?:e|ir|as|a|eme)?|agreg\w*|cr[eé](?:a|ar|ame|e|ad|en)?|apunt\w*|anot\w*|ponme\s+un\s+recordatorio|quiero\s+recordar)"
CREATE_PATTERN_NORMALIZED = r"(?:recuerdame|anad(?:e|ir|as|a|eme)?|agreg\w*|cre(?:a|ar|ame|e|ad|en)?|apunt\w*|anot\w*|ponme\s+un\s+recordatorio|quiero\s+recordar)"
WEEKDAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
HOUR_WORDS = {
    "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuna": 21, "veintiuno": 21,
    "veintidos": 22, "veintitres": 23,
}


@dataclass(frozen=True)
class TimeResolution:
    present: bool
    value: str | None = None
    issue: str | None = None
    candidates: tuple[str, ...] = ()


def _resolve_time(
    text: str, target_date: str | None = None, now: datetime | None = None, *, allow_bare: bool = False,
) -> TimeResolution:
    prefix = r"(?:a\s+las?\s+)?" if allow_bare else r"a\s+las?\s+"
    clock = re.search(rf"\b{prefix}(\d{{1,2}})(?::(\d{{2}}))?\b", text)
    if clock:
        hour, minute = int(clock.group(1)), int(clock.group(2) or 0)
    else:
        spoken = re.search(
            r"\b" + prefix + r"(" + "|".join(HOUR_WORDS)
            + r")(?:\s+(?:(y)\s+(media|medio|cuarto|treinta)|(menos)\s+cuarto|treinta))?\b",
            text,
        )
        if not spoken:
            return TimeResolution(False)
        hour = HOUR_WORDS[spoken.group(1)]
        modifier = spoken.group(3) or ("menos_cuarto" if spoken.group(4) else "")
        if modifier == "menos_cuarto":
            hour = (hour - 1) % 24
            minute = 45
        elif modifier in {"media", "medio", "treinta"} or re.search(rf"\b{spoken.group(1)}\s+treinta\b", spoken.group(0)):
            minute = 30
        elif modifier == "cuarto":
            minute = 15
        else:
            minute = 0
    if hour > 23 or minute > 59:
        return TimeResolution(True, issue="invalid")

    morning = bool(re.search(r"\b(?:de|por)\s+la\s+manana\b|\ba\.?m\.?\b", text))
    afternoon = bool(re.search(r"\b(?:de|por)\s+la\s+(?:tarde|noche)\b|\bp\.?m\.?\b", text))
    if hour > 12:
        hours = [hour]
    elif morning:
        hours = [hour % 12]
    elif afternoon:
        hours = [(hour % 12) + 12]
    else:
        hours = [hour % 12, (hour % 12) + 12]
    candidates = tuple(dict.fromkeys(f"{candidate:02d}:{minute:02d}" for candidate in hours))

    # Without a target date/current time retain the historic first interpretation;
    # production routing always supplies both and applies the safety rules below.
    if not target_date or now is None:
        return TimeResolution(True, candidates[0], candidates=candidates)
    try:
        intended_date = date.fromisoformat(target_date)
    except ValueError:
        return TimeResolution(True, issue="invalid", candidates=candidates)
    if intended_date < now.date():
        return TimeResolution(True, issue="past", candidates=candidates)
    if intended_date > now.date():
        if len(candidates) == 1:
            return TimeResolution(True, candidates[0], candidates=candidates)
        return TimeResolution(True, issue="ambiguous", candidates=candidates)

    future = [
        candidate for candidate in candidates
        if datetime.combine(intended_date, clock_time.fromisoformat(candidate), tzinfo=now.tzinfo) > now
    ]
    if len(future) == 1:
        return TimeResolution(True, future[0], candidates=candidates)
    if len(future) > 1:
        return TimeResolution(True, issue="ambiguous", candidates=tuple(future))
    return TimeResolution(True, issue="past", candidates=candidates)


def _time_clarification(resolution: TimeResolution) -> str:
    if resolution.issue == "past":
        return "Esa hora ya ha pasado hoy. ¿A qué hora, señor?"
    if resolution.issue == "ambiguous" and len(resolution.candidates) >= 2:
        return f"¿Se refiere a las {resolution.candidates[0]} o a las {resolution.candidates[1]}, señor?"
    return "¿A qué hora, señor?"


def _extract_date(text: str, today: date) -> str | None:
    explicit = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if explicit:
        return explicit.group(1)
    if re.search(r"\bmanana\b", text) and not re.search(r"\b(?:de|por)\s+la\s+manana\b", text):
        return (today + timedelta(days=1)).isoformat()
    if re.search(r"\bhoy\b", text):
        return today.isoformat()
    target = next((number for name, number in WEEKDAYS.items() if re.search(rf"\b{name}\b", text)), None)
    return _next_weekday(today, target) if target is not None else None


def _temporal_scope(text: str) -> str | None:
    if re.search(r"\b(?:la\s+)?semana\s+(?:que\s+viene|proxima|siguiente)\b", text):
        return "next_week"
    if re.search(r"\besta\s+semana\b", text):
        return "this_week"
    if re.search(r"\bmanana\b", text) and not re.search(r"\b(?:de|por)\s+la\s+manana\b", text):
        return "tomorrow"
    if re.search(r"\bhoy\b", text):
        return "today"
    return None


def _reminder_title(message: str) -> str:
    title = re.sub(rf"(?is)^.*?\b{CREATE_PATTERN}\b", "", message, count=1).strip()
    title = re.sub(r"(?i)^\s*(?:como\s+)?(?:un\s+)?recordatorio(?:\s+para)?\s*", "", title)
    title = re.sub(r"(?i)\b(?:hoy|mañana|este\s+|el\s+)?(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)\b", " ", title)
    title = re.sub(r"(?i)\b(?:hoy|mañana)\b|\b20\d{2}-\d{2}-\d{2}\b", " ", title)
    title = re.sub(
        r"(?i)\ba\s+las?\s+(?:\d{1,2}(?::\d{2})?|[a-záéíóúñ]+)(?:\s+y\s+(?:media|cuarto))?(?:\s+de\s+la\s+(?:mañana|tarde|noche))?\b",
        " ", title,
    )
    title = re.sub(r"(?i)^\s*(?:para\s+)?(?:(?:de\s+)?que\s+)?(?:tengo\s+)?", "", title)
    title = re.sub(r"\s+", " ", title).strip(" ¿?¡!,.-")
    return title or "Recordatorio"


def _reminder_query(text: str) -> str:
    query = re.sub(
        r"\b(?:jarvis|que|tengo|tiene|algo|para|hoy|manana|esta|este|la|el|de|semana|proxima|siguiente|viene|lunes|martes|miercoles|jueves|viernes|sabado|domingo|recordatori[oa]s?|hay|cuando|guardia)\b",
        " ", text,
    )
    return re.sub(r"\s+", " ", query).strip(" ¿?¡!,.-")


def _reminder_delete_queries(message: str) -> list[str]:
    tail = re.sub(r"(?is)^.*?\b(?:elimina|borra|cancela)\b", "", message, count=1).strip()
    parts = re.split(
        r"(?i)\s+y\s+(?=(?:(?:el|la)\s+)?(?:recordatori[oa]\b|['\"]))",
        tail,
    )
    queries = []
    for part in parts:
        cleaned = re.sub(
            r"(?i)^\s*(?:(?:el|la|los|las)\s+)?recordatori[oa]s?\s*(?:de(?:l)?\s+)?",
            "", part,
        ).strip(" \t\r\n'\"¿?¡!,.-")
        cleaned = re.sub(r"(?i)^que\s+se\s+llama\s+", "", cleaned).strip()
        if cleaned:
            queries.append(cleaned)
    return queries


def route_direct_intent(message: str, today: date, now: datetime | None = None) -> DirectIntent | None:
    text = normalize(message)
    purchased = re.search(
        r"(?is)\bhe\s+comprado\s+(.+?)\s+de\s+([^.,]+?)(?=\s*[.,]|$)", message,
    )
    if purchased and re.search(r"\b(anad|agreg|apunt)", text):
        page_match = re.search(r"\bpagina\s+(\d{1,5})\b", text)
        status = "planned" if re.search(r"\b(?:todavia|aun)\s+no\s+(?:lo\s+)?he\s+empezado\b", text) else "reading"
        return DirectIntent("book_create", "bookshell_create_book", {
            "title": purchased.group(1).strip(), "author": purchased.group(2).strip(),
            "current_page": int(page_match.group(1)) if page_match else 0, "status": status,
        }, domain="books", operation="create")

    checklist_create = re.search(r"(?is)\bcrea\s+(?:una\s+)?(?:nota\s+(?:tipo\s+)?)?checklist\s+(?:llamada|titulada)\s+(.+?)\s+(?:con\s+)?(?:los\s+)?(?:puntos|elementos|tareas)\s*[:：]?\s*(.+)$", message)
    if checklist_create:
        items = [item.strip(" .") for item in re.split(r"\s*[,;]\s*|\s+y\s+(?=[^,;]+$)", checklist_create.group(2), flags=re.I) if item.strip(" .")]
        return DirectIntent("checklist_create", "bookshell_notes_write", {
            "action": "create", "title": checklist_create.group(1).strip(" ."),
            "content": "\n".join(f"- [ ] {item}" for item in items), "tags": ["checklist"],
        }, domain="notes", operation="create")

    note_create = re.search(r"(?is)\bcrea\s+(?:una\s+)?nota\s+(?:llamada|titulada)\s+(.+?)\s+(?:con\s+)?(?:el\s+)?contenido\s*[:：]?\s*(.+)$", message)
    if note_create:
        return DirectIntent("note_create", "bookshell_notes_write", {
            "action": "create", "title": note_create.group(1).strip(" ."),
            "content": note_create.group(2).strip(),
        }, domain="notes", operation="create")

    check_mark = re.search(r"(?is)\b(?:marca|completa)\s+(.+?)\s+(?:en|de)\s+(?:la\s+)?(?:nota\s+)?(.+)$", message)
    if check_mark and ("checklist" in text or "nota" in text):
        return DirectIntent("checklist_mark", "bookshell_notes_write", {
            "action": "update", "title": check_mark.group(2).strip(" ."),
            "check_item": check_mark.group(1).strip(" ."),
        }, domain="notes", operation="update")

    pending_checklist = re.search(r"(?is)\bque\s+(?:queda|falta|esta\s+pendiente)\b.*\b(?:checklist|nota)\s+(.+)$", text)
    if pending_checklist:
        return DirectIntent("checklist_pending", "bookshell_notes_query", {
            "query": pending_checklist.group(1).strip(" .?"), "pending_only": True, "limit": 10,
        }, domain="notes", operation="read")
    page = re.search(
        r"\bpagina(?:\s+(?:a|en))?\s+(\d{1,5})\b|\b(?:voy\s+(?:por|en|a)\s+la|hasta\s+la)\s+(\d{1,5})\b",
        text,
    )
    write_page = page and re.search(
        r"\b(apunt\w*|anot\w*|a\s+nota|actualiz\w*|pon\w*|voy\s+por|he\s+llegado|marc\w*|contar\s+que\s+voy)\b",
        text,
    )
    if write_page:
        arguments: dict[str, Any] = {"page": int(page.group(1) or page.group(2))}
        title_match = re.search(r"\bpagina\s+de\s+([a-z0-9][a-z0-9 ]*?)(?:\s*[.,;]|\s+voy\b|$)", text)
        if title_match:
            arguments["title"] = title_match.group(1).strip()
        return DirectIntent("book_update", "bookshell_update_progress", arguments, domain="books", operation="update")
    if re.search(r"\b(que|cual|por)\b.*\bpagina\b|\bpagina\b.*\b(voy|actual)\b", text):
        return DirectIntent("book_progress", "bookshell_books_query", {"mode": "progress", "limit": 1})
    if re.search(r"\b(que|cual)\b.*\blibro\b.*\b(leo|leyendo|actual)\b|\blibro actual\b", text):
        return DirectIntent("book_current", "bookshell_books_query", {"mode": "current", "limit": 1})
    if re.search(r"\b(?:cual|cuando|que)\b.*\b(?:ultimo|ultima)\b.*\b(?:entrenamiento|sesion)\b|\b(?:ultimo|ultima)\s+(?:entrenamiento|sesion)\b", text):
        return DirectIntent("gym_last", "bookshell_gym_query", {"mode": "last"}, domain="gym", operation="read")
    if re.search(r"\b(registra|anota|apunta|guarda)\b.*\b(gym|gimnasio|entrenamiento)\b", text):
        return DirectIntent("gym_create", "bookshell_gym_write", {
            "action": "create", "date": today.isoformat(), "name": "Entrenamiento", "exercises": [],
        }, domain="gym", operation="create")
    if re.search(r"\bhabitos?\b", text) and not re.search(r"\b(marca|desmarca|completa|anota|registra)\b", text):
        mode = "pending" if re.search(r"\bpendient", text) else "list"
        target_date = _extract_date(text, today) or today.isoformat()
        return DirectIntent(
            "habits_list", "bookshell_habits_query", {"mode": mode, "date": target_date},
            domain="habits", operation="read",
        )
    finance_latest = re.search(r"\b(?:ultimo|ultima)\b.*\b(gasto|ingreso|movimiento)\b", text)
    if finance_latest:
        movement_type = "expense" if finance_latest.group(1) == "gasto" else "income" if finance_latest.group(1) == "ingreso" else None
        arguments = {"mode": "latest"}
        if movement_type:
            arguments["type"] = movement_type
        return DirectIntent(
            "finance_latest", "bookshell_finance_query", arguments,
            domain="finance", operation="read",
        )
    reminder_topic = re.search(r"\b(recordatori[oa]s?|recuerdame|clase|cita|dentista|guardia)\b", text)
    creation = re.search(rf"\b{CREATE_PATTERN_NORMALIZED}\b", text)
    reminder_context = reminder_topic or re.search(r"\b(hoy|manana|lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b", text)

    if reminder_topic and re.search(r"\b(cancela|elimina|borra)\b", text):
        scope = _temporal_scope(text)
        arguments: dict[str, Any] = {"queries": _reminder_delete_queries(message)}
        if scope:
            arguments.update({"scope": scope, "delete_all": bool(re.search(r"\brecordatorios\b", text))})
        return DirectIntent(
            "reminder_delete", arguments=arguments,
            domain="reminders", operation="delete",
        )

    # Explicit write intent must win before any read pattern such as "hoy que tengo".
    if creation and reminder_context:
        arguments: dict[str, Any] = {"title": _reminder_title(message), "minutes_before": 0}
        target_date = _extract_date(text, today)
        time_resolution = _resolve_time(text, target_date, now)
        target_time = time_resolution.value
        missing = tuple(field for field, value in (("date", target_date), ("time", target_time)) if not value)
        if target_date:
            arguments["target_date"] = target_date
        if target_time:
            arguments["target_time"] = target_time
        clarification = "¿Para qué fecha, señor?" if "date" in missing else _time_clarification(time_resolution) if "time" in missing else None
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
        scope = _temporal_scope(text)
        target_date = _extract_date(text, today)
        query = _reminder_query(text)
        arguments: dict[str, Any] = {}
        if scope:
            arguments["scope"] = scope
        elif target_date:
            arguments.update({"from": target_date, "until": target_date})
        if query:
            arguments["query"] = query
        if "guardia" in text:
            arguments["event_type"] = "guardia"
            person = re.search(r"\b(?:tiene|de)\s+([a-z][a-z0-9_-]*)\s+guardia\b", text)
            if person:
                arguments["person"] = person.group(1)
            arguments["temporal_scope"] = "future"
            arguments["status"] = "pending"
            # Guardia/person are structured filters. Reapplying them as one
            # free-text phrase turns the intended AND query into an impossible
            # match for canonical rows such as "Guardia Laura".
            arguments.pop("query", None)
        read_operation = "search" if query else "list"
        return DirectIntent(
            f"reminder_{read_operation}", "bookshell_reminders_query", arguments,
            domain="reminders", operation=read_operation,
        )
    return None


def continue_direct_intent(
    pending: DirectIntent, message: str, today: date, now: datetime | None = None,
) -> DirectIntent | None:
    if pending.kind != "reminder_create":
        return None
    arguments = dict(pending.arguments or {})
    candidate = route_direct_intent(message, today, now)
    time_resolution = TimeResolution(False)
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
        effective_date = target_date or str(arguments.get("target_date") or "") or None
        time_resolution = _resolve_time(text, effective_date, now, allow_bare=True)
        target_time = time_resolution.value
        if target_date:
            arguments["target_date"] = target_date
        if target_time:
            arguments["target_time"] = target_time
    missing = tuple(field for field in ("date", "time") if not arguments.get(f"target_{field}"))
    clarification = "¿Para qué fecha, señor?" if "date" in missing else _time_clarification(time_resolution) if "time" in missing else None
    return DirectIntent(
        "reminder_create", "bookshell_create_reminder", arguments, clarification,
        "reminders", "create", missing,
    )


def is_pending_followup(message: str) -> bool:
    text = normalize(message)
    return bool(
        _resolve_time(text, allow_bare=True).present
        or _extract_date(text, date.today())
        or re.search(r"\b(eso no|no es lo que|te he pedido|te he dicho|no crealo|quiero que lo|anadelo|apuntalo)\b", text)
    )


def is_pending_field_response(pending: DirectIntent, message: str) -> bool:
    """Only resume a pending action when the reply can fill its expected field."""
    text = normalize(message)
    expected = pending.missing_fields[0] if pending.missing_fields else ""
    if expected == "time":
        return bool(
            _resolve_time(text, allow_bare=True).present
            or re.fullmatch(r"\s*(?:por\s+la\s+)?(?:manana|tarde|noche)\s*[.!?]?\s*", text)
        )
    if expected == "date":
        return _extract_date(text, date.today()) is not None
    return False


MONTH_NAMES = (
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _render_reminder_dates(items: list[dict[str, Any]]) -> str:
    dates = []
    for item in items:
        try:
            parsed = date.fromisoformat(str(item.get("targetDate") or ""))
        except ValueError:
            continue
        if parsed not in dates:
            dates.append(parsed)
    dates.sort()
    if not dates:
        return ""
    if len(dates) > 1 and len({(value.year, value.month) for value in dates}) == 1:
        days = " y ".join(f"el {value.day}" for value in dates)
        return f"{days} de {MONTH_NAMES[dates[0].month]}"
    return " y ".join(f"el {value.day} de {MONTH_NAMES[value.month]}" for value in dates)


def render_direct_result(
    kind: str, result: dict[str, Any], *, question: str = "",
    arguments: dict[str, Any] | None = None,
) -> str:
    if kind in {"book_current", "book_progress"}:
        book = result.get("book") or {}
        if not result.get("found") or not book:
            return str(result.get("message") or "No encuentro el libro actual, señor.")
        title, page, pages = book.get("title"), book.get("currentPage"), book.get("pages")
        normalized_question = normalize(question)
        if "ahora" in normalized_question:
            return f"Ahora va por la {page} de {pages}, señor."
        if "musashi" in normalized_question or "libro" in normalized_question:
            return f"Está leyendo {title} y va por la página {page} de {pages}, señor."
        return f"Va por la página {page} de {pages}, señor."
    if kind == "book_update":
        return "Anotado, señor." if result.get("updated") and result.get("verified") else str(result.get("message") or "BookShell no confirmó la escritura, señor.")
    if kind == "book_create":
        if result.get("duplicate"):
            return "Ese libro ya estaba en BookShell, señor."
        return "Libro añadido, señor." if result.get("created") and result.get("verified") else str(result.get("message") or "BookShell no confirmó el libro, señor.")
    if kind in {"note_create", "note_update", "checklist_create", "checklist_mark"}:
        succeeded = (result.get("created") or result.get("updated")) and result.get("verified")
        return "Hecho y verificado en BookShell, señor." if succeeded else str(result.get("message") or "BookShell no confirmó la nota, señor.")
    if kind == "checklist_pending":
        items = [str(item.get("item")) for item in result.get("pendingItems") or []]
        return ("Quedan pendientes: " + "; ".join(items) + ", señor.") if items else "No queda ningún elemento pendiente, señor."
    if kind == "pc_open_url":
        return "Fuente abierta en el navegador, señor." if result.get("opened") else str(result.get("message") or "No pude abrir la fuente, señor.")
    if kind == "gym_last":
        workout = result.get("workout") or {}
        if not workout:
            return str(result.get("message") or "No encuentro entrenamientos registrados, señor.")
        return f"Su último entrenamiento fue {workout.get('name') or 'una sesión'} el {workout.get('date')}, señor."
    if kind == "habits_list":
        items = list(result.get("items") or [])
        if not items:
            return "No tiene hábitos pendientes para esa fecha, señor."
        descriptions = [
            f"{item.get('name')}: {'completado' if item.get('completed') else 'pendiente'}"
            for item in items[:8]
        ]
        return "; ".join(descriptions) + ", señor."
    if kind == "finance_latest":
        movement = result.get("movement") or {}
        if not movement:
            return "No encuentro movimientos financieros coincidentes, señor."
        try:
            amount = f"{float(movement.get('amount')):.2f}"
        except (TypeError, ValueError):
            amount = str(movement.get("amount") or "importe desconocido")
        currency = movement.get("currency") or movement.get("originalCurrency") or ""
        category = movement.get("category") or movement.get("description") or "sin categoría"
        movement_date = movement.get("date") or "fecha desconocida"
        return f"El último movimiento fue {amount} {currency} en {category}, el {movement_date}, señor."
    if kind in {"reminders_today", "reminder_list", "reminder_search"}:
        items = list(result.get("items") or [])
        arguments = arguments or {}
        scope = str(result.get("range") or "today")
        label = {
            "today": "hoy", "tomorrow": "mañana", "this_week": "esta semana",
            "next_week": "la semana que viene",
        }.get(scope, "ese periodo")
        if not items:
            return f"No tiene recordatorios para {label}, señor."
        if arguments.get("event_type") == "guardia":
            rendered_dates = _render_reminder_dates(items)
            subject = str(arguments.get("person") or "Laura").capitalize()
            if rendered_dates:
                count = "una guardia" if len(items) == 1 else f"{len(items)} guardias"
                return f"{subject} tiene {count} próximas: {rendered_dates}, señor."
        descriptions = []
        for item in items[:5]:
            description = str(item.get("title") or "Recordatorio")
            try:
                target_date = date.fromisoformat(str(item.get("targetDate") or ""))
                description += f" el {target_date.day} de {MONTH_NAMES[target_date.month]}"
            except ValueError:
                pass
            if item.get("targetTime"):
                description += f" a las {item['targetTime']}"
            descriptions.append(description)
        return "; ".join(descriptions) + ", señor."
    if kind == "reminder_create":
        return "Recordatorio creado, señor." if result.get("created") and result.get("verified") else str(result.get("message") or "BookShell no confirmó la escritura, señor.")
    return "Hecho, señor."
