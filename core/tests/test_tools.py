import asyncio

import pytest

from jarvis_core.tools import Tool, ToolRegistry


def test_registry_exposes_and_executes_tools() -> None:
    async def handler(arguments):
        return {"created": arguments["title"]}

    registry = ToolRegistry()
    registry.register(Tool(
        name="create_reminder",
        description="Create a reminder",
        parameters={"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
        handler=handler,
    ))

    assert registry.definitions()[0]["function"]["name"] == "create_reminder"
    assert asyncio.run(registry.execute("create_reminder", {"title": "German class"})) == '{"created": "German class"}'


def test_registry_rejects_duplicate_names() -> None:
    async def handler(_arguments):
        return None

    registry = ToolRegistry()
    tool = Tool("same", "same", {"type": "object"}, handler)
    registry.register(tool)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(tool)


def test_registry_narrows_bookshell_domains_without_choosing_action() -> None:
    async def handler(_arguments):
        return None

    registry = ToolRegistry()
    for name in ("bookshell_gym_query", "bookshell_gym_write", "bookshell_world_query", "bookshell_reminders_query"):
        registry.register(Tool(name, name, {"type": "object"}, handler))

    gym_names = [item["function"]["name"] for item in registry.definitions_for("¿Cuánto llevo sin gimnasio?")]
    reminder_names = [item["function"]["name"] for item in registry.definitions_for("¿Cuándo tiene Laura guardia?")]

    assert gym_names == ["bookshell_gym_query", "bookshell_gym_write"]
    assert reminder_names == ["bookshell_reminders_query"]


def test_normal_conversation_uses_zero_tools_and_routing_caps_at_three() -> None:
    async def handler(_arguments):
        return None

    registry = ToolRegistry()
    for name in (
        "bookshell_reminders_query", "bookshell_reminder_update", "bookshell_create_reminder",
        "bookshell_books_query", "bookshell_update_progress",
    ):
        registry.register(Tool(name, name, {"type": "object"}, handler))

    assert registry.definitions_for("¿Cómo estás?") == []
    assert len(registry.definitions_for("Recuérdame mi libro y la página mañana")) <= 3
    assert registry.direct_query("¿Qué recordatorios tengo hoy?") == ("bookshell_reminders_query", {"scope": "today"})
    assert registry.direct_query("Añade un recordatorio hoy para clase de alemán") is None
    assert registry.direct_query("Cambia el recordatorio de clase de hoy") is None
    assert [item["function"]["name"] for item in registry.definitions_for("Cambia la clase de alemán a las 18:00")] == [
        "bookshell_reminders_query", "bookshell_reminder_update", "bookshell_create_reminder",
    ]
    assert registry.direct_query("¿Por qué página voy en el libro actual?") == ("bookshell_books_query", {"mode": "progress", "limit": 1})
