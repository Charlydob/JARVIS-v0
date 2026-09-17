from pathlib import Path

import pytest

from jarvis_core.config import CoreSettings
from jarvis_core.services import JarvisServices, TextToSpeechService, response_language
from jarvis_core.tools import Tool


def test_repetitive_answer_keeps_known_input_language() -> None:
    assert response_language("Here is the list: " + "test " * 50, "en") == "en"


@pytest.mark.asyncio
async def test_chat_stream_preserves_long_answer_and_detects_english(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))
    expected_chunks = ["This is sentence one. ", "This is sentence two. "] * 150
    received: list[str] = []

    async def fake_stream(_messages, context=None):
        assert "English (en)" in context
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected_language", "answer"),
    [
        ("Could you explain this in a concise way?", "English (en)", "Certainly, sir. Here is the explanation."),
        ("¿Podría explicarme esto de forma breve?", "Spanish (es)", "Desde luego, señor. Esta es la explicación."),
    ],
)
async def test_manual_text_forces_the_detected_output_language(
    tmp_path: Path, message: str, expected_language: str, answer: str
) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))

    async def fake_stream(_messages, context=None):
        assert expected_language in context
        yield answer

    services.ollama.chat_stream = fake_stream

    async def ignore_chunk(_chunk: str) -> None:
        return None

    result = await services.chat_stream({"message": message}, ignore_chunk)
    assert result["message"] == answer
    assert result["language"] == ("en" if expected_language.startswith("English") else "es")


@pytest.mark.asyncio
async def test_tts_uses_generated_text_language_over_input_hint(tmp_path: Path, monkeypatch) -> None:
    selected_languages: list[str | None] = []

    async def fake_voice(language: str | None) -> str:
        selected_languages.append(language)
        return "test-voice"

    class FakeCommunicate:
        def __init__(self, text: str, voice: str) -> None:
            self.text = text
            self.voice = voice

        async def save(self, filename: str) -> None:
            Path(filename).write_bytes(b"mp3")

    service = TextToSpeechService(CoreSettings(data_dir=tmp_path))
    service._voice_for = fake_voice
    monkeypatch.setattr("jarvis_core.services.edge_tts.Communicate", FakeCommunicate)

    await service.synthesize("This answer is clearly written in English.", "es")
    await service.synthesize("Esta respuesta está claramente escrita en español.", "en")

    assert selected_languages == ["en", "es"]


@pytest.mark.asyncio
async def test_failed_tool_is_reported_without_false_success(tmp_path: Path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules=""))

    async def failed_reminder(_arguments):
        raise RuntimeError("BookShell unavailable")

    services.tools.register(Tool(
        "bookshell_create_reminder", "create", {"type": "object"}, failed_reminder,
    ))

    async def fake_decision(_messages, _context, _tools):
        return {"role": "assistant", "tool_calls": [{"function": {
            "name": "bookshell_create_reminder",
            "arguments": {"title": "Alemán", "target_date": "2026-09-18", "target_time": "18:00"},
        }}]}

    services.ollama.tool_decision = fake_decision
    chunks: list[str] = []

    async def on_chunk(chunk: str) -> None:
        chunks.append(chunk)

    result = await services.chat_stream({"message": "Recuérdame mañana a las 18:00 que tengo alemán"}, on_chunk)

    assert result["message"] == "No se pudo guardar, señor."
    assert "creado" not in result["message"].casefold()
    assert chunks == [result["message"]]
