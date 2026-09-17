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
