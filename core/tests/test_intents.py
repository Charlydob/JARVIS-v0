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
