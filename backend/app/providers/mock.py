from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.models import Memory
from app.providers.base import LLMProvider, MemoryProvider, SpeechToTextProvider, TextToSpeechProvider, ToolProvider


class MockLLMProvider(LLMProvider):
    name = "mock"

    async def chat(self, message: str, conversation_id: str) -> str:
        return f"He recibido tu mensaje: «{message}». El proveedor de lenguaje está en modo demostración."


class MockSpeechToTextProvider(SpeechToTextProvider):
    name = "mock"

    async def transcribe(self, audio: bytes, content_type: str | None = None) -> str:
        return "Audio recibido correctamente. La transcripción estará disponible al configurar un proveedor STT."


class MockTextToSpeechProvider(TextToSpeechProvider):
    name = "mock"

    async def synthesize(self, text: str) -> bytes:
        return b""


class InMemoryProvider(MemoryProvider):
    name = "in-memory"

    def __init__(self) -> None:
        self._items: list[Memory] = []

    async def list(self, limit: int = 50) -> list[Memory]:
        return self._items[-limit:]

    async def remember(self, content: str, metadata: dict[str, Any] | None = None) -> Memory:
        memory = Memory(id=str(uuid4()), content=content, created_at=datetime.now(UTC), metadata=metadata or {})
        self._items.append(memory)
        return memory


class MockToolProvider(ToolProvider):
    name = "mock"

    async def available_tools(self) -> list[dict[str, Any]]:
        return []

    async def execute(self, tool: str, arguments: dict[str, Any]) -> Any:
        raise ValueError(f"Tool not available: {tool}")
