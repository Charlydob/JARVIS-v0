from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from jarvis_core.intents import continue_direct_intent, is_pending_field_response, route_direct_intent


def test_common_books_and_reminder_intents_are_deterministic() -> None:
    today = date(2026, 9, 17)  # Thursday
    assert route_direct_intent("¿Qué libro estoy leyendo?", today).kind == "book_current"
    assert route_direct_intent("¿Por qué página voy?", today).kind == "book_progress"
    update = route_direct_intent("Apunta página 220", today)
    assert update.tool == "bookshell_update_progress"
    assert update.arguments == {"page": 220}
    reminder_list = route_direct_intent("¿Qué tengo hoy?", today)
    assert reminder_list.domain == "reminders"
    assert reminder_list.operation == "list"
    gym = route_direct_intent("¿Cuál es mi último entrenamiento?", today)
    assert gym.tool == "bookshell_gym_query"
    assert gym.arguments == {"mode": "last"}


def test_required_real_phrases_route_with_exact_write_and_filters() -> None:
    zone = ZoneInfo("Europe/Zurich")
    now = datetime(2026, 9, 20, 12, 0, tzinfo=zone)

    book = route_direct_intent("Anota que voy por la página 229.", now.date(), now)
    assert (book.tool, book.operation, book.arguments) == (
        "bookshell_update_progress", "update", {"page": 229},
    )

    reminder = route_direct_intent(
        "Crea un recordatorio para mañana a las cuatro de la tarde de que llega el paquete de Apple.",
        now.date(), now,
    )
    assert (reminder.tool, reminder.operation, reminder.arguments) == (
        "bookshell_create_reminder", "create", {
            "title": "llega el paquete de Apple", "minutes_before": 0,
            "target_date": "2026-09-21", "target_time": "16:00",
        },
    )

    week = route_direct_intent("¿Qué tengo esta semana?", now.date(), now)
    assert week.arguments == {"scope": "this_week"}

    guard = route_direct_intent("¿Cuándo tiene Laura guardia?", now.date(), now)
    assert guard.arguments == {
        "event_type": "guardia", "person": "laura", "temporal_scope": "future", "status": "pending",
    }


@pytest.mark.parametrize("message,page", [
    ("anota que voy en la página 230", 230),
    ("apunta que voy por la 229", 229),
    ("actualiza la página a 229", 229),
    ("pon que voy por la 229", 229),
    ("voy por la 229, anótalo", 229),
])
def test_natural_book_updates_win_over_reads(message: str, page: int) -> None:
    intent = route_direct_intent(message, date(2026, 9, 20))
    assert (intent.tool, intent.operation, intent.arguments) == (
        "bookshell_update_progress", "update", {"page": page},
    )
    read = route_direct_intent("¿En qué página voy?", date(2026, 9, 20))
    assert (read.tool, read.operation) == ("bookshell_books_query", None)


def test_reminder_without_time_waits_and_delete_routes_to_search() -> None:
    now = datetime(2026, 9, 20, 12, 0, tzinfo=ZoneInfo("Europe/Zurich"))
    create = route_direct_intent("Recuérdame mañana comprar leche", now.date(), now)
    assert create.clarification == "¿A qué hora, señor?"
    assert create.missing_fields == ("time",)
    assert "target_time" not in create.arguments

    delete = route_direct_intent("Elimina el recordatorio del paquete de Apple", now.date(), now)
    assert (delete.kind, delete.operation) == ("reminder_delete", "delete")
    assert delete.arguments == {"queries": ["paquete de Apple"]}
    multiple = route_direct_intent(
        "Elimina el recordatorio del paquete de Apple y el recordatorio 'está ese recordatorio creado o no'",
        now.date(), now,
    )
    assert multiple.arguments == {"queries": ["paquete de Apple", "está ese recordatorio creado o no"]}
    named = route_direct_intent("Elimina el recordatorio que se llama que me llega el paquete de Apple", now.date(), now)
    assert named.arguments == {"queries": ["que me llega el paquete de Apple"]}


def test_book_note_and_checklist_writes_are_deterministic() -> None:
    today = date(2026, 9, 20)
    book = route_direct_intent(
        "He comprado El extranjero de Albert Camus. Añádelo, página 0, todavía no lo he empezado.", today,
    )
    assert book.tool == "bookshell_create_book"
    assert book.arguments == {"title": "El extranjero", "author": "Albert Camus", "current_page": 0, "status": "planned"}
    note = route_direct_intent(
        "Crea una nota titulada Prueba integración JARVIS con el contenido Primera línea", today,
    )
    assert note.tool == "bookshell_notes_write"
    assert note.arguments["content"] == "Primera línea"
    update = route_direct_intent(
        "Modifica Prueba integración JARVIS y añade: segunda línea", today,
    )
    assert update.arguments == {
        "action": "update", "title": "Prueba integración JARVIS", "append_content": "segunda línea",
    }
    checklist = route_direct_intent(
        "Crea una checklist llamada Checklist laboratorio con los puntos: conectar ESP32, probar relé, revisar fuente", today,
    )
    assert checklist.kind == "checklist_create"
    assert checklist.arguments["content"].splitlines() == [
        "- [ ] conectar ESP32", "- [ ] probar relé", "- [ ] revisar fuente",
    ]


def test_natural_notes_phrases_win_and_book_reading_is_an_upsert() -> None:
    today = date(2026, 9, 20)
    note = route_direct_intent("crea una nota montaje checkout", today)
    assert (note.domain, note.kind, note.arguments) == (
        "notes", "note_create", {"action": "create", "title": "montaje checkout", "content": ""},
    )
    checklist = route_direct_intent("crea un checklist Mejoras para JARVIS", today)
    assert checklist.kind == "checklist_create"
    assert checklist.arguments == {
        "action": "create", "title": "Mejoras para JARVIS", "content": "", "tags": ["checklist"],
        "category": "checklist",
    }
    folder = route_direct_intent("crea una carpeta en notas llamada Mejoras para JARVIS", today)
    assert (folder.kind, folder.tool, folder.arguments) == (
        "note_folder_create", "bookshell_notes_folder_create",
        {"name": "Mejoras para JARVIS"},
    )
    reading = route_direct_intent("estoy leyendo El extranjero de Albert Camus", today)
    assert (reading.kind, reading.operation, reading.arguments) == (
        "book_reading", "update",
        {"title": "El extranjero", "author": "Albert Camus", "current_page": 0, "status": "reading"},
    )
    explicit_add = route_direct_intent(
        "quiero que lo anotes añadiendo el libro El extranjero de Albert Camus, página 0", today,
    )
    assert (explicit_add.kind, explicit_add.tool, explicit_add.arguments) == (
        "book_reading", "bookshell_create_book",
        {"title": "El extranjero", "author": "Albert Camus", "current_page": 0, "status": "reading"},
    )


def test_natural_reminder_date_and_web_pages_do_not_collide_with_books() -> None:
    now = datetime(2026, 9, 20, 12, 0, tzinfo=ZoneInfo("Europe/Zurich"))
    reminder = route_direct_intent(
        "crea un recordatorio para el 12 de abril que se llame mi cumpleaños", now.date(), now,
    )
    assert reminder.kind == "reminder_create"
    assert reminder.arguments["title"] == "mi cumpleaños"
    assert reminder.arguments["target_date"] == "2027-04-12"
    assert reminder.missing_fields == ("time",)
    assert reminder.clarification == "¿A qué hora, señor?"
    web = route_direct_intent("me gustaría que buscase su página de wikipedia", now.date(), now)
    assert web is not None and web.tool == "web_search"
    assert web.domain == "web"
    pc = route_direct_intent("abre https://es.wikipedia.org/ en el ordenador", now.date(), now)
    assert (pc.kind, pc.tool, pc.arguments["url"]) == ("pc_open_url", "pc_open_url", "https://es.wikipedia.org/")


def test_book_write_keeps_title_and_gym_write_wins_over_read() -> None:
    today = date(2026, 9, 19)
    book = route_direct_intent("Actualiza la página de Musashi. Voy en la 222.", today)
    assert book is not None
    assert book.tool == "bookshell_update_progress"
    assert book.arguments == {"page": 222, "title": "musashi"}
    gym = route_direct_intent("Registra que fui al gym hoy.", today)
    assert gym is not None
    assert gym.tool == "bookshell_gym_write"
    assert gym.operation == "create"


def test_guardia_search_uses_structured_subject_and_event_type() -> None:
    intent = route_direct_intent("¿Cuándo tiene Laura guardia?", date(2026, 9, 19))
    assert intent is not None
    assert intent.tool == "bookshell_reminders_query"
    assert intent.arguments["event_type"] == "guardia"
    assert intent.arguments["person"] == "laura"
    assert intent.arguments["temporal_scope"] == "future"
    assert intent.arguments["status"] == "pending"
    assert "query" not in intent.arguments


def test_common_stt_gender_variant_still_routes_without_phrase_substitution() -> None:
    intent = route_direct_intent("¿Qué recordatorias tengo hoy?", date(2026, 9, 19))
    assert intent is not None
    assert intent.tool == "bookshell_reminders_query"
    assert intent.arguments == {"scope": "today"}


def test_habits_today_uses_deterministic_read_route() -> None:
    intent = route_direct_intent("¿Qué hábitos tengo hoy?", date(2026, 9, 19))
    assert intent is not None
    assert (intent.domain, intent.operation, intent.tool) == ("habits", "read", "bookshell_habits_query")
    assert intent.arguments == {"mode": "list", "date": "2026-09-19"}


def test_latest_expense_uses_deterministic_read_route() -> None:
    intent = route_direct_intent("¿Cuál es mi último gasto?", date(2026, 9, 19))
    assert intent is not None
    assert (intent.domain, intent.operation, intent.tool) == ("finance", "read", "bookshell_finance_query")
    assert intent.arguments == {"mode": "latest", "type": "expense"}


def test_friday_is_resolved_and_missing_time_is_requested() -> None:
    today = date(2026, 9, 17)  # Thursday
    missing = route_direct_intent("Añade clase de alemán el viernes", today)
    assert missing.clarification == "¿A qué hora, señor?"
    complete = route_direct_intent("Recuérdame clase de alemán el viernes a las 18:30", today)
    assert complete.arguments["target_date"] == "2026-09-18"
    assert complete.arguments["target_time"] == "18:30"


def test_same_weekday_means_next_week_not_today() -> None:
    complete = route_direct_intent("Recuérdame clase el viernes a las 18", date(2026, 9, 18))
    assert complete.arguments["target_date"] == "2026-09-25"


def test_reminder_clarification_preserves_date_and_title() -> None:
    today = date(2026, 9, 17)  # Thursday
    pending = route_direct_intent("Añade clase de alemán el viernes", today)
    complete = continue_direct_intent(pending, "A las 18", today)
    assert complete.clarification is None
    assert complete.arguments == {
        "title": "clase de alemán",
        "minutes_before": 0,
        "target_date": "2026-09-18",
        "target_time": "18:00",
    }


@pytest.mark.parametrize(
    ("message", "operation", "clarification", "expected"),
    [
        (
            "¿Podrías añadir como recordatorio hoy que tengo clase de alemán?",
            "create", "¿A qué hora, señor?",
            {"title": "clase de alemán", "target_date": "2026-09-18"},
        ),
        (
            "Esto no es lo que te he pedido a Jarvis, te he pedido que añadas un recordatorio para hoy, clase de alemán.",
            "create", "¿A qué hora, señor?",
            {"title": "clase de alemán", "target_date": "2026-09-18"},
        ),
        ("¿Qué tengo para hoy?", "list", None, {"scope": "today"}),
        (
            "Recuérdame comprar leche mañana a las 18:00.",
            "create", None,
            {"title": "comprar leche", "target_date": "2026-09-19", "target_time": "18:00"},
        ),
        (
            "Apunta dentista el viernes a las diez.",
            "create", None,
            {"title": "dentista", "target_date": "2026-09-25", "target_time": "10:00"},
        ),
        (
            "¿Tengo dentista el viernes?",
            "search", None,
            {"query": "dentista", "from": "2026-09-25", "until": "2026-09-25"},
        ),
    ],
)
def test_exact_reminder_operation_routes(
    message: str, operation: str, clarification: str | None, expected: dict,
) -> None:
    intent = route_direct_intent(message, date(2026, 9, 18))
    assert intent is not None
    assert intent.domain == "reminders"
    assert intent.operation == operation
    assert intent.clarification == clarification
    for key, value in expected.items():
        assert intent.arguments[key] == value


@pytest.mark.parametrize(
    ("message", "operation"),
    [
        ("Cambia la clase de alemán a las 18:00", "update"),
        ("Cancela la clase de alemán", "delete"),
        ("Hecho lo del dentista", "complete"),
    ],
)
def test_reminder_mutations_keep_domain_and_operation(message: str, operation: str) -> None:
    intent = route_direct_intent(message, date(2026, 9, 18))
    assert intent.domain == "reminders"
    assert intent.operation == operation


def test_exact_conversational_repair_keeps_pending_create() -> None:
    today = date(2026, 9, 18)
    pending = route_direct_intent("¿Podrías añadir como recordatorio hoy que tengo clase de alemán?", today)
    repaired = continue_direct_intent(
        pending,
        "Esto no es lo que te he pedido a Jarvis, te he pedido que añadas un recordatorio para hoy, clase de alemán.",
        today,
    )
    assert repaired.domain == "reminders"
    assert repaired.operation == "create"
    assert repaired.arguments["title"] == "clase de alemán"
    assert repaired.arguments["target_date"] == "2026-09-18"
    assert repaired.missing_fields == ("time",)
    assert repaired.clarification == "¿A qué hora, señor?"


def test_spoken_hour_chooses_only_future_interpretation_for_today() -> None:
    zone = ZoneInfo("Europe/Zurich")
    now = datetime(2026, 9, 18, 8, 30, tzinfo=zone)
    pending = route_direct_intent("Anota que hoy tengo clase de alemán", now.date(), now)
    complete = continue_direct_intent(pending, "A las cinco y media", now.date(), now)
    assert complete.arguments["target_time"] == "17:30"
    assert complete.clarification is None


def test_spoken_hour_asks_when_all_today_interpretations_are_past() -> None:
    zone = ZoneInfo("Europe/Zurich")
    now = datetime(2026, 9, 18, 18, 30, tzinfo=zone)
    pending = route_direct_intent("Anota que hoy tengo clase de alemán", now.date(), now)
    complete = continue_direct_intent(pending, "A las cinco y media hoy", now.date(), now)
    assert "target_time" not in complete.arguments
    assert complete.clarification == "Esa hora ya ha pasado hoy. ¿A qué hora, señor?"


def test_explicit_past_morning_is_not_created_and_24_hour_time_is_direct() -> None:
    zone = ZoneInfo("Europe/Zurich")
    now = datetime(2026, 9, 18, 8, 30, tzinfo=zone)
    pending = route_direct_intent("Anota que hoy tengo clase de alemán", now.date(), now)
    morning = continue_direct_intent(pending, "A las cinco y media de la mañana", now.date(), now)
    assert "target_time" not in morning.arguments
    assert morning.clarification == "Esa hora ya ha pasado hoy. ¿A qué hora, señor?"

    direct = route_direct_intent("Anota hoy clase de alemán a las 17:30", now.date(), now)
    assert direct.arguments["target_time"] == "17:30"
    assert direct.clarification is None


@pytest.mark.parametrize(
    ("message", "scope"),
    [
        ("¿Qué recordatorios tengo hoy?", "today"),
        ("¿Qué recordatorios tengo mañana?", "tomorrow"),
        ("¿Qué recordatorios tengo esta semana?", "this_week"),
        ("¿Qué recordatorios tengo la semana que viene?", "next_week"),
    ],
)
def test_reminder_temporal_scopes_are_not_reused_or_turned_into_queries(message: str, scope: str) -> None:
    intent = route_direct_intent(message, date(2026, 9, 18))
    assert intent is not None
    assert intent.arguments == {"scope": scope}
    assert intent.operation == "list"


def test_wake_word_is_not_sent_as_a_bookshell_search_filter() -> None:
    intent = route_direct_intent("¿Qué recordatorios tengo mañana, JARVIS?", date(2026, 9, 19))
    assert intent is not None
    assert intent.arguments == {"scope": "tomorrow"}


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("cinco", "17:00"),
        ("cinco y media", "17:30"),
        ("cinco y medio", "17:30"),
        ("cinco y cuarto", "17:15"),
        ("seis menos cuarto", "17:45"),
        ("17:30", "17:30"),
        ("cinco treinta", "17:30"),
    ],
)
def test_pending_accepts_spoken_spanish_times(reply: str, expected: str) -> None:
    zone = ZoneInfo("Europe/Zurich")
    now = datetime(2026, 9, 18, 8, 30, tzinfo=zone)
    pending = route_direct_intent("Crea un recordatorio para hoy", now.date(), now)
    assert is_pending_field_response(pending, reply) is True
    complete = continue_direct_intent(pending, reply, now.date(), now)
    assert complete.arguments["target_time"] == expected
    assert complete.clarification is None


def test_unrelated_complete_intent_does_not_resume_pending_time() -> None:
    pending = route_direct_intent("Crea un recordatorio para hoy", date(2026, 9, 18))
    assert is_pending_field_response(pending, "¿Qué libro estoy leyendo?") is False
