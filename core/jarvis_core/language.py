import re
from dataclasses import dataclass

from langdetect import DetectorFactory, LangDetectException, detect_langs


DetectorFactory.seed = 0
SUPPORTED_LANGUAGES = {"de", "en", "es", "fr", "it", "pt"}
EXPLICIT_LANGUAGE = {
    "de": (r"\b(?:auf deutsch|en aleman|en alemán|speak german)\b",),
    "en": (r"\b(?:in english|en ingles|en inglés|speak english)\b",),
    "es": (r"\b(?:en espanol|en español|in spanish|habla espanol|habla español)\b",),
    "fr": (r"\b(?:en francais|en français|en frances|en francés|in french)\b",),
    "it": (r"\b(?:in italiano|en italiano|in italian)\b",),
    "pt": (r"\b(?:em portugues|em português|en portugues|en portugués|in portuguese)\b",),
}


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", text.lower(), flags=re.UNICODE)


def detected_language(text: str, fallback: str = "es") -> tuple[str, float]:
    if len(_words(text)) < 4:
        return fallback, 0.0
    try:
        result = detect_langs(text)[0]
    except LangDetectException:
        return fallback, 0.0
    language = result.lang if result.lang in SUPPORTED_LANGUAGES else fallback
    return language, float(result.prob) if language == result.lang else 0.0


def response_language(text: str, fallback: str | None = None) -> str:
    fallback = (fallback or "es").split("-", 1)[0].lower()
    words = _words(text)
    if len(words) < 4 or (len(words) >= 8 and len(set(words)) / len(words) < 0.25):
        return fallback
    return detected_language(text, fallback)[0]


@dataclass
class LanguageState:
    language: str = "es"
    candidate: str | None = None
    candidate_turns: int = 0


class SessionLanguagePolicy:
    """Conservative language switching: short/noisy detections never move the session."""

    def __init__(self) -> None:
        self._states: dict[str, LanguageState] = {}

    def resolve(
        self,
        conversation_id: str,
        text: str,
        whisper_language: str | None = None,
        whisper_confidence: float | None = None,
    ) -> str:
        state = self._states.setdefault(conversation_id, LanguageState())
        normalized = text.casefold()
        for language, patterns in EXPLICIT_LANGUAGE.items():
            if any(re.search(pattern, normalized) for pattern in patterns):
                state.language, state.candidate, state.candidate_turns = language, None, 0
                return language

        words = _words(text)
        text_language, text_confidence = detected_language(text, state.language)
        hint = (whisper_language or "").split("-", 1)[0].lower()
        hint_confidence = float(whisper_confidence or 0.0)
        if hint in SUPPORTED_LANGUAGES and hint_confidence >= 0.82:
            detected = hint
            confidence = max(text_confidence if text_language == hint else 0.0, hint_confidence)
        else:
            detected, confidence = text_language, text_confidence

        if detected == state.language:
            state.candidate, state.candidate_turns = None, 0
            return state.language
        if detected not in SUPPORTED_LANGUAGES or len(words) < 4 or confidence < 0.80:
            return state.language

        immediate = (len(words) >= 8 and confidence >= 0.92) or (
            len(words) >= 5 and confidence >= 0.98 and detected in {"de", "en", "fr", "it"}
        ) or (
            detected == "es" and len(words) >= 5 and confidence >= 0.88
        )
        if immediate:
            state.language, state.candidate, state.candidate_turns = detected, None, 0
            return detected

        if state.candidate == detected:
            state.candidate_turns += 1
        else:
            state.candidate, state.candidate_turns = detected, 1
        if state.candidate_turns >= 2:
            state.language, state.candidate, state.candidate_turns = detected, None, 0
        return state.language
