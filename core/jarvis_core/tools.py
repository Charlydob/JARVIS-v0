import importlib
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def ollama_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry for optional, explicitly installed JARVIS action adapters."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.ollama_definition() for tool in self._tools.values()]

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        result = await tool.handler(arguments)
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)

    def load_modules(self, modules: str) -> None:
        for module_name in (item.strip() for item in modules.split(",")):
            if not module_name:
                continue
            module = importlib.import_module(module_name)
            register = getattr(module, "register_tools", None)
            if not callable(register):
                raise TypeError(f"{module_name} must expose register_tools(registry)")
            register(self)
