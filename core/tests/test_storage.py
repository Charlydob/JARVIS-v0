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
