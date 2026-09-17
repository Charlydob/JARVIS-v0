# Tools/actions

JARVIS Core includes an empty, allow-listed tool registry. No external application is connected by default. An integration is a Python module exposing `register_tools(registry)` and is enabled explicitly with the comma-separated `JARVIS_TOOL_MODULES` setting.

```python
from jarvis_core.tools import Tool


async def create_reminder(arguments):
    # Authenticate to the target application's private API here.
    return {"created": True, "id": "reminder-id"}


def register_tools(registry):
    registry.register(Tool(
        name="bookshell_create_reminder",
        description="Create a reminder in BookShell after the user requests it.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "starts_at": {"type": "string", "description": "ISO-8601 date and time"},
                "advance_minutes": {"type": "integer", "minimum": 0},
            },
            "required": ["title", "starts_at"],
        },
        handler=create_reminder,
    ))
```

The generic flow is:

1. The Core gives Ollama only the definitions of installed tools.
2. Ollama can return a structured tool call.
3. `ToolRegistry` validates the registered name and invokes its handler.
4. The handler result is returned to Ollama as a tool message.
5. JARVIS streams the final user-facing answer.

Adapters own their API authentication, validation and authorization rules. Secrets remain in the Windows Core environment and must never be sent to the browser or committed. Adding BookShell, Guardias, Calendar or Home Assistant later requires a new adapter module and configuration, not changes to the conversation pipeline.
