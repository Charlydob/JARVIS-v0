from datetime import date

from jarvis_core.intents import continue_direct_intent, route_direct_intent


def test_common_books_and_reminder_intents_are_deterministic() -> None:
    today = date(2026, 9, 17)  # Thursday
    assert route_direct_intent("¿Qué libro estoy leyendo?", today).kind == "book_current"
    assert route_direct_intent("¿Por qué página voy?", today).kind == "book_progress"
    update = route_direct_intent("Apunta página 220", today)
    assert update.tool == "bookshell_update_progress"
    assert update.arguments == {"page": 220}
    assert route_direct_intent("¿Qué tengo hoy?", today).kind == "reminders_today"


def test_friday_is_resolved_and_missing_time_is_requested() -> None:
    today = date(2026, 9, 17)  # Thursday
    missing = route_direct_intent("Clase de alemán el viernes", today)
    assert missing.clarification == "¿A qué hora, señor?"
    complete = route_direct_intent("Recuérdame clase de alemán el viernes a las 18:30", today)
    assert complete.arguments["target_date"] == "2026-09-18"
    assert complete.arguments["target_time"] == "18:30"


def test_same_weekday_means_next_week_not_today() -> None:
    complete = route_direct_intent("Recuérdame clase el viernes a las 18", date(2026, 9, 18))
    assert complete.arguments["target_date"] == "2026-09-25"


def test_reminder_clarification_preserves_date_and_title() -> None:
    today = date(2026, 9, 17)  # Thursday
    pending = route_direct_intent("Clase de alemán el viernes", today)
    complete = continue_direct_intent(pending, "A las 18", today)
    assert complete.clarification is None
    assert complete.arguments == {
        "title": "Clase de alemán",
        "minutes_before": 0,
        "target_date": "2026-09-18",
        "target_time": "18:00",
    }
