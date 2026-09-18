from pathlib import Path

from jarvis_core.storage import Storage


def test_history_and_feedback_are_persistent(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "memory.db")
    storage.add_message("conversation", "user", "Hola")
    assistant_id = storage.add_message("conversation", "assistant", "Hola, Carlos")
    feedback_id = storage.add_feedback(assistant_id, "bad", "Deberías haber dicho hola, señor", "incorrect")

    history = storage.history()
    assert len(history) == 2
    assert history[0]["rating"] == "bad"
    assert history[0]["reward"] == -1
    assert history[0]["reason"] == "incorrect"
    assert history[0]["correction"] == "Deberías haber dicho hola, señor"
    assert feedback_id
    assert storage.stats() == {"messages": 2, "positives": 0, "negatives": 1}

    storage.add_feedback(assistant_id, "good", None, "perfect")
    assert storage.stats() == {"messages": 2, "positives": 1, "negatives": 0}


def test_advanced_feedback_snapshots_turn_and_tools(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "memory.db")
    storage.add_message("conversation", "user", "¿Qué recordatorios tengo hoy?", turn_id="turn-12345678")
    assistant_id = storage.add_message(
        "conversation", "assistant", "No tiene recordatorios.", turn_id="turn-12345678",
        tools_available=["bookshell_reminders_query"], tools_used=[], tool_results=[],
    )
    storage.add_feedback(
        assistant_id, "bad", reason_code="should_have_used_tool",
        comment="Consulta BOOKSHELL antes de responder.",
        expected_behavior="Realizar una lectura actual.",
    )

    example = storage.feedback_examples()[0]
    assert example["reward"] == -1
    assert example["reason_code"] == "should_have_used_tool"
    assert example["comment"] == "Consulta BOOKSHELL antes de responder."
    assert example["expected_behavior"] == "Realizar una lectura actual."
    assert example["user_message"] == "¿Qué recordatorios tengo hoy?"
    assert example["assistant_response"] == "No tiene recordatorios."
    assert example["tools_available"] == '["bookshell_reminders_query"]'
    assert example["tools_used"] == "[]"
    assert example["turn_id"] == "turn-12345678"
