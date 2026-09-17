import asyncio
from pathlib import Path

from jarvis_core.feedback import FeedbackLearning
from jarvis_core.storage import Storage


def _feedback(storage: Storage, request: str, answer: str, rating: str, correction: str | None = None) -> str:
    conversation = f"conversation-{request}"
    storage.add_message(conversation, "user", request)
    message_id = storage.add_message(conversation, "assistant", answer)
    return storage.add_feedback(message_id, rating, correction, "style" if rating == "bad" else None)


def test_negative_feedback_injects_correction_and_not_old_answer(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "memory.db")
    feedback_id = _feedback(
        storage,
        "Resume este correo de trabajo",
        "Una respuesta larguísima.",
        "bad",
        "Dar tres viñetas breves y accionables.",
    )

    async def selector(_query, _examples):
        return [feedback_id]

    context = asyncio.run(FeedbackLearning(storage, selector).context_for("Sintetiza este email profesional"))
    assert context is not None
    assert "Avoid this previous answer" in context
    assert "Dar tres viñetas breves" in context


def test_positive_feedback_is_used_as_an_approved_example(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "memory.db")
    feedback_id = _feedback(storage, "Salúdame", "Buenos días, señor.", "good")

    context = asyncio.run(FeedbackLearning(storage, lambda *_: [feedback_id]).context_for("Dame los buenos días"))

    assert context is not None
    assert "approved this answer" in context
    assert "Buenos días, señor." in context
