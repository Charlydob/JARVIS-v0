from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from jarvis_core.semantic import (
    Intent, PendingPlan, PlanValidator, SemanticPlan, SemanticPlanner, merge_pending,
)
from jarvis_core.config import CoreSettings
from jarvis_core.services import JarvisServices
from jarvis_core.tools import Tool


@pytest.mark.asyncio
async def test_planner_uses_schema_and_returns_semantic_title() -> None:
    captured = {}

    async def request(payload):
        captured.update(payload)
        return {
            "intent": "reminder.create", "confidence": 0.94,
            "entities": {"title": "hacer deberes de alemán", "date": "tomorrow", "time": None},
            "ambiguities": [{"field": "time", "options": ["03:00", "15:00"]}],
            "references": [], "continuation": False, "repair": False,
        }

    plan = await SemanticPlanner(request).plan(
        "Jarvis añade un recordatorio para mañana a las tres de hacer deberes de alemán"
    )
    assert plan.entities["title"] == "hacer deberes de alemán"
    assert captured["schema"]["additionalProperties"] is False
    result = PlanValidator().validate(plan, date(2026, 9, 21))
    assert result.missing_fields == ("time",)
    assert "03:00" in result.clarification and "15:00" in result.clarification


def test_planner_cannot_invent_uuid_or_success() -> None:
    with pytest.raises(ValidationError):
        SemanticPlan.model_validate({
            "intent": "reminder.delete", "confidence": 1,
            "entities": {"uuid": "invented", "verified": True},
        })


def test_pending_followup_overlays_same_plan() -> None:
    original = SemanticPlan(
        intent=Intent.REMINDER_CREATE, confidence=.94,
        entities={"title": "hacer deberes de alemán", "date": "tomorrow", "time": None},
        ambiguities=[{"field": "time", "options": ["03:00", "15:00"]}],
    )
    followup = SemanticPlan(
        intent=Intent.REMINDER_CREATE, confidence=.98, entities={"time": "15:00"},
        continuation=True, repair=True,
    )
    merged = merge_pending(PendingPlan(original, ("time",), "turn-1"), followup)
    validated = PlanValidator().validate(merged, date(2026, 9, 21))
    assert validated.execution.arguments == {
        "title": "hacer deberes de alemán", "target_date": "2026-09-22",
        "target_time": "15:00", "minutes_before": 0,
    }


def test_real_delete_and_checklist_continuation_meaning() -> None:
    validator = PlanValidator()
    deletion = SemanticPlan(
        intent=Intent.REMINDER_DELETE, confidence=.96,
        entities={"title": "otro recordatorio", "scope": "tomorrow"},
    )
    assert validator.validate(deletion, date(2026, 9, 21)).execution.arguments == {
        "title": "otro recordatorio", "scope": "tomorrow",
    }
    append = SemanticPlan(
        intent=Intent.CHECKLIST_APPEND, confidence=.93,
        entities={"checklist": "Mejoras", "item": "mejorar transcripción"}, continuation=True,
    )
    execution = validator.validate(append, date(2026, 9, 21)).execution
    assert execution.arguments["item"] == "mejorar transcripción"
    assert execution.tool is None  # entity resolution must happen in the deterministic executor


def test_low_confidence_mutation_is_never_executable() -> None:
    plan = SemanticPlan(
        intent=Intent.NOTE_DELETE, confidence=.42, entities={"title": "Importante"},
    )
    result = PlanValidator().validate(plan, date(2026, 9, 21))
    assert result.execution is None
    assert result.clarification


@pytest.mark.asyncio
async def test_service_executes_semantic_plan_only_through_verified_tool(tmp_path) -> None:
    services = JarvisServices(CoreSettings(
        data_dir=tmp_path, tool_modules="", semantic_planner_enabled=True,
    ))
    calls = []

    async def planned(*_args, **_kwargs):
        return SemanticPlan(
            intent=Intent.REMINDER_CREATE, confidence=.96,
            entities={"title": "hacer deberes de alemán", "date": "tomorrow", "time": "15:00"},
        )

    async def create(arguments):
        calls.append(arguments)
        return {"created": True, "verified": True}

    services.semantic_planner.plan = planned
    services.tools.register(Tool("bookshell_create_reminder", "create", {"type": "object"}, create))
    result = await services.chat_stream({
        "message": "pon eso mañana por la tarde", "conversation_id": "semantic-e2e",
        "turn_id": "semantic-e2e-1",
    }, lambda _chunk: __import__("asyncio").sleep(0))
    assert calls == [{
        "title": "hacer deberes de alemán", "target_date": (date.today() + timedelta(days=1)).isoformat(),
        "target_time": "15:00", "minutes_before": 0, "idempotency_key": "semantic-e2e-1",
    }]
    # Production uses the configured timezone's date. Assert the safety
    # properties independently of midnight boundary timing.
    assert calls[0]["title"] == "hacer deberes de alemán"
    assert result["message"] == "Recordatorio creado, señor."
