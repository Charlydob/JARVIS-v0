from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class Intent(StrEnum):
    CONVERSATION = "conversation"
    REMINDER_CREATE = "reminder.create"
    REMINDER_LIST = "reminder.list"
    REMINDER_SEARCH = "reminder.search"
    REMINDER_DELETE = "reminder.delete"
    CHECKLIST_CREATE = "checklist.create"
    CHECKLIST_APPEND = "checklist.append"
    CHECKLIST_DELETE = "checklist.delete"
    CHECKLIST_MARK = "checklist.mark"
    CHECKLIST_UNMARK = "checklist.unmark"
    NOTE_CREATE = "note.create"
    NOTE_UPDATE = "note.update"
    NOTE_DELETE = "note.delete"
    FOLDER_CREATE = "folder.create"
    FOLDER_DELETE = "folder.delete"
    WEATHER_FORECAST = "weather.forecast"
    LOCATION_CURRENT = "location.current"
    WEB_SEARCH = "web.search"
    WEB_OPEN_SOURCE = "web.open_source"
    PC_OPEN_URL = "pc.open_url"


MUTATING_INTENTS = {
    Intent.REMINDER_CREATE, Intent.REMINDER_DELETE, Intent.CHECKLIST_CREATE,
    Intent.CHECKLIST_APPEND, Intent.CHECKLIST_DELETE, Intent.CHECKLIST_MARK,
    Intent.CHECKLIST_UNMARK, Intent.NOTE_CREATE, Intent.NOTE_UPDATE,
    Intent.NOTE_DELETE, Intent.FOLDER_CREATE, Intent.FOLDER_DELETE,
}


class Ambiguity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    options: list[str] = Field(default_factory=list, max_length=8)


class SemanticPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    entities: dict[str, Any] = Field(default_factory=dict)
    ambiguities: list[Ambiguity] = Field(default_factory=list, max_length=8)
    references: list[str] = Field(default_factory=list, max_length=8)
    continuation: bool = False
    repair: bool = False

    @field_validator("entities")
    @classmethod
    def reject_identifiers_and_results(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = {"id", "uuid", "result", "verified", "success"}
        if forbidden.intersection(key.casefold() for key in value):
            raise ValueError("planner may not invent identifiers or execution results")
        return value


@dataclass
class PendingPlan:
    plan: SemanticPlan
    missing_fields: tuple[str, ...]
    originating_turn: str
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)
    candidate_uuids: tuple[str, ...] = ()

    def expired(self, ttl_seconds: float = 300) -> bool:
        return time.monotonic() - self.updated_at > ttl_seconds


@dataclass(frozen=True)
class ToolExecutionPlan:
    intent: Intent
    tool: str | None
    arguments: dict[str, Any]
    mutation: bool
    needs_confirmation: bool = False


@dataclass(frozen=True)
class ValidationResult:
    execution: ToolExecutionPlan | None = None
    clarification: str | None = None
    missing_fields: tuple[str, ...] = ()


CAPABILITY_CATALOG = """conversation
reminder.create(title,date,time), reminder.list(scope), reminder.search(title,scope), reminder.delete(title,scope)
checklist.create(title), checklist.append(checklist,item), checklist.delete(checklist), checklist.mark(checklist,item), checklist.unmark(checklist,item)
note.create(title,content,folder), note.update(title,content), note.delete(title), folder.create(name), folder.delete(name)
weather.forecast(scope), location.current, web.search(query), web.open_source(source), pc.open_url(url)"""


PLANNER_SYSTEM_PROMPT = """You are the semantic planner for a local Spanish-first voice assistant.
Return exactly one JSON object matching the supplied schema. Never execute tools or claim success.
Interpret meaning, corrections and follow-ups. Preserve proper nouns, including Jarvis when it is part of a name.
Strip grammatical wrappers from content: 'de hacer deberes' becomes 'hacer deberes'; 'que tengo que recoger' becomes 'recoger'.
Preserve relative dates exactly: if the user says today/tomorrow, output today/tomorrow, never an invented ISO date.
A bare 1-12 hour without morning/afternoon is always ambiguous: set time null and add 24-hour options (e.g. 03:00 and 15:00). Never choose one.
Set continuation true only when a supplied pending plan or recent turn is actually being continued.
Never invent IDs, UUIDs, URLs, entities, tool results, or facts. If intent or target is unclear, lower confidence or add ambiguity.
Use conversation for greetings, explanations, opinions and ordinary chat."""


class SemanticPlanner:
    def __init__(self, request_json: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        self._request_json = request_json

    async def plan(
        self,
        message: str,
        *,
        pending: PendingPlan | None = None,
        recent: list[dict[str, str]] | None = None,
    ) -> SemanticPlan:
        context: dict[str, Any] = {
            "message": message,
            "current_date": date.today().isoformat(),
            "capabilities": CAPABILITY_CATALOG,
        }
        if pending and not pending.expired():
            context["pending_plan"] = pending.plan.model_dump(mode="json")
            context["pending_missing_fields"] = list(pending.missing_fields)
        if recent:
            context["recent_turns"] = recent[-4:]
        payload = {
            "system": PLANNER_SYSTEM_PROMPT,
            "input": context,
            "schema": SemanticPlan.model_json_schema(),
        }
        raw = await self._request_json(payload)
        return SemanticPlan.model_validate(raw)

    @staticmethod
    def parse_json(content: str) -> SemanticPlan:
        return SemanticPlan.model_validate(json.loads(content))


class PlanValidator:
    REQUIRED: dict[Intent, tuple[str, ...]] = {
        Intent.REMINDER_CREATE: ("title", "date", "time"),
        Intent.REMINDER_DELETE: ("title",),
        Intent.CHECKLIST_CREATE: ("title",),
        Intent.CHECKLIST_APPEND: ("checklist", "item"),
        Intent.CHECKLIST_DELETE: ("checklist",),
        Intent.CHECKLIST_MARK: ("checklist", "item"),
        Intent.CHECKLIST_UNMARK: ("checklist", "item"),
        Intent.NOTE_CREATE: ("title",),
        Intent.NOTE_UPDATE: ("title", "content"),
        Intent.NOTE_DELETE: ("title",),
        Intent.FOLDER_CREATE: ("name",),
        Intent.FOLDER_DELETE: ("name",),
        Intent.WEB_SEARCH: ("query",),
        Intent.PC_OPEN_URL: ("url",),
    }

    TOOLS: dict[Intent, str | None] = {
        Intent.REMINDER_CREATE: "bookshell_create_reminder",
        Intent.REMINDER_LIST: "bookshell_reminders_query",
        Intent.REMINDER_SEARCH: "bookshell_reminders_query",
        Intent.REMINDER_DELETE: None,
        Intent.CHECKLIST_CREATE: "bookshell_notes_write",
        Intent.CHECKLIST_APPEND: None,
        Intent.CHECKLIST_DELETE: None,
        Intent.CHECKLIST_MARK: None,
        Intent.CHECKLIST_UNMARK: None,
        Intent.NOTE_CREATE: "bookshell_notes_write",
        Intent.NOTE_UPDATE: "bookshell_notes_write",
        Intent.NOTE_DELETE: "bookshell_notes_delete",
        Intent.FOLDER_CREATE: "bookshell_notes_folder_create",
        Intent.FOLDER_DELETE: "bookshell_notes_folder_delete",
        Intent.WEATHER_FORECAST: "weather_forecast",
        Intent.LOCATION_CURRENT: "location_reverse",
        Intent.WEB_SEARCH: "web_search",
        Intent.WEB_OPEN_SOURCE: None,
        Intent.PC_OPEN_URL: "pc_open_url",
        Intent.CONVERSATION: None,
    }

    def validate(self, plan: SemanticPlan, today: date) -> ValidationResult:
        if plan.confidence < 0.70:
            return ValidationResult(clarification="No estoy seguro de haberle entendido. ¿Puede concretarlo, señor?")
        entities = self._normalize(plan.entities, today)
        ambiguous_fields = {item.field for item in plan.ambiguities}
        missing = tuple(
            field for field in self.REQUIRED.get(plan.intent, ())
            if entities.get(field) in (None, "") or field in ambiguous_fields
        )
        if missing:
            return ValidationResult(
                clarification=self._clarification(missing[0], plan), missing_fields=missing,
            )
        arguments = self._arguments(plan.intent, entities)
        return ValidationResult(execution=ToolExecutionPlan(
            intent=plan.intent,
            tool=self.TOOLS[plan.intent],
            arguments=arguments,
            mutation=plan.intent in MUTATING_INTENTS,
            needs_confirmation=plan.intent in MUTATING_INTENTS and plan.confidence < 0.85,
        ))

    @staticmethod
    def _normalize(entities: dict[str, Any], today: date) -> dict[str, Any]:
        result = dict(entities)
        if result.get("date") == "today":
            result["date"] = today.isoformat()
        elif result.get("date") == "tomorrow":
            result["date"] = (today + timedelta(days=1)).isoformat()
        for key in ("title", "item", "checklist", "name", "content", "query"):
            if isinstance(result.get(key), str):
                result[key] = " ".join(result[key].split()).strip()
        return result

    @staticmethod
    def _clarification(field: str, plan: SemanticPlan) -> str:
        ambiguity = next((item for item in plan.ambiguities if item.field == field), None)
        if field == "time" and ambiguity and len(ambiguity.options) >= 2:
            return f"¿Se refiere a las {ambiguity.options[0]} o a las {ambiguity.options[1]}, señor?"
        prompts = {
            "time": "¿A qué hora, señor?", "date": "¿Para qué día, señor?",
            "checklist": "¿A qué checklist quiere añadirlo, señor?",
            "item": "¿Qué elemento quiere añadir, señor?", "title": "¿Cuál es el nombre exacto, señor?",
            "content": "¿Qué contenido quiere guardar, señor?", "name": "¿Qué nombre tendrá, señor?",
        }
        return prompts.get(field, f"Necesito concretar {field}, señor.")

    @staticmethod
    def _arguments(intent: Intent, entities: dict[str, Any]) -> dict[str, Any]:
        if intent == Intent.REMINDER_CREATE:
            return {"title": entities["title"], "target_date": entities["date"], "target_time": entities["time"], "minutes_before": 0}
        if intent in {Intent.REMINDER_LIST, Intent.REMINDER_SEARCH}:
            return {key: value for key, value in entities.items() if key in {"scope", "query", "title"} and value not in (None, "")}
        if intent == Intent.CHECKLIST_CREATE:
            return {"action": "create", "title": entities["title"], "content": "", "tags": ["checklist"], "category": "checklist"}
        if intent == Intent.NOTE_CREATE:
            return {"action": "create", "title": entities["title"], "content": entities.get("content", "")}
        if intent == Intent.NOTE_UPDATE:
            return {"action": "update", "title": entities["title"], "append_content": entities["content"]}
        if intent in {Intent.FOLDER_CREATE, Intent.FOLDER_DELETE}:
            return {"name": entities["name"]}
        if intent == Intent.WEATHER_FORECAST:
            return {"scope": entities.get("scope", "current")}
        if intent == Intent.LOCATION_CURRENT:
            return {}
        if intent == Intent.WEB_SEARCH:
            return {"query": entities["query"], "max_results": 5, "topic": "general"}
        if intent == Intent.PC_OPEN_URL:
            return {"url": entities["url"], "title": entities.get("title", "URL")}
        return dict(entities)


def to_direct_intent(result: ValidationResult):
    """Adapt a validated semantic plan to the established verified executor seam."""
    from jarvis_core.intents import DirectIntent

    if result.execution is None:
        return DirectIntent(
            "semantic_clarification", clarification=result.clarification,
            domain="semantic", operation="clarify", missing_fields=result.missing_fields,
        )
    execution = result.execution
    mapping: dict[Intent, tuple[str, str, str]] = {
        Intent.REMINDER_CREATE: ("reminder_create", "reminders", "create"),
        Intent.REMINDER_LIST: ("reminder_list", "reminders", "list"),
        Intent.REMINDER_SEARCH: ("reminder_search", "reminders", "search"),
        Intent.REMINDER_DELETE: ("reminder_delete", "reminders", "delete"),
        Intent.CHECKLIST_CREATE: ("checklist_create", "notes", "create"),
        Intent.CHECKLIST_APPEND: ("checklist_append", "notes", "update"),
        Intent.CHECKLIST_DELETE: ("checklist_delete", "notes", "delete"),
        Intent.CHECKLIST_MARK: ("checklist_mark", "notes", "update"),
        Intent.CHECKLIST_UNMARK: ("checklist_unmark", "notes", "update"),
        Intent.NOTE_CREATE: ("note_create", "notes", "create"),
        Intent.NOTE_UPDATE: ("note_update", "notes", "update"),
        Intent.NOTE_DELETE: ("note_delete", "notes", "delete"),
        Intent.FOLDER_CREATE: ("note_folder_create", "notes", "create"),
        Intent.FOLDER_DELETE: ("note_folder_delete", "notes", "delete"),
        Intent.WEATHER_FORECAST: ("weather_forecast", "weather", "forecast"),
        Intent.LOCATION_CURRENT: ("current_location", "location", "reverse_geocode"),
        Intent.WEB_SEARCH: ("web_search", "web", "search"),
        Intent.WEB_OPEN_SOURCE: ("source_open", "web", "open_source"),
        Intent.PC_OPEN_URL: ("pc_open_url", "pc", "open"),
    }
    if execution.intent == Intent.CONVERSATION:
        return None
    kind, domain, operation = mapping[execution.intent]
    arguments = dict(execution.arguments)
    if execution.intent in {
        Intent.CHECKLIST_APPEND, Intent.CHECKLIST_DELETE,
        Intent.CHECKLIST_MARK, Intent.CHECKLIST_UNMARK,
    }:
        arguments["target_name"] = arguments.pop("checklist", None)
    return DirectIntent(kind, execution.tool, arguments, domain=domain, operation=operation)


def merge_pending(pending: PendingPlan, update: SemanticPlan) -> SemanticPlan:
    """Overlay a follow-up/correction on the existing semantic object."""
    entities = dict(pending.plan.entities)
    entities.update({key: value for key, value in update.entities.items() if value is not None})
    return pending.plan.model_copy(update={
        "entities": entities,
        "confidence": update.confidence,
        "ambiguities": update.ambiguities,
        "references": update.references,
        "continuation": True,
        "repair": update.repair,
    })


def safe_parse_plan(value: str) -> SemanticPlan | None:
    try:
        return SemanticPlanner.parse_json(value)
    except (json.JSONDecodeError, ValidationError):
        return None
