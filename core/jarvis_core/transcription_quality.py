from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class QualityDecision(StrEnum):
    ACCEPT = "ACCEPT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    REJECT = "REJECT"


@dataclass(frozen=True)
class QualityResult:
    decision: QualityDecision
    score: float
    reasons: tuple[str, ...]


def _normalize(value: str) -> str:
    return " ".join(
        re.findall(r"[^\W_]+", unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode(), flags=re.UNICODE)
    )


def repetition_ratio(text: str) -> float:
    words = _normalize(text).split()
    if len(words) < 6:
        return 0.0
    worst = 0.0
    for size in range(2, min(10, len(words) // 2) + 1):
        chunks = [tuple(words[index:index + size]) for index in range(0, len(words) - size + 1)]
        most = max(chunks.count(chunk) for chunk in set(chunks))
        if most > 1:
            worst = max(worst, min(1.0, (most * size) / len(words)))
    return worst


class TranscriptionQualityGate:
    HALLUCINATION_ENDINGS = (
        "gracias por ver", "gracias por ver el video", "nos vemos en el proximo video",
        "suscribete", "subtitulos por", "thank you for watching", "see you in the next video",
    )

    def assess(self, text: str, metadata: dict[str, Any]) -> QualityResult:
        normalized = _normalize(text)
        if not normalized:
            return QualityResult(QualityDecision.REJECT, 0.0, ("empty",))
        score = 1.0
        reasons: list[str] = []
        avg_logprob = float(metadata.get("avg_logprob", -0.5) or -0.5)
        no_speech = float(metadata.get("max_no_speech_prob", 0) or 0)
        compression = float(metadata.get("max_compression_ratio", 1) or 1)
        duration = float(metadata.get("decoded_duration_s", metadata.get("container_duration_s", 0)) or 0)
        after_vad = float(metadata.get("duration_after_vad_s", duration) or 0)
        tokens = len(normalized.split())
        repeated = repetition_ratio(normalized)
        suspicious_ending = any(phrase in normalized for phrase in self.HALLUCINATION_ENDINGS)

        if avg_logprob < -1.25:
            score -= 0.38; reasons.append("very_low_logprob")
        elif avg_logprob < -0.85:
            score -= 0.20; reasons.append("low_logprob")
        if no_speech > 0.75:
            score -= 0.42; reasons.append("high_no_speech")
        elif no_speech > 0.45:
            score -= 0.18; reasons.append("elevated_no_speech")
        if compression > 3.0:
            score -= 0.35; reasons.append("high_compression")
        elif compression > 2.4:
            score -= 0.15; reasons.append("elevated_compression")
        if duration and after_vad < 0.22:
            score -= 0.32; reasons.append("almost_no_voice_after_vad")
        if repeated >= 0.60:
            score -= 0.60; reasons.append("phrase_loop")
        elif repeated >= 0.35:
            score -= 0.25; reasons.append("repetition")
        if tokens <= 2 and (avg_logprob < -0.85 or no_speech > 0.45):
            score -= 0.20; reasons.append("weak_short_fragment")
        if suspicious_ending and (avg_logprob < -0.65 or no_speech > 0.30 or after_vad < 0.5):
            score -= 0.55; reasons.append("hallucination_style_ending")

        score = max(0.0, min(1.0, score))
        severe = {"phrase_loop", "hallucination_style_ending", "almost_no_voice_after_vad"}.intersection(reasons)
        if score < 0.42 or (severe and score < 0.58):
            decision = QualityDecision.REJECT
        elif score < 0.72:
            decision = QualityDecision.LOW_CONFIDENCE
        else:
            decision = QualityDecision.ACCEPT
        return QualityResult(decision, round(score, 3), tuple(reasons))


def likely_own_tts(transcript: str, recent_tts: str | None) -> bool:
    if not recent_tts:
        return False
    heard, spoken = _normalize(transcript), _normalize(recent_tts)
    if len(heard) < 8:
        return False
    if heard in spoken:
        return True
    heard_words, spoken_words = set(heard.split()), set(spoken.split())
    return len(heard_words & spoken_words) / max(1, len(heard_words)) >= 0.85
