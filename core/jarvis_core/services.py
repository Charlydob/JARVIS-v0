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
LOCATION_WORDS = ("dónde estamos", "donde estamos", "dónde estoy", "donde estoy", "ubicación", "ubicacion", "localización", "localizacion")


class OllamaService:
    def __init__(self, settings: CoreSettings) -> None:
        self.base_url = settings.ollama_url.rstrip("/")
        self.model = settings.ollama_model

    async def chat(self, messages: list[dict[str, str]], context: str | None = None) -> str:
        system_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context:
            system_messages.append({"role": "system", "content": context})
        payload = {
            "model": self.model,
            "messages": [*system_messages, *messages],
            "stream": False,
            "keep_alive": "10m",
            "options": {"temperature": 0.35, "num_predict": 220},
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=5.0)) as client:
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
            else ".m4a" if "mp4" in content_type or "m4a" in content_type or "aac" in content_type
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
        segments, _ = self._load().transcribe(
            str(path),
            language="es",
            beam_size=5,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt="Conversación clara en español con un asistente llamado JARVIS.",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 450},
        )
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
        self._location_cache: dict[tuple[float, float], str] = {}
        self._geocode_lock = asyncio.Lock()
        self._last_geocode_at = 0.0

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
        context = await self._tool_context(message, payload.get("latitude"), payload.get("longitude"))
        answer = await self.ollama.chat([*previous, {"role": "user", "content": message}], context)
        self.storage.add_message(conversation_id, "user", message)
        message_id = self.storage.add_message(conversation_id, "assistant", answer)
        return {
            "message": answer,
            "provider": "ollama",
            "conversation_id": conversation_id,
            "message_id": message_id,
        }

    async def _tool_context(self, message: str, latitude: Any, longitude: Any) -> str | None:
        normalized = message.lower()
        wants_weather = any(word in normalized for word in WEATHER_WORDS)
        wants_location = any(word in normalized for word in LOCATION_WORDS)
        if not wants_weather and not wants_location:
            return None
        if latitude is None or longitude is None:
            return "La petición requiere ubicación, pero el navegador no la ha compartido. Dilo claramente y pide permiso o una ubicación escrita; no adivines."
        location_context = (
            "El navegador ha compartido estas coordenadas actuales: "
            f"latitud {float(latitude):.5f}, longitud {float(longitude):.5f}. "
        )
        place = await self._reverse_location(float(latitude), float(longitude))
        if place:
            location_context += f"La geolocalización inversa de OpenStreetMap sitúa al usuario aproximadamente en {place}. "
        if not wants_weather:
            return location_context + "Responde con la localidad, región y país disponibles, aclarando que son aproximados."
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
                location_context + "Datos meteorológicos actuales obtenidos por herramienta para esas coordenadas "
                f"({float(latitude):.3f}, {float(longitude):.3f}), zona {data.get('timezone', 'desconocida')}: "
                f"temperatura {current.get('temperature_2m')} °C, sensación {current.get('apparent_temperature')} °C, "
                f"precipitación {current.get('precipitation')} mm, lluvia {current.get('rain')} mm, "
                f"nubosidad {current.get('cloud_cover')} %, código WMO {current.get('weather_code')}, "
                f"máxima probabilidad de precipitación próximas 12 h {maximum_rain} %. "
                "Usa solo estos datos para contestar sobre el tiempo y aclara que son una previsión."
            )
        except (httpx.HTTPError, TypeError, ValueError):
            return "La herramienta meteorológica no está disponible ahora mismo. Dilo claramente y no inventes datos."

    async def _reverse_location(self, latitude: float, longitude: float) -> str | None:
        cache_key = (round(latitude, 3), round(longitude, 3))
        if cache_key in self._location_cache:
            return self._location_cache[cache_key]
        async with self._geocode_lock:
            if cache_key in self._location_cache:
                return self._location_cache[cache_key]
            loop = asyncio.get_running_loop()
            wait = 1.0 - (loop.time() - self._last_geocode_at)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        "https://nominatim.openstreetmap.org/reverse",
                        params={
                            "lat": latitude,
                            "lon": longitude,
                            "format": "jsonv2",
                            "addressdetails": 1,
                            "accept-language": "es",
                            "zoom": 10,
                        },
                        headers={"User-Agent": "JARVIS-v0/0.2 (https://github.com/Charlydob/JARVIS-v0)"},
                    )
                    response.raise_for_status()
                address = response.json().get("address", {})
                locality = next((address.get(key) for key in ("city", "town", "village", "municipality", "hamlet") if address.get(key)), None)
                parts = [locality, address.get("state"), address.get("country")]
                place = ", ".join(dict.fromkeys(str(part) for part in parts if part))
                if place:
                    self._location_cache[cache_key] = place
                    return place
            except (httpx.HTTPError, TypeError, ValueError):
                return None
            finally:
                self._last_geocode_at = loop.time()
        return None
