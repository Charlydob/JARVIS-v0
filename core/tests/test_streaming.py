from pathlib import Path

import pytest

from jarvis_core.config import CoreSettings
from jarvis_core.services import JarvisServices, response_language


def test_repetitive_answer_keeps_known_input_language() -> None:
    assert response_language("Here is the list: " + "test " * 50, "en") == "en"


@pytest.mark.asyncio
async def test_chat_stream_preserves_long_answer_and_detects_english(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    expected_chunks = ["This is sentence one. ", "This is sentence two. "] * 150
    received: list[str] = []

    async def fake_stream(_messages, context=None):
        assert "«en»" in context
        for chunk in expected_chunks:
            yield chunk

    services.ollama.chat_stream = fake_stream

    async def on_chunk(chunk: str) -> None:
        received.append(chunk)

    result = await services.chat_stream({"message": "Tell me a long story", "language": "en"}, on_chunk)

    assert received == expected_chunks
    assert result["message"] == "".join(expected_chunks).strip()
    assert result["language"] == "en"
    assert len(result["message"]) > 5_000
