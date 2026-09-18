from datetime import date

import pytest

from jarvis_core.intents import continue_direct_intent, route_direct_intent


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
        ("¿Qué tengo para hoy?", "list", None, {"from": "2026-09-18", "until": "2026-09-18"}),
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
