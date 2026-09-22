from datetime import date
import time

import pytest

from jarvis_core.config import CoreSettings
from jarvis_core.intents import DirectIntent
from jarvis_core.semantic import Intent, PendingPlan, SemanticPlan
from jarvis_core.services import JarvisServices, PendingAction
from jarvis_core.tools import Tool


async def _silent(_chunk: str) -> None:
    return None


@pytest.mark.asyncio
async def test_complete_read_does_not_resume_or_merge_pending_create(tmp_path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules="", semantic_planner_enabled=True))
    conversation = "pending-read"
    pending_plan = PendingPlan(SemanticPlan(
        intent=Intent.REMINDER_CREATE, confidence=.97,
        entities={"title": "hacer deberes aleman", "date": "today", "time": None},
    ), ("time",), "original-turn")
    services._pending_plans[conversation] = pending_plan
    now = time.monotonic()
    services._pending_intents[conversation] = PendingAction(
        "legacy", now, now, "time", "original-turn", "reminders", "create",
        DirectIntent("reminder_create", "bookshell_create_reminder", {
            "title": "hacer deberes aleman", "target_date": date.today().isoformat(),
        }, domain="reminders", operation="create", missing_fields=("time",)),
    )

    async def planned(*_args, **_kwargs):
        return SemanticPlan(intent=Intent.REMINDER_LIST, confidence=.99, entities={"scope": "today"})

    reads, mutations = [], []
    services.semantic_planner.plan = planned
    services.tools.register(Tool("bookshell_reminders_query", "read", {"type": "object"}, lambda args: _record(reads, args, {"count": 0, "items": [], "range": "today"})))
    services.tools.register(Tool("bookshell_create_reminder", "create", {"type": "object"}, lambda args: _record(mutations, args, {"created": True, "verified": True})))

    await services.chat_stream({"message": "Qué recordatorios tengo hoy", "conversation_id": conversation, "turn_id": "read-turn"}, _silent)
    assert reads and reads[0]["scope"] == "today"
    assert mutations == []
    assert services._pending_plans[conversation] is pending_plan
    assert conversation not in services._pending_intents


async def _record(calls, arguments, result):
    calls.append(arguments)
    return result


def test_merge_rejects_new_intent() -> None:
    from jarvis_core.semantic import merge_pending

    pending = PendingPlan(SemanticPlan(intent=Intent.REMINDER_CREATE, confidence=.9, entities={"title": "X"}), ("time",), "t")
    with pytest.raises(ValueError):
        merge_pending(pending, SemanticPlan(intent=Intent.REMINDER_LIST, confidence=.9, entities={"scope": "today"}, continuation=True))


@pytest.mark.asyncio
async def test_ambiguous_then_resolved_time_resumes_same_pending_once(tmp_path) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules="", semantic_planner_enabled=True))
    conversation = "pending-time"
    services._pending_plans[conversation] = PendingPlan(SemanticPlan(
        intent=Intent.REMINDER_CREATE, confidence=.97,
        entities={"title": "hacer deberes aleman", "date": "today", "time": None},
    ), ("time",), "original")
    plans = iter([
        SemanticPlan(
            intent=Intent.REMINDER_CREATE, confidence=.98, entities={"time": None},
            ambiguities=[{"field": "time", "options": ["04:00", "16:00"]}], continuation=True,
        ),
        SemanticPlan(
            intent=Intent.REMINDER_CREATE, confidence=.99, entities={"time": "16:00"}, continuation=True,
        ),
    ])

    async def planned(*_args, **_kwargs):
        return next(plans)

    calls = []
    services.semantic_planner.plan = planned
    services.tools.register(Tool("bookshell_create_reminder", "create", {"type": "object"}, lambda args: _record(calls, args, {"created": True, "verified": True})))
    first = await services.chat_stream({"message": "a las cuatro", "conversation_id": conversation, "turn_id": "time-1"}, _silent)
    assert "04:00" in first["message"] and "16:00" in first["message"]
    assert calls == []
    await services.chat_stream({"message": "a las cuatro de la tarde", "conversation_id": conversation, "turn_id": "time-2"}, _silent)
    assert len(calls) == 1
    assert calls[0]["target_time"] == "16:00"
    assert conversation not in services._pending_plans
