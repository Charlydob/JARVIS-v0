import httpx

from app.providers.base import LLMProvider


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def chat(self, message: str, conversation_id: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Eres JARVIS, un asistente personal preciso, discreto y útil."},
                {"role": "user", "content": message},
            ],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        return str(data["message"]["content"])
