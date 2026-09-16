from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.models import Memory


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def chat(self, message: str, conversation_id: str) -> str: ...

    async def stream(self, message: str, conversation_id: str) -> AsyncIterator[str]:
        yield await self.chat(message, conversation_id)


class SpeechToTextProvider(ABC):
    name: str

    @abstractmethod
    async def transcribe(self, audio: bytes, content_type: str | None = None) -> str: ...


class TextToSpeechProvider(ABC):
    name: str

    @abstractmethod
    async def synthesize(self, text: str) -> bytes: ...


class MemoryProvider(ABC):
    name: str

    @abstractmethod
    async def list(self, limit: int = 50) -> list[Memory]: ...

    @abstractmethod
    async def remember(self, content: str, metadata: dict[str, Any] | None = None) -> Memory: ...


class ToolProvider(ABC):
    name: str

    @abstractmethod
    async def available_tools(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def execute(self, tool: str, arguments: dict[str, Any]) -> Any: ...
