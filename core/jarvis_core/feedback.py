import inspect
import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable
from difflib import SequenceMatcher
from typing import Any

from jarvis_core.storage import Storage


LOGGER = logging.getLogger("jarvis-core.feedback")
SemanticSelector = Callable[[str, list[dict[str, Any]]], Awaitable[list[str]] | list[str]]

BEHAVIOR_REASONS = {
    "should_have_used_tool", "wrong_tool", "action_not_executed",
    "ignored_context", "repeated_response",
}
PREFERENCE_REASONS = {"too_long", "too_short", "wrong_tone"}


def _domain(value: str) -> str:
    normalized = _normalized(value)
    rules = {
        "reminders": r"\b(recordatori|recuerd|agenda|cita|dentista|clase)\w*\b",
        "books": r"\b(libro|pagina|leyendo|lectura)\w*\b",
        "gym": r"\b(gym|gimnasio|entren|ejercicio)\w*\b",
        "habits": r"\b(habito|racha)\w*\b",
        "finance": r"\b(gasto|saldo|cuenta|ingreso|finanz)\w*\b",
        "notes": r"\b(nota|apunte)\w*\b",
    }
    return next((name for name, pattern in rules.items() if re.search(pattern, normalized)), "general")


def _normalized(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value.lower()).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value))


def _lexical_score(query: str, candidate: str) -> float:
    left, right = _normalized(query), _normalized(candidate)
    if not left or not right:
        return 0.0
    left_words, right_words = set(left.split()), set(right.split())
    overlap = len(left_words & right_words) / max(1, len(left_words | right_words))
    return max(overlap, SequenceMatcher(None, left, right).ratio() * 0.72)


class FeedbackLearning:
    """Retrieves a few relevant examples; the selector can later be replaced by embeddings."""

    def __init__(self, storage: Storage, selector: SemanticSelector | None = None, max_examples: int = 3) -> None:
        self.storage = storage
        self.selector = selector
        self.max_examples = max_examples

    async def context_for(self, query: str) -> str | None:
        candidates = self.storage.feedback_examples(50)
        if not candidates:
            return None
        ranked = sorted(
            ((_lexical_score(query, str(item["user_message"])), item) for item in candidates),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not ranked or ranked[0][0] < 0.18:
            LOGGER.info(
                "Feedback retrieval: mode=fast-skip candidates=%d selected=0 query=%r",
                len(candidates), query,
            )
            return None
        selected_ids: list[str] = []
        mode = "lexical-fallback"
        if self.selector:
            try:
                result = self.selector(query, candidates)
                selected_ids = list(await result if inspect.isawaitable(result) else result)
                mode = "semantic-model"
            except Exception:
                LOGGER.exception("Semantic feedback selection failed; using lexical fallback")
        if not selected_ids:
            selected_ids = [
                str(item["feedback_id"]) for score, item in ranked[: self.max_examples] if score >= 0.34
            ]
        selected_set = set(selected_ids[: self.max_examples])
        selected = [item for item in candidates if str(item["feedback_id"]) in selected_set][: self.max_examples]
        LOGGER.info(
            "Feedback retrieval: mode=%s candidates=%d selected=%d ids=%s query=%r",
            mode, len(candidates), len(selected), [item["feedback_id"] for item in selected], query,
        )
        if not selected:
            return None
        lines = [
            "LEARNED RULES (guidance only; never copy an old response or treat feedback as current factual data):"
        ]
        for item in selected:
            reason_code = str(item.get("reason_code") or item.get("reason") or "")
            domain = _domain(str(item["user_message"]))
            feedback_kind = (
                "behavior" if reason_code in BEHAVIOR_REASONS
                else "preference" if reason_code in PREFERENCE_REASONS
                else "factual"
            )
            LOGGER.info(
                "feedback_kind=%s reason_code=%s domain=%s feedback_id=%s",
                feedback_kind, reason_code or "none", domain, item["feedback_id"],
            )
            lines.append(f"- feedback_kind={feedback_kind}; domain={domain}; reason_code={reason_code or 'unspecified'}")
            if item["rating"] == "good":
                lines.append("  Preserve the successful style, but obtain dynamic facts again from tools.")
                if item.get("comment"):
                    lines.append(f"  Preference: {item['comment']}")
            elif feedback_kind == "behavior":
                if reason_code == "should_have_used_tool":
                    lines.append(
                        "  POLICY: For a factual request in this domain, call the configured BookShell read tool "
                        "on every request and answer only from its fresh result. Never reuse the old answer."
                    )
                elif reason_code == "wrong_tool":
                    lines.append("  POLICY: Re-evaluate the domain and operation, then use the matching configured tool.")
                elif reason_code == "action_not_executed":
                    lines.append("  POLICY: Do not claim completion until the requested action tool succeeds and is verified.")
                elif reason_code == "ignored_context":
                    lines.append("  POLICY: Resolve the request using the relevant preceding turn before routing it.")
                elif reason_code == "repeated_response":
                    lines.append("  POLICY: Re-query the source of truth instead of repeating a prior response.")
                if item.get("expected_behavior"):
                    lines.append(f"  Expected behavior: {item['expected_behavior']}")
                elif item.get("comment"):
                    lines.append(f"  Context: {item['comment']}")
            elif feedback_kind == "preference":
                preference = item.get("expected_behavior") or item.get("comment") or item.get("correction")
                if preference:
                    lines.append(f"  Style preference: {preference}")
            else:
                lines.append(f"  This previous answer was factually rejected: {item['assistant_response']}")
                correction = item.get("expected_behavior") or item.get("correction") or item.get("comment")
                if correction:
                    lines.append(f"  Scoped correction: {correction}")
        return "\n".join(lines)
