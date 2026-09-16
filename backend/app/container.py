from dataclasses import dataclass

from app.config import Settings
from app.providers.base import LLMProvider, MemoryProvider, SpeechToTextProvider, TextToSpeechProvider, ToolProvider
from app.providers.mock import InMemoryProvider, MockLLMProvider, MockSpeechToTextProvider, MockTextToSpeechProvider, MockToolProvider
from app.providers.ollama import OllamaProvider


@dataclass
class Providers:
    llm: LLMProvider
    stt: SpeechToTextProvider
    tts: TextToSpeechProvider
    memory: MemoryProvider
    tools: ToolProvider


def build_providers(settings: Settings) -> Providers:
    llm: LLMProvider
    if settings.llm_provider.lower() == "ollama":
        llm = OllamaProvider(settings.ollama_url, settings.ollama_model)
    else:
        llm = MockLLMProvider()
    return Providers(
        llm=llm,
        stt=MockSpeechToTextProvider(),
        tts=MockTextToSpeechProvider(),
        memory=InMemoryProvider(),
        tools=MockToolProvider(),
    )
