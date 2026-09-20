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

    def names(self) -> list[str]:
        return list(self._tools)

    def has(self, name: str) -> bool:
        return name in self._tools

    def definitions_for(self, message: str) -> list[dict[str, Any]]:
        """Narrow BookShell domains before model routing without choosing the action itself."""
        normalized = unicodedata.normalize("NFKD", message.casefold()).encode("ascii", "ignore").decode()
        rules = {
            "books": r"\b(libro|libros|leer|leyendo|lectura|leido|book|books|reading)\b",
            "gym": r"\b(gym|gimnasio|entren|ejercicio|series?|repeticiones?|kilos?|press banca|levante|pesas?)\b",
            "habits": r"\b(habito|habitos|racha|cumpl|pendientes? hoy)\b",
            "finance": r"\b(gasto|gastado|ingreso|sueldo|transfer|francos?|chf|euros?|saldo|cuentas?|movimiento|spent|expense|income|balance)\b",
            "reminder": r"\b(recordatori[oa]s?|recuerdame|agenda|guardia|dentista|clase|cita|evento|que tengo hoy|que tengo esta semana|remind|reminders?|schedule|appointment)\b",
            "world": r"\b(lugar|sitio|cafeteria|restaurante|local|ubicacion|guardado en|valoracion|puntuacion)\b",
            "notes": r"\b(nota|notas|apunte|checklist|lista de tareas|tareas|carpeta|subcarpeta|buscar en mis notas)\b|\bmarca\b.+\bcomo hecho\b",
            "recipes": r"\b(receta|recetas|ingredientes?|cocinar|preparacion)\b",
        }
        domains = {domain for domain, pattern in rules.items() if re.search(pattern, normalized)}
        web_context = bool(re.search(r"\b(wikipedia|pagina web|sitio web|internet|url|web)\b", normalized))
        reading_page = bool(re.search(
            r"\b(?:en|por|que|cual)\s+(?:la\s+)?pagina\b.*\b(?:voy|libro|lectura)\b|"
            r"\bpagina\s+(?:del|de un|de mi)\s+libro\b|\bvoy\s+por\s+la\s+pagina\b",
            normalized,
        ))
        if reading_page and not web_context:
            domains.add("books")
        if web_context:
            domains.discard("books")
        if not domains:
            return []
        aliases = {
            "books": ("bookshell_books_", "bookshell_update_progress", "bookshell_create_book"),
            "gym": ("bookshell_gym_",), "habits": ("bookshell_habits_",),
            "finance": ("bookshell_finance_",), "reminder": ("bookshell_reminder", "bookshell_create_reminder"),
            "world": ("bookshell_world_",), "notes": ("bookshell_notes_",), "recipes": ("bookshell_recipes_",),
        }
        selected = []
        for name, tool in self._tools.items():
            if any(name.startswith(prefix) for domain in domains for prefix in aliases[domain]):
                selected.append(tool.ollama_definition())
        if "notes" in domains:
            if re.search(r"\b(?:sub)?carpeta\b", normalized):
                priority = ["bookshell_notes_folder_query", "bookshell_notes_folder_create", "bookshell_notes_query"]
            else:
                priority = ["bookshell_notes_query", "bookshell_notes_write", "bookshell_notes_folder_query"]
            order = {name: index for index, name in enumerate(priority)}
            selected.sort(key=lambda item: order.get(str(item.get("function", {}).get("name", "")), len(order)))
        return selected[:3]

    def direct_query(self, message: str) -> tuple[str, dict[str, Any]] | None:
        """Bypass a model routing round only for unambiguous, read-only intents."""
        normalized = unicodedata.normalize("NFKD", message.casefold()).encode("ascii", "ignore").decode()
        reminder_write = re.search(
            r"\b(anad\w*|agreg\w*|cre\w*|apunt\w*|anot\w*|recuerdame|ponme|cambia|mueve|actualiza|cancela|elimina|borra|completa)\b",
            normalized,
        )
        if not reminder_write and re.search(r"\b(recordatori[oa]s?|reminders?)\b", normalized) and re.search(r"\b(hoy|today)\b", normalized):
            if "bookshell_reminders_query" in self._tools:
                return "bookshell_reminders_query", {"scope": "today"}
        if re.search(r"\b(pagina|page)\b", normalized) and re.search(r"\b(libro|book|voy|current)\b", normalized):
            if "bookshell_books_query" in self._tools:
                return "bookshell_books_query", {"mode": "progress", "limit": 1}
        return None

    def required_read_name(self, message: str) -> str | None:
        """Return the real registry capability required by an explicit factual query."""
        normalized = unicodedata.normalize("NFKD", message.casefold()).encode("ascii", "ignore").decode()
        if re.search(r"\b(anad\w*|agreg\w*|cre\w*|apunt\w*|anot\w*|recuerdame|ponme|cambia|actualiza|cancela|elimina|borra|marca)\b", normalized):
            return None
        web_context = bool(re.search(r"\b(wikipedia|pagina web|sitio web|internet|url|web)\b", normalized))
        reading_page = bool(re.search(
            r"\b(?:en|por|que|cual)\s+(?:la\s+)?pagina\b.*\b(?:voy|libro|lectura)\b|"
            r"\bpagina\s+(?:del|de un|de mi)\s+libro\b|\bvoy\s+por\s+la\s+pagina\b",
            normalized,
        ))
        queries = (
            (r"\b(recordatori[oa]s?|agenda|citas?|guardia)\b", "bookshell_reminders_query"),
            (r"\b(libro|libros|leyendo|lectura)\b", "bookshell_books_query"),
            (r"\b(gym|gimnasio|entrenamiento|ejercicio)\b", "bookshell_gym_query"),
            (r"\b(habito|habitos|racha)\b", "bookshell_habits_query"),
            (r"\b(gasto|saldo|cuenta|ingreso|finanzas?)\b", "bookshell_finance_query"),
            (r"\b(nota|notas|apunte|checklist|lista de tareas|tareas)\b|\bmarca\b.+\bcomo hecho\b", "bookshell_notes_query"),
            (r"\b(receta|recetas|ingredientes)\b", "bookshell_recipes_query"),
        )
        if reading_page and not web_context:
            return "bookshell_books_query"
        if web_context:
            return None
        return next((name for pattern, name in queries if re.search(pattern, normalized)), None)

    def fallback_read(
        self, message: str, definitions: list[dict[str, Any]]
    ) -> tuple[str, dict[str, Any]] | None:
        """Guarantee a fresh BookShell read when a factual domain was recognized.

        Ollama still chooses detailed arguments when it can. If it declines to call a
        tool, this conservative fallback calls the domain's read endpoint rather than
        allowing a cached or invented factual answer.
        """
        required = self.required_read_name(message)
        if required is None:
            return None
        available = {
            str(item.get("function", {}).get("name", ""))
            for item in definitions
        }
        normalized = unicodedata.normalize("NFKD", message.casefold()).encode("ascii", "ignore").decode()
        candidates: list[tuple[str, dict[str, Any]]] = []
        if "bookshell_books_query" in available:
            candidates.append(("bookshell_books_query", {"mode": "progress", "limit": 1}))
        if "bookshell_gym_query" in available:
            mode = "exercise" if re.search(r"\b(ejercicio|press|peso|kilos?)\b", normalized) else "last"
            arguments: dict[str, Any] = {"mode": mode, "limit": 10}
            if mode == "exercise":
                arguments["exercise"] = message
            candidates.append(("bookshell_gym_query", arguments))
        if "bookshell_habits_query" in available:
            mode = "pending" if re.search(r"\b(pendiente|hoy)\b", normalized) else "list"
            candidates.append(("bookshell_habits_query", {"mode": mode}))
        if "bookshell_finance_query" in available:
            mode = "accounts" if re.search(r"\b(saldo|cuentas?)\b", normalized) else "latest"
            candidates.append(("bookshell_finance_query", {"mode": mode, "limit": 10}))
        if "bookshell_reminders_query" in available:
            scope = (
                "next_week" if re.search(r"\b(semana que viene|proxima semana|next week)\b", normalized)
                else "this_week" if re.search(r"\b(esta semana|this week|semana)\b", normalized)
                else "tomorrow" if re.search(r"\b(manana|tomorrow)\b", normalized)
                else "today"
            )
            candidates.append(("bookshell_reminders_query", {"scope": scope}))
        if "bookshell_world_query" in available:
            candidates.append(("bookshell_world_query", {"scope": "all", "limit": 20}))
        if "bookshell_notes_query" in available:
            candidates.append(("bookshell_notes_query", {"limit": 10}))
        if "bookshell_recipes_query" in available:
            candidates.append(("bookshell_recipes_query", {"limit": 10}))
        return next((candidate for candidate in candidates if candidate[0] == required), None)

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        arguments = self._validated_arguments(tool, arguments)
        started = time.perf_counter()
        try:
            result = await tool.handler(arguments)
        except Exception:
            LOGGER.exception("event=tool_error tool=%s duration_ms=%.1f", name, (time.perf_counter() - started) * 1000)
            raise
        rendered = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return rendered

    @staticmethod
    def _validated_arguments(tool: Tool, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ValueError(f"Invalid arguments for {tool.name}: expected an object")
        properties = dict(tool.parameters.get("properties") or {})
        required = {str(item) for item in tool.parameters.get("required") or []}
        cleaned: dict[str, Any] = {}
        null_tokens = {"", "null", "none", "undefined"}
        for key, value in arguments.items():
            schema = properties.get(key)
            if not isinstance(schema, dict):
                cleaned[key] = value
                continue
            expected = schema.get("type")
            if isinstance(value, str) and value.strip().casefold() in null_tokens:
                value = None
            if value is None:
                if key in required:
                    raise ValueError(f"Invalid arguments for {tool.name}: {key} is required")
                continue
            if expected == "array" and isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid arguments for {tool.name}: {key} must be a JSON array") from exc
            type_valid = {
                "string": isinstance(value, str),
                "array": isinstance(value, list),
                "object": isinstance(value, dict),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "number": isinstance(value, (int, float)) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
            }.get(str(expected), True)
            if not type_valid:
                raise ValueError(f"Invalid arguments for {tool.name}: {key} must be {expected}")
            if isinstance(schema.get("enum"), list) and value not in schema["enum"]:
                raise ValueError(f"Invalid arguments for {tool.name}: {key} has an unsupported value")
            if expected == "array" and isinstance(schema.get("items"), dict):
                item_type = schema["items"].get("type")
                if item_type == "string" and any(not isinstance(item, str) for item in value):
                    raise ValueError(f"Invalid arguments for {tool.name}: every {key} item must be string")
                if item_type == "object" and any(not isinstance(item, dict) for item in value):
                    raise ValueError(f"Invalid arguments for {tool.name}: every {key} item must be object")
            cleaned[key] = value
        missing = [key for key in required if key not in cleaned]
        if missing:
            raise ValueError(f"Invalid arguments for {tool.name}: missing {', '.join(sorted(missing))}")
        return cleaned

    def load_modules(self, modules: str) -> None:
        for module_name in (item.strip() for item in modules.split(",")):
            if not module_name:
                continue
            module = importlib.import_module(module_name)
            register = getattr(module, "register_tools", None)
            if not callable(register):
                raise TypeError(f"{module_name} must expose register_tools(registry)")
            register(self)
