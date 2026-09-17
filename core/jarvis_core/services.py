import asyncio
import base64
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import edge_tts
import httpx
from faster_whisper import WhisperModel

from jarvis_core.config import CoreSettings
from jarvis_core.storage import Storage


SYSTEM_PROMPT = """Eres JARVIS, un asistente personal preciso, discreto y útil.
Responde en español salvo que el usuario pida otro idioma y dirígete a él como «señor» cuando resulte natural.
No inventes nunca hechos, ubicación, clima, agenda, vivienda, familia, posesiones ni acciones realizadas.
No menciones mansiones, desayunos ni detalles personales que el usuario no haya proporcionado.
Un saludo se responde con brevedad, sin añadir noticias, clima ni supuestos.
Si necesitas información actual y no aparece en un contexto de herramienta, di claramente que no dispones de ella."""

WEATHER_WORDS = ("tiempo", "clima", "lluv", "temperatura", "frío", "frio", "calor", "nubl", "pronóstico", "pronostico", "previsión", "prevision")


class OllamaService:
    def __init__(self, settings: CoreSettings) -> None:
        self.base_url = settings.ollama_url.rstrip("/")
        self.model = settings.ollama_model

    async def chat(self, messages: list[dict[str, str]], context: str | None = None) -> str:
        system_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context:
            system_messages.append({"role": "system", "content": context})
        payload = {"model": self.model, "messages": [*system_messages, *messages], "stream": False}
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        return str(data["message"]["content"])

    async def available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
            return response.is_success
        except httpx.HTTPError:
            return False


class SpeechToTextService:
    def __init__(self, settings: CoreSettings) -> None:
        self.model_name = settings.whisper_model
        self.device = settings.whisper_device
        self.compute_type = settings.whisper_compute_type
        self._model: WhisperModel | None = None
        self._lock = asyncio.Lock()

    def _load(self) -> WhisperModel:
        if self._model is None:
            self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        return self._model

    async def transcribe(self, raw: bytes, content_type: str) -> str:
        suffix = (
            ".webm" if "webm" in content_type
            else ".ogg" if "ogg" in content_type
            else ".mp3" if "mpeg" in content_type or "mp3" in content_type
            else ".wav"
        )
        fd, filename = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        path = Path(filename)
        try:
            path.write_bytes(raw)
            async with self._lock:
                return await asyncio.to_thread(self._transcribe_file, path)
        finally:
            path.unlink(missing_ok=True)

    def _transcribe_file(self, path: Path) -> str:
        segments, _ = self._load().transcribe(str(path), language="es", vad_filter=True, beam_size=5)
        return " ".join(segment.text.strip() for segment in segments).strip()


class TextToSpeechService:
    def __init__(self, settings: CoreSettings) -> None:
        self.voice = settings.tts_voice

    async def synthesize(self, text: str) -> bytes:
        fd, filename = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        path = Path(filename)
        try:
            await edge_tts.Communicate(text=text, voice=self.voice).save(str(path))
            return path.read_bytes()
        finally:
            path.unlink(missing_ok=True)


class JarvisServices:
    def __init__(self, settings: CoreSettings) -> None:
        self.settings = settings
        self.storage = Storage(settings.database_path)
        self.ollama = OllamaService(settings)
        self.stt = SpeechToTextService(settings)
        self.tts = TextToSpeechService(settings)

    async def status(self) -> dict[str, Any]:
        return {
            "version": "0.2.0",
            "providers": {
                "llm": f"ollama/{self.settings.ollama_model}",
                "stt": f"faster-whisper/{self.settings.whisper_model}",
                "tts": f"edge-tts/{self.settings.tts_voice}",
                "memory": "sqlite",
            },
            "ollama_ready": await self.ollama.available(),
        }

    async def dispatch(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action == "chat":
            return await self._chat(payload)
        if action == "audio":
            raw = base64.b64decode(str(payload["data"]), validate=True)
            transcript = await self.stt.transcribe(raw, str(payload.get("content_type", "audio/webm")))
            return {"transcript": transcript, "provider": "faster-whisper", "detail": "complete"}
        if action == "tts":
            raw = await self.tts.synthesize(str(payload["text"]))
            return {"data": base64.b64encode(raw).decode("ascii"), "content_type": "audio/mpeg"}
        if action == "history":
            return {"items": self.storage.history(int(payload.get("limit", 100)))}
        if action == "memories":
            return {"items": self.storage.memories(int(payload.get("limit", 50)))}
        if action == "feedback":
            feedback_id = self.storage.add_feedback(
                str(payload["message_id"]), str(payload["rating"]), payload.get("correction")
            )
            return {"id": feedback_id, "stored": True}
        raise ValueError(f"Unsupported action: {action}")

    async def _chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        message = str(payload["message"]).strip()
        conversation_id = str(payload.get("conversation_id") or uuid4())
        previous = self.storage.conversation(conversation_id, limit=20)
        self.storage.add_message(conversation_id, "user", message)
        context = await self._weather_context(message, payload.get("latitude"), payload.get("longitude"))
        answer = await self.ollama.chat([*previous, {"role": "user", "content": message}], context)
        message_id = self.storage.add_message(conversation_id, "assistant", answer)
        return {
            "message": answer,
            "provider": "ollama",
            "conversation_id": conversation_id,
            "message_id": message_id,
        }

    async def _weather_context(self, message: str, latitude: Any, longitude: Any) -> str | None:
        if not any(word in message.lower() for word in WEATHER_WORDS):
            return None
        if latitude is None or longitude is None:
            return "El usuario pregunta por meteorología, pero no ha compartido ubicación. Pídele una ubicación; no hagas ninguna estimación."
        params = {
            "latitude": float(latitude),
            "longitude": float(longitude),
            "current": "temperature_2m,apparent_temperature,precipitation,rain,weather_code,cloud_cover",
            "hourly": "precipitation_probability",
            "forecast_hours": 12,
            "timezone": "auto",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
                response.raise_for_status()
            data = response.json()
            current = data.get("current", {})
            probabilities = data.get("hourly", {}).get("precipitation_probability", [])
            maximum_rain = max((value for value in probabilities if value is not None), default=None)
            return (
                "Datos meteorológicos actuales obtenidos por herramienta para las coordenadas autorizadas "
                f"({float(latitude):.3f}, {float(longitude):.3f}), zona {data.get('timezone', 'desconocida')}: "
                f"temperatura {current.get('temperature_2m')} °C, sensación {current.get('apparent_temperature')} °C, "
                f"precipitación {current.get('precipitation')} mm, lluvia {current.get('rain')} mm, "
                f"nubosidad {current.get('cloud_cover')} %, código WMO {current.get('weather_code')}, "
                f"máxima probabilidad de precipitación próximas 12 h {maximum_rain} %. "
                "Usa solo estos datos para contestar sobre el tiempo y aclara que son una previsión."
            )
        except (httpx.HTTPError, TypeError, ValueError):
            return "La herramienta meteorológica no está disponible ahora mismo. Dilo claramente y no inventes datos."
