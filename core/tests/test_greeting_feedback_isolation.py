import pytest

from jarvis_core.config import CoreSettings
from jarvis_core.semantic import Intent, SemanticPlan
from jarvis_core.services import JarvisServices


@pytest.mark.parametrize("message", ["hola", "hola Jarvis", "Jarvis hola", "buenos días Jarvis", "buenas tardes Jarvis", "hey Jarvis"])
def test_greeting_with_vocative_skips_feedback(message) -> None:
    assert JarvisServices._skip_feedback(message) is True


@pytest.mark.asyncio
async def test_greeting_has_one_response_and_no_tools_or_feedback(tmp_path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules="", semantic_planner_enabled=True))
    feedback_calls = []

    async def planned(*_args, **_kwargs):
        return SemanticPlan(intent=Intent.CONVERSATION, confidence=.99)

    async def feedback(_message):
        feedback_calls.append(_message)
        return "stale factual context"

    async def chat_stream(*_args, **_kwargs):
        yield "Hola, señor."

    services.semantic_planner.plan = planned
    services.feedback.context_for = feedback
    services.ollama.chat_stream = chat_stream
    chunks = []

    async def collect(chunk):
        chunks.append(chunk)

    result = await services.chat_stream({"message": "hola Jarvis", "conversation_id": "greeting", "turn_id": "greeting-1"}, collect)
    assert feedback_calls == []
    assert services.tools.names() == []
    assert "sources" not in result
    assert chunks == ["Hola, señor."]
