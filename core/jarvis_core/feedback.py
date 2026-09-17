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
            "LEARNED USER PREFERENCES (only relevant past feedback; apply as guidance, not as fixed facts):"
        ]
        for item in selected:
            lines.append(f"- Similar request: {item['user_message']}")
            if item["rating"] == "good":
                lines.append(f"  The user approved this answer style/content: {item['assistant_response']}")
            else:
                lines.append(f"  Avoid this previous answer: {item['assistant_response']}")
                if item.get("reason"):
                    lines.append(f"  Reason: {item['reason']}")
                if item.get("correction"):
                    lines.append(f"  Prefer instead: {item['correction']}")
        return "\n".join(lines)
