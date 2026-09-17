import importlib
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]
LOGGER = logging.getLogger("jarvis-core.tools")


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

    def definitions_for(self, message: str) -> list[dict[str, Any]]:
        """Narrow BookShell domains before model routing without choosing the action itself."""
        normalized = unicodedata.normalize("NFKD", message.casefold()).encode("ascii", "ignore").decode()
        rules = {
            "books": r"\b(libro|libros|pagina|leer|leyendo|lectura|leido|book|books|page|reading)\b",
            "gym": r"\b(gym|gimnasio|entren|ejercicio|series?|repeticiones?|kilos?|press banca|levante|pesas?)\b",
            "habits": r"\b(habito|habitos|racha|cumpl|pendientes? hoy)\b",
            "finance": r"\b(gasto|gastado|ingreso|sueldo|transfer|francos?|chf|euros?|saldo|cuentas?|movimiento|spent|expense|income|balance)\b",
            "reminder": r"\b(recordatorios?|recuerdame|agenda|guardia|dentista|cita|evento|que tengo hoy|que tengo esta semana|remind|reminders?|schedule|appointment)\b",
            "world": r"\b(lugar|sitio|cafeteria|restaurante|local|ubicacion|guardado en|valoracion|puntuacion)\b",
            "notes": r"\b(nota|notas|apunte|buscar en mis notas)\b",
            "recipes": r"\b(receta|recetas|ingredientes?|cocinar|preparacion)\b",
        }
        domains = {domain for domain, pattern in rules.items() if re.search(pattern, normalized)}
        if not domains:
            return []
        aliases = {
            "books": ("bookshell_books_", "bookshell_update_progress"),
            "gym": ("bookshell_gym_",), "habits": ("bookshell_habits_",),
            "finance": ("bookshell_finance_",), "reminder": ("bookshell_reminder", "bookshell_create_reminder"),
            "world": ("bookshell_world_",), "notes": ("bookshell_notes_",), "recipes": ("bookshell_recipes_",),
        }
        selected = []
        for name, tool in self._tools.items():
            if any(name.startswith(prefix) for domain in domains for prefix in aliases[domain]):
                selected.append(tool.ollama_definition())
        return selected[:3]

    def direct_query(self, message: str) -> tuple[str, dict[str, Any]] | None:
        """Bypass a model routing round only for unambiguous, read-only intents."""
        normalized = unicodedata.normalize("NFKD", message.casefold()).encode("ascii", "ignore").decode()
        if re.search(r"\b(recordatorios?|reminders?)\b", normalized) and re.search(r"\b(hoy|today)\b", normalized):
            if "bookshell_reminders_query" in self._tools:
                return "bookshell_reminders_query", {"scope": "today"}
        if re.search(r"\b(pagina|page)\b", normalized) and re.search(r"\b(libro|book|voy|current)\b", normalized):
            if "bookshell_books_query" in self._tools:
                return "bookshell_books_query", {"mode": "progress", "limit": 1}
        return None

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        started = time.perf_counter()
        try:
            result = await tool.handler(arguments)
        except Exception:
            LOGGER.exception("event=tool_error tool=%s duration_ms=%.1f", name, (time.perf_counter() - started) * 1000)
            raise
        rendered = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return rendered

    def load_modules(self, modules: str) -> None:
        for module_name in (item.strip() for item in modules.split(",")):
            if not module_name:
                continue
            module = importlib.import_module(module_name)
            register = getattr(module, "register_tools", None)
            if not callable(register):
                raise TypeError(f"{module_name} must expose register_tools(registry)")
            register(self)
