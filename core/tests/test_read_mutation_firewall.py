import pytest

from jarvis_core.config import CoreSettings
from jarvis_core.semantic import Intent, PendingPlan, SemanticPlan
from jarvis_core.services import JarvisServices
from jarvis_core.tools import Tool


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["que tengo hoy Jarvis", "qué tiempo hará hoy"])
async def test_read_turn_cannot_execute_stale_pending_mutation(tmp_path, message) -> None:
    services = JarvisServices(CoreSettings(data_dir=tmp_path, tool_modules="", semantic_planner_enabled=True))
    conversation = "firewall"
    services._pending_plans[conversation] = PendingPlan(SemanticPlan(
        intent=Intent.REMINDER_CREATE, confidence=.98,
        entities={"title": "hacer deberes aleman", "date": "today", "time": None},
    ), ("time",), "old")

    async def planned(*_args, **_kwargs):
        if "tiempo" in message:
            return SemanticPlan(intent=Intent.WEATHER_FORECAST, confidence=.99, entities={"scope": "today"})
        return SemanticPlan(intent=Intent.REMINDER_LIST, confidence=.99, entities={"scope": "today"})

    mutation_calls = []
    services.semantic_planner.plan = planned
    services.tools.register(Tool("bookshell_create_reminder", "create", {"type": "object"}, lambda args: _mutation(mutation_calls, args)))
    services.tools.register(Tool("bookshell_reminders_query", "read", {"type": "object"}, lambda _args: _result({"count": 0, "items": [], "range": "today"})))
    services.tools.register(Tool("weather_forecast", "read", {"type": "object"}, lambda _args: _result({"scope": "today", "days": []})))
    await services.chat_stream({"message": message, "conversation_id": conversation, "turn_id": message}, lambda _c: _result(None))
    assert mutation_calls == []


async def _mutation(calls, args):
    calls.append(args)
    return {"created": True, "verified": True}


async def _result(value):
    return value

