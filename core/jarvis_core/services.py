import asyncio
import base64
import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

import edge_tts
import httpx
from edge_tts import VoicesManager
from faster_whisper import WhisperModel
from jarvis_core.config import CoreSettings
from jarvis_core.feedback import FeedbackLearning
from jarvis_core.intents import DirectIntent, continue_direct_intent, is_pending_followup, render_direct_result, route_direct_intent
from jarvis_core.language import SessionLanguagePolicy, response_language
from jarvis_core.storage import Storage
from jarvis_core.tools import ToolRegistry


SYSTEM_PROMPT = """Eres JARVIS, un asistente personal preciso, discreto y útil.
Cumple siempre el requisito OUTPUT LANGUAGE; el idioma de sesión ya ha sido validado conservadoramente.
Dirígete a él como «señor» (o el equivalente natural en ese idioma) cuando resulte apropiado.
Responde de forma breve y útil por defecto; amplía solo si la tarea lo necesita o el usuario lo pide.
No inventes nunca hechos, ubicación, clima, agenda, vivienda, familia, posesiones ni acciones realizadas.
No menciones mansiones, desayunos ni detalles personales que el usuario no haya proporcionado.
Un saludo se responde con brevedad, sin añadir noticias, clima ni supuestos.
No antepongas etiquetas de rol como «assistant», «user» o «JARVIS» a la respuesta.
No afirmes que una acción externa se ejecutó salvo que recibas un resultado de tool explícitamente exitoso y verificado.
Si necesitas información actual y no aparece en un contexto de herramienta, di claramente que no dispones de ella."""

WEATHER_WORDS = ("tiempo", "clima", "lluv", "temperatura", "frío", "frio", "calor", "nubl", "pronóstico", "pronostico", "previsión", "prevision")
LOCATION_WORDS = ("dónde estamos", "donde estamos", "dónde estoy", "donde estoy", "ubicación", "ubicacion", "localización", "localizacion")
PREFERRED_VOICE_LOCALES = {
    "ar": "ar-SA", "ca": "ca-ES", "de": "de-DE", "en": "en-GB", "es": "es-ES",
    "fr": "fr-FR", "it": "it-IT", "ja": "ja-JP", "ko": "ko-KR", "nl": "nl-NL",
    "pl": "pl-PL", "pt": "pt-PT", "ru": "ru-RU", "zh": "zh-CN",
}
LOGGER = logging.getLogger("jarvis-core.audio")
PERFORMANCE_LOGGER = logging.getLogger("jarvis-core.performance")
TOOL_LOGGER = logging.getLogger("jarvis-core.tools")
LANGUAGE_NAMES = {
    "de": "German", "en": "English", "es": "Spanish", "fr": "French",
    "it": "Italian", "pt": "Portuguese",
}
AUDIO_MIN_DURATION_MS = 500
AUDIO_MIN_SPEECH_MS = 300
AUDIO_MIN_RMS = 0.014
TRANSCRIPT_REPEAT_WINDOW_S = 8.0
PENDING_ACTION_TIMEOUT_S = 10 * 60
NOISE_TRANSCRIPTS = {
    "gracias por ver", "gracias por ver el video", "subtitulos", "musica", "silencio",
    "thank you for watching", "you", "bye",
}


def normalized_transcript(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def collapse_repeated_phrases(value: str) -> str:
    segments = [segment.strip() for segment in re.findall(r"[^.!?]+[.!?]?", value) if segment.strip()]
    if len(segments) < 2:
        return value.strip()
    result: list[str] = []
    previous = ""
    for segment in segments:
        canonical = re.sub(r"\bjarvis\b", "", normalized_transcript(segment)).strip()
        if canonical == previous and len(canonical.split()) >= 3:
            continue
        result.append(segment)
        previous = canonical
    return " ".join(result).strip()


class OllamaService:
    def __init__(self, settings: CoreSettings) -> None:
        self.base_url = settings.ollama_url.rstrip("/")
        self.model = settings.ollama_model

    def _payload(self, messages: list[dict[str, str]], context: str | None, stream: bool) -> dict[str, Any]:
        system_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context:
            system_messages.append({"role": "system", "content": context})
        return {
            "model": self.model,
            "messages": [*system_messages, *messages],
            "stream": stream,
            "keep_alive": "10m",
            "options": {"temperature": 0.35, "num_predict": -1},
        }

    async def chat_stream(self, messages: list[dict[str, str]], context: str | None = None):
        timeout = httpx.Timeout(180.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/api/chat", json=self._payload(messages, context, True)
            ) as response:
                response.raise_for_status()
                prefix = ""
                decided = False
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    content = str(data.get("message", {}).get("content", ""))
                    if content:
                        if decided:
                            yield content
                            continue
                        prefix += content
                        candidate = prefix.lstrip().casefold()
                        if candidate and "assistant".startswith(candidate) and "\n" not in prefix and len(candidate) <= len("assistant"):
                            continue
                        cleaned = re.sub(r"^\s*assistant\s*:?\s*", "", prefix, flags=re.IGNORECASE)
                        decided = True
                        if cleaned:
                            yield cleaned
                if prefix and not decided:
                    cleaned = re.sub(r"^\s*assistant\s*:?\s*", "", prefix, flags=re.IGNORECASE)
                    if cleaned:
                        yield cleaned

    async def tool_decision(
        self,
        messages: list[dict[str, Any]],
        context: str | None,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = self._payload(messages, context, False)
        payload["tools"] = tools
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0)) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
        return dict(response.json().get("message") or {})

    async def available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
            return response.is_success
        except httpx.HTTPError:
            return False

    async def warm(self) -> None:
        started = time.perf_counter()
        payload = {
            "model": self.model, "prompt": "", "stream": False, "keep_alive": "10m",
            "options": {"num_predict": 0},
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0)) as client:
                response = await client.post(f"{self.base_url}/api/generate", json=payload)
                response.raise_for_status()
            PERFORMANCE_LOGGER.info("stage=ollama_warm duration_ms=%.1f", (time.perf_counter() - started) * 1000)
        except httpx.HTTPError:
            PERFORMANCE_LOGGER.exception("stage=ollama_warm_failed")

    async def select_feedback(self, query: str, examples: list[dict[str, Any]]) -> list[str]:
        compact = [
            {"id": item["feedback_id"], "request": item["user_message"]}
            for item in examples
        ]
        prompt = (
            "Select at most 3 past requests that are semantically relevant to the new request. "
            "Match intent or topic even when wording differs. Do not select merely because both are greetings. "
            "Return strict JSON only as {\"ids\":[...]}.\n"
            f"NEW REQUEST: {query}\nPAST REQUESTS: {json.dumps(compact, ensure_ascii=False)}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "keep_alive": "10m",
            "options": {"temperature": 0, "num_predict": 120},
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=5.0)) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
        content = str(response.json().get("message", {}).get("content", "{}"))
        parsed = json.loads(content)
        allowed = {str(item["feedback_id"]) for item in examples}
        return [str(item) for item in parsed.get("ids", []) if str(item) in allowed][:3]


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

    async def transcribe(self, raw: bytes, content_type: str) -> tuple[str, str, dict[str, Any]]:
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

    def _transcribe_file(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        segments, info = self._load().transcribe(
            str(path),
            beam_size=5,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt="JARVIS",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 450},
        )
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
        metadata = {
            "decoded_duration_s": round(float(getattr(info, "duration", 0.0) or 0.0), 3),
            "duration_after_vad_s": round(float(getattr(info, "duration_after_vad", 0.0) or 0.0), 3),
            "language_probability": round(float(getattr(info, "language_probability", 0.0) or 0.0), 3),
        }
        return transcript, info.language, metadata


class TextToSpeechService:
    def __init__(self, settings: CoreSettings) -> None:
        self.voice = settings.tts_voice
        self._voices: VoicesManager | None = None
        self._voices_lock = asyncio.Lock()

    async def _voice_for(self, language: str | None) -> str:
        language_code = (language or "es").split("-", 1)[0].lower()
        if language_code == "es":
            return self.voice
        try:
            async with self._voices_lock:
                if self._voices is None:
                    self._voices = await VoicesManager.create()
            locale = PREFERRED_VOICE_LOCALES.get(language_code)
            choices = self._voices.find(Locale=locale, Gender="Male") if locale else []
            if not choices:
                choices = self._voices.find(Language=language_code, Gender="Male")
            return str(choices[0]["ShortName"]) if choices else self.voice
        except (IndexError, KeyError, RuntimeError):
            return self.voice

    async def synthesize(self, text: str, language: str | None = None) -> bytes:
        fd, filename = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        path = Path(filename)
        try:
            # The hint is only a fallback. The selected voice must follow the
            # language of the text that will actually be spoken.
            detected_language = response_language(text, language)
            await edge_tts.Communicate(text=text, voice=await self._voice_for(detected_language)).save(str(path))
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
        self.tools = ToolRegistry()
        self.tools.load_modules(settings.tool_modules)
        self.feedback = FeedbackLearning(self.storage, self.ollama.select_feedback)
        self.languages = SessionLanguagePolicy()
        self._location_cache: dict[tuple[float, float], str] = {}
        self._geocode_lock = asyncio.Lock()
        self._last_geocode_at = 0.0
        self._audio_results: dict[str, dict[str, Any]] = {}
        self._recent_transcripts: dict[str, tuple[str, float]] = {}
        self._turn_results: dict[str, tuple[dict[str, Any], float]] = {}
        self._turn_inflight: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_intents: dict[str, DirectIntent] = {}
        self._pending_intent_created: dict[str, float] = {}
        self._recent_completed_intents: dict[str, tuple[DirectIntent, float]] = {}
        self._action_locks: dict[str, asyncio.Lock] = {}
        self._action_results: dict[str, str] = {}

    async def status(self) -> dict[str, Any]:
        return {
            "version": "0.2.0",
            "providers": {
                "llm": f"ollama/{self.settings.ollama_model}",
                "stt": f"faster-whisper/{self.settings.whisper_model}",
                "tts": f"edge-tts/{self.settings.tts_voice}",
                "memory": "sqlite",
                "tools": ",".join(item["function"]["name"] for item in self.tools.definitions()) or "none",
            },
            "ollama_ready": await self.ollama.available(),
        }

    async def dispatch(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action == "chat":
            return await self._chat(payload)
        if action == "audio":
            started = time.perf_counter()
            utterance_id = str(payload.get("utterance_id") or uuid4())
            if utterance_id in self._audio_results:
                LOGGER.info("utterance_id=%s discard_reason=duplicate_utterance", utterance_id)
                return self._audio_results[utterance_id]
            raw = base64.b64decode(str(payload["data"]), validate=True)
            content_type = str(payload.get("content_type", "audio/webm"))
            duration_ms = float(payload.get("duration_ms") or 0)
            speech_ms = float(payload.get("speech_ms") or 0)
            max_rms = float(payload.get("max_rms") or 0)
            LOGGER.info(
                "utterance_id=%s audio_duration=%.0f speech_ms=%.0f rms=%.4f bytes=%d content_type=%s",
                utterance_id, duration_ms, speech_ms, max_rms, len(raw), content_type,
            )
            discard_reason = None
            if duration_ms < AUDIO_MIN_DURATION_MS:
                discard_reason = "audio_too_short"
            elif speech_ms < AUDIO_MIN_SPEECH_MS:
                discard_reason = "speech_too_short"
            elif max_rms < AUDIO_MIN_RMS:
                discard_reason = "energy_too_low"
            elif len(raw) < 1000:
                discard_reason = "audio_too_small"
            if discard_reason:
                result = {
                    "transcript": "", "language": "es", "language_confidence": 0,
                    "provider": "faster-whisper", "detail": "discarded", "discard_reason": discard_reason,
                    "utterance_id": utterance_id,
                }
                LOGGER.info("utterance_id=%s transcript=%r discard_reason=%s", utterance_id, "", discard_reason)
                self._audio_results[utterance_id] = result
                return result
            transcript, language, metadata = await self.stt.transcribe(raw, content_type)
            transcript = collapse_repeated_phrases(transcript)
            LOGGER.info(
                "Whisper result: language=%s probability=%s decoded_s=%s after_vad_s=%s transcript=%r",
                language,
                metadata["language_probability"],
                metadata["decoded_duration_s"],
                metadata["duration_after_vad_s"],
                transcript,
            )
            normalized = normalized_transcript(transcript)
            conversation_key = str(payload.get("conversation_id") or "global")
            now = time.monotonic()
            previous = self._recent_transcripts.get(conversation_key)
            discard_reason = None
            if not normalized:
                discard_reason = "empty_transcript"
            elif normalized in NOISE_TRANSCRIPTS or len(normalized.replace(" ", "")) < 2:
                discard_reason = "noise_transcript"
            elif previous and previous[0] == normalized and now - previous[1] <= TRANSCRIPT_REPEAT_WINDOW_S:
                discard_reason = "duplicate_transcript"
            if discard_reason:
                transcript = ""
            else:
                self._recent_transcripts[conversation_key] = (normalized, now)
            LOGGER.info("utterance_id=%s transcript=%r discard_reason=%s", utterance_id, transcript, discard_reason or "none")
            PERFORMANCE_LOGGER.info("stage=stt duration_ms=%.1f", (time.perf_counter() - started) * 1000)
            result = {
                "transcript": transcript, "language": language,
                "language_confidence": metadata["language_probability"],
                "provider": "faster-whisper", "detail": "discarded" if discard_reason else "complete",
                "discard_reason": discard_reason, "utterance_id": utterance_id,
            }
            self._audio_results[utterance_id] = result
            if len(self._audio_results) > 200:
                self._audio_results.pop(next(iter(self._audio_results)))
            return result
        if action == "tts":
            started = time.perf_counter()
            raw = await self.tts.synthesize(str(payload["text"]), payload.get("language"))
            duration_ms = (time.perf_counter() - started) * 1000
            PERFORMANCE_LOGGER.info("turn_id=%s stage=tts_first_audio duration_ms=%.1f", payload.get("turn_id"), duration_ms)
            PERFORMANCE_LOGGER.info("turn_id=%s stage=tts_total duration_ms=%.1f", payload.get("turn_id"), duration_ms)
            return {"data": base64.b64encode(raw).decode("ascii"), "content_type": "audio/mpeg"}
        if action == "history":
            return {"items": self.storage.history(int(payload.get("limit", 100)))}
        if action == "stats":
            return self.storage.stats()
        if action == "memories":
            return {"items": self.storage.memories(int(payload.get("limit", 50)))}
        if action == "feedback":
            feedback_id = self.storage.add_feedback(
                str(payload["message_id"]), str(payload["rating"]), payload.get("correction"), payload.get("reason")
            )
            return {"id": feedback_id, "stored": True, "reward": 1 if payload["rating"] == "good" else -1}
        raise ValueError(f"Unsupported action: {action}")

    async def _chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        async def ignore_chunk(_chunk: str) -> None:
            return None

        return await self.chat_stream(payload, ignore_chunk)

    async def chat_stream(
        self,
        payload: dict[str, Any],
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> dict[str, Any]:
        turn_id = str(payload.get("turn_id") or uuid4())
        now = time.monotonic()
        cached = self._turn_results.get(turn_id)
        if cached and now - cached[1] < 300:
            TOOL_LOGGER.info("turn_id=%s discard_reason=duplicate_turn", turn_id)
            await on_chunk(str(cached[0].get("message", "")))
            return cached[0]
        pending = self._turn_inflight.get(turn_id)
        if pending is not None:
            result = await pending
            TOOL_LOGGER.info("turn_id=%s discard_reason=duplicate_turn_inflight", turn_id)
            await on_chunk(str(result.get("message", "")))
            return result
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._turn_inflight[turn_id] = future
        try:
            result = await self._chat_stream_once({**payload, "turn_id": turn_id}, on_chunk)
            result["turn_id"] = turn_id
            self._turn_results[turn_id] = (result, time.monotonic())
            if len(self._turn_results) > 200:
                self._turn_results.pop(next(iter(self._turn_results)))
            future.set_result(result)
            return result
        except Exception as exc:
            future.set_exception(exc)
            future.exception()
            raise
        finally:
            self._turn_inflight.pop(turn_id, None)

    async def _chat_stream_once(
        self,
        payload: dict[str, Any],
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> dict[str, Any]:
        message = str(payload["message"]).strip()
        conversation_id = str(payload.get("conversation_id") or uuid4())
        turn_id = str(payload["turn_id"])
        total_started = time.perf_counter()
        routing_started = time.perf_counter()
        local_now = datetime.now(ZoneInfo(os.getenv("JARVIS_BOOKSHELL_TIMEZONE", "Europe/Zurich")))
        today = local_now.date()
        pending_created = self._pending_intent_created.get(conversation_id)
        if pending_created is not None and time.monotonic() - pending_created > PENDING_ACTION_TIMEOUT_S:
            self._pending_intents.pop(conversation_id, None)
            self._pending_intent_created.pop(conversation_id, None)
        direct = route_direct_intent(message, today, local_now)
        pending_resumed = False
        if conversation_id in self._pending_intents and (
            direct is None or (direct.kind == "reminder_create" and is_pending_followup(message))
        ):
            direct = continue_direct_intent(self._pending_intents[conversation_id], message, today, local_now)
            pending_resumed = direct is not None
        elif direct is None and is_pending_followup(message):
            completed = self._recent_completed_intents.get(conversation_id)
            if completed and time.monotonic() - completed[1] <= 120:
                replay = continue_direct_intent(completed[0], message, today, local_now)
                if replay and replay.arguments and completed[0].arguments and (
                    replay.arguments.get("target_time") == completed[0].arguments.get("target_time")
                ):
                    direct = replay
                    pending_resumed = True
        routed = direct
        if routed and routed.domain:
            TOOL_LOGGER.info(
                "turn_id=%s route_domain=%s route_operation=%s missing_fields=%s pending_action_resumed=%s",
                turn_id, routed.domain, routed.operation or "unknown",
                ",".join(routed.missing_fields) or "none", str(pending_resumed).lower(),
            )
        # Complex reminder mutations remain on the existing tool-selection path after
        # their domain and operation have been classified. Direct execution is reserved
        # for deterministic create/list/search operations.
        if direct and direct.tool is None and direct.clarification is None:
            direct = None
        PERFORMANCE_LOGGER.info(
            "turn_id=%s stage=intent_routing duration_ms=%.1f direct=%s",
            turn_id, (time.perf_counter() - routing_started) * 1000, routed.kind if routed else "none",
        )
        user_language = self.languages.resolve(
            conversation_id, message, payload.get("language"), payload.get("language_confidence")
        )
        if direct:
            if direct.clarification:
                answer = direct.clarification
                if direct.kind == "reminder_create" and direct.arguments is not None:
                    direct.arguments.setdefault("idempotency_key", str(uuid4()))
                self._pending_intents[conversation_id] = direct
                self._pending_intent_created.setdefault(conversation_id, time.monotonic())
                TOOL_LOGGER.info(
                    "turn_id=%s route_domain=%s route_operation=%s missing_fields=%s pending_action_created=true",
                    turn_id, direct.domain or "unknown", direct.operation or "unknown",
                    ",".join(direct.missing_fields) or "none",
                )
            elif direct.tool and direct.arguments is not None:
                tool_call_id = str(uuid4())
                public_tool = "bookshell.reminders.create" if direct.tool == "bookshell_create_reminder" else direct.tool
                execution_arguments = dict(direct.arguments)
                action_key = ""
                if direct.tool == "bookshell_create_reminder":
                    action_key = str(execution_arguments.setdefault("idempotency_key", turn_id))
                TOOL_LOGGER.info(
                    "turn_id=%s tool_call_id=%s event=tool_requested tool=%s internal_tool=%s arguments=%s",
                    turn_id, tool_call_id, public_tool, direct.tool, json.dumps(execution_arguments, ensure_ascii=False),
                )
                tool_started = time.perf_counter()
                try:
                    if action_key:
                        action_lock = self._action_locks.setdefault(action_key, asyncio.Lock())
                        async with action_lock:
                            raw_result = self._action_results.get(action_key) or await self.tools.execute(direct.tool, execution_arguments)
                            self._action_results[action_key] = raw_result
                    else:
                        raw_result = await self.tools.execute(direct.tool, execution_arguments)
                    parsed = json.loads(raw_result)
                    self._log_tool_timings(turn_id, tool_call_id, parsed)
                    succeeded = self._tool_succeeded(raw_result, direct.tool)
                    verification_succeeded = isinstance(parsed, dict) and parsed.get("verified") is True
                    if action_key and not succeeded:
                        self._action_results.pop(action_key, None)
                    TOOL_LOGGER.info(
                        "turn_id=%s tool_call_id=%s event=%s tool=%s internal_tool=%s tool_success=%s verification_success=%s duration_ms=%.1f",
                        turn_id, tool_call_id, "tool_success" if succeeded else "tool_error", public_tool, direct.tool,
                        str(succeeded).lower(), str(verification_succeeded).lower(),
                        (time.perf_counter() - tool_started) * 1000,
                    )
                    answer = render_direct_result(direct.kind, parsed if isinstance(parsed, dict) else {})
                    if succeeded:
                        self._pending_intents.pop(conversation_id, None)
                        self._pending_intent_created.pop(conversation_id, None)
                        if direct.kind == "reminder_create":
                            self._recent_completed_intents[conversation_id] = (direct, time.monotonic())
                        if len(self._action_results) > 200:
                            self._action_results.pop(next(iter(self._action_results)))
                except Exception:
                    if action_key:
                        self._action_results.pop(action_key, None)
                    TOOL_LOGGER.exception("turn_id=%s tool_call_id=%s event=tool_error tool=%s", turn_id, tool_call_id, direct.tool)
                    answer = "No se pudo guardar, señor." if direct.kind in {"book_update", "reminder_create"} else "No he podido consultar BookShell, señor."
                PERFORMANCE_LOGGER.info(
                    "turn_id=%s stage=tool_execution_and_readback duration_ms=%.1f",
                    turn_id, (time.perf_counter() - tool_started) * 1000,
                )
            else:
                answer = "No he podido completar la solicitud, señor."
            await on_chunk(answer)
            result = self._store_chat_result(conversation_id, message, answer, user_language)
            PERFORMANCE_LOGGER.info(
                "turn_id=%s stage=total duration_ms=%.1f path=direct", turn_id,
                (time.perf_counter() - total_started) * 1000,
            )
            return result
        context_started = time.perf_counter()
        previous = self.storage.conversation(conversation_id, limit=8)

        async def timed_context() -> str | None:
            started = time.perf_counter()
            result = await self._tool_context(message, payload.get("latitude"), payload.get("longitude"))
            PERFORMANCE_LOGGER.info("stage=external_context duration_ms=%.1f", (time.perf_counter() - started) * 1000)
            return result

        async def timed_feedback() -> str | None:
            started = time.perf_counter()
            result = await self.feedback.context_for(message)
            PERFORMANCE_LOGGER.info("stage=feedback_retrieval duration_ms=%.1f", (time.perf_counter() - started) * 1000)
            return result

        context, feedback_context = await asyncio.gather(timed_context(), timed_feedback())
        PERFORMANCE_LOGGER.info("stage=context duration_ms=%.1f history=%d", (time.perf_counter() - context_started) * 1000, len(previous))
        language_name = LANGUAGE_NAMES.get(user_language.split("-", 1)[0].lower(), user_language)
        language_context = (
            f"OUTPUT LANGUAGE REQUIREMENT: {language_name} ({user_language}). "
            f"Answer the user's latest message entirely in {language_name}. "
            "Do not switch language because of isolated foreign words or noisy transcription."
        )
        date_context = (
            f"CURRENT LOCAL DATE: {datetime.now().astimezone().date().isoformat()}. "
            "For tool calls, prefer relative_day/period/scope when the user says today, tomorrow, this week or this month. "
            "Never invent a date, ID, duration or field the user did not provide."
        )
        context_parts = [language_context, date_context]
        if feedback_context:
            context_parts.append(feedback_context)
        if context:
            context_parts.append(context)
        context = "\n".join(context_parts)
        conversation: list[dict[str, Any]] = [*previous, {"role": "user", "content": message}]
        routing_started = time.perf_counter()
        routing_message = message
        if len(re.findall(r"[^\W\d_]+", message, flags=re.UNICODE)) <= 3 and previous:
            routing_message = " ".join(str(item.get("content", "")) for item in previous[-2:]) + " " + message
        definitions = self.tools.definitions_for(routing_message)
        PERFORMANCE_LOGGER.info("turn_id=%s stage=tool_schema_selection duration_ms=%.1f tools=%d", turn_id, (time.perf_counter() - routing_started) * 1000, len(definitions))
        if definitions:
            direct_query = self.tools.direct_query(routing_message)
            if direct_query:
                direct_name, direct_arguments = direct_query
                decision = {"role": "assistant", "tool_calls": [{"function": {"name": direct_name, "arguments": direct_arguments}}]}
                PERFORMANCE_LOGGER.info("stage=ollama_tool_decision duration_ms=0.0 mode=deterministic")
            else:
                decision_started = time.perf_counter()
                decision = await self.ollama.tool_decision(conversation, context, definitions)
                PERFORMANCE_LOGGER.info("turn_id=%s stage=pre_llm duration_ms=%.1f", turn_id, (time.perf_counter() - decision_started) * 1000)
            tool_calls = list(decision.get("tool_calls") or [])
            if tool_calls:
                conversation.append(decision)
                authoritative_results: list[str] = []
                failure_messages: list[str] = []
                for call in tool_calls:
                    tool_call_id = str(call.get("id") or uuid4())
                    function = dict(call.get("function") or {})
                    name = str(function.get("name", ""))
                    arguments = function.get("arguments") or {}
                    if not isinstance(arguments, dict):
                        arguments = json.loads(str(arguments))
                    TOOL_LOGGER.info("turn_id=%s tool_call_id=%s event=tool_requested tool=%s arguments=%s", turn_id, tool_call_id, name, json.dumps(arguments, ensure_ascii=False))
                    tool_started = time.perf_counter()
                    try:
                        result = await self.tools.execute(name, arguments)
                        try:
                            self._log_tool_timings(turn_id, tool_call_id, json.loads(result))
                        except json.JSONDecodeError:
                            pass
                        TOOL_LOGGER.info("turn_id=%s tool_call_id=%s event=tool_executed tool=%s duration_ms=%.1f", turn_id, tool_call_id, name, (time.perf_counter() - tool_started) * 1000)
                        if self._tool_succeeded(result, name):
                            TOOL_LOGGER.info("turn_id=%s tool_call_id=%s event=tool_success tool=%s", turn_id, tool_call_id, name)
                        else:
                            TOOL_LOGGER.warning("turn_id=%s tool_call_id=%s event=tool_error tool=%s result=%s", turn_id, tool_call_id, name, result)
                            failure_messages.append(self._tool_failure_message(result))
                    except Exception as exc:
                        TOOL_LOGGER.exception("turn_id=%s tool_call_id=%s event=tool_error tool=%s", turn_id, tool_call_id, name)
                        result = json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
                        failure_messages.append("No he podido completar esa acción.")
                    PERFORMANCE_LOGGER.info("turn_id=%s stage=tool_execution_and_readback duration_ms=%.1f tool=%s", turn_id, (time.perf_counter() - tool_started) * 1000, name)
                    conversation.append({"role": "tool", "tool_name": name, "content": result})
                    authoritative_results.append(f"{name}: {result}")
                if failure_messages:
                    answer = " ".join(dict.fromkeys(failure_messages))
                    await on_chunk(answer)
                    PERFORMANCE_LOGGER.info("stage=chat_total duration_ms=%.1f path=tool_failure", (time.perf_counter() - total_started) * 1000)
                    return self._store_chat_result(conversation_id, message, answer, user_language)
                conversation.append({
                    "role": "system",
                    "content": (
                        "AUTHORITATIVE TOOL RESULTS (the requested actions/queries have already run; "
                        "answer only from these results). Never say created, updated, saved, deleted or completed "
                        "unless the corresponding result explicitly reports success=true or that action=true. "
                        "If clarificationRequired/confirmationRequired/configurationRequired/error is present, "
                        "ask or report it briefly and never claim success:\n"
                        + "\n".join(authoritative_results)
                    ),
                })
            else:
                answer = str(decision.get("content", "")).strip()
                if self._claims_success(answer):
                    answer = "No he ejecutado esa acción. Necesito los datos requeridos para hacerlo."
                if answer:
                    await on_chunk(answer)
                PERFORMANCE_LOGGER.info("stage=chat_total duration_ms=%.1f path=tool_no_call", (time.perf_counter() - total_started) * 1000)
                return self._store_chat_result(conversation_id, message, answer, user_language)

        chunks: list[str] = []
        ollama_started = time.perf_counter()
        ollama_stage = "second_llm" if definitions else "ollama"
        first_token = True
        async for chunk in self.ollama.chat_stream(conversation, context):
            if first_token:
                PERFORMANCE_LOGGER.info("turn_id=%s stage=%s_ttft duration_ms=%.1f", turn_id, ollama_stage, (time.perf_counter() - ollama_started) * 1000)
                first_token = False
            chunks.append(chunk)
            await on_chunk(chunk)
        PERFORMANCE_LOGGER.info("turn_id=%s stage=%s_total duration_ms=%.1f", turn_id, ollama_stage, (time.perf_counter() - ollama_started) * 1000)
        answer = "".join(chunks).strip()
        PERFORMANCE_LOGGER.info("turn_id=%s stage=total duration_ms=%.1f path=%s", turn_id, (time.perf_counter() - total_started) * 1000, "tool" if definitions else "fast")
        return self._store_chat_result(conversation_id, message, answer, user_language)

    @staticmethod
    def _tool_succeeded(result: str, tool_name: str = "") -> bool:
        try:
            payload = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return False
        if not isinstance(payload, dict):
            return False
        if any(payload.get(key) for key in ("error", "clarificationRequired", "confirmationRequired", "configurationRequired", "ambiguous")):
            return False
        action_flags = [key for key in ("created", "updated", "stored", "deleted", "completed") if key in payload]
        successful = all(payload[key] is True for key in action_flags) if action_flags else True
        if tool_name in {
            "bookshell_update_progress", "bookshell_create_reminder", "bookshell_gym_write",
            "bookshell_notes_write", "bookshell_finance_create",
        }:
            return successful and payload.get("verified") is True
        return successful

    @staticmethod
    def _log_tool_timings(turn_id: str, tool_call_id: str, payload: Any) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("_timings"), dict):
            return
        timings = payload["_timings"]
        PERFORMANCE_LOGGER.info(
            "turn_id=%s tool_call_id=%s stage=tool_execution duration_ms=%s",
            turn_id, tool_call_id, timings.get("write_ms"),
        )
        PERFORMANCE_LOGGER.info(
            "turn_id=%s tool_call_id=%s stage=readback_verification duration_ms=%s",
            turn_id, tool_call_id, timings.get("readback_ms"),
        )

    @staticmethod
    def _tool_failure_message(result: str) -> str:
        try:
            payload = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return "No he podido completar esa acción."
        message = str(payload.get("message") or "").strip() if isinstance(payload, dict) else ""
        return message or "No he podido completar esa acción."

    @staticmethod
    def _claims_success(answer: str) -> bool:
        return bool(re.search(r"\b(cread[oa]|actualizad[oa]|guardad[oa]|eliminad[oa]|completad[oa]|created|updated|saved|deleted)\b", answer.casefold()))

    def _store_chat_result(
        self, conversation_id: str, message: str, answer: str, fallback_language: str
    ) -> dict[str, Any]:
        answer = re.sub(r"^\s*assistant\s*:?\s*", "", answer, flags=re.IGNORECASE).strip()
        language = fallback_language
        self.storage.add_message(conversation_id, "user", message)
        message_id = self.storage.add_message(conversation_id, "assistant", answer)
        return {
            "message": answer,
            "provider": "ollama",
            "conversation_id": conversation_id,
            "message_id": message_id,
            "language": language,
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
