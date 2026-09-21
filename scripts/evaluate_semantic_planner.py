"""Evaluate the legacy router and local semantic planner on real regression cases."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from jarvis_core.config import CoreSettings  # noqa: E402
from jarvis_core.intents import route_direct_intent  # noqa: E402
from jarvis_core.semantic import Intent, PendingPlan, SemanticPlan, SemanticPlanner, merge_pending  # noqa: E402
from jarvis_core.services import OllamaService  # noqa: E402


CASES = [
    ("añade un recordatorio para mañana a las tres de hacer deberes de alemán", "reminder.create", {"title": "hacer deberes de alemán", "date": "tomorrow", "time": None}, None, None),
    ("elimina el recordatorio de mañana que se llama otro recordatorio", "reminder.delete", {"title": "otro recordatorio", "scope": "tomorrow"}, None, None),
    ("crea un checklist llamado Proyecto Jarvis", "checklist.create", {"title": "Proyecto Jarvis"}, None, None),
    ("añade también mejorar transcripción", "checklist.append", {"checklist": "Mejoras", "item": "mejorar transcripción"}, None, [{"role": "assistant", "content": "Elemento añadido al checklist Mejoras."}]),
    ("no, me refería a Mejoras Dos", "checklist.append", {"checklist": "Mejoras Dos", "item": "probar actualizaciones"}, PendingPlan(SemanticPlan(intent=Intent.CHECKLIST_APPEND, confidence=.9, entities={"checklist": "Mejoras", "item": "probar actualizaciones"}), (), "prior"), None),
    ("hola, qué opinas de los asistentes locales", "conversation", {}, None, None),
]

LEGACY_MAP = {
    "reminder_create": "reminder.create", "reminder_delete": "reminder.delete",
    "checklist_create": "checklist.create", "checklist_append": "checklist.append",
    "checklist_append_guess": "checklist.append", "checklist_append_explicit": "checklist.append",
}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    service = OllamaService(CoreSettings())
    planner = SemanticPlanner(service.semantic_plan)
    old_correct = new_intent_correct = new_entity_correct = 0
    rows = []
    for utterance, expected_intent, expected_entities, pending, recent in CASES:
        legacy = route_direct_intent(utterance, date.today())
        legacy_intent = LEGACY_MAP.get(legacy.kind) if legacy else "conversation"
        old_ok = legacy_intent == expected_intent
        old_correct += old_ok
        plan = await planner.plan(utterance, pending=pending, recent=recent)
        if pending and plan.continuation:
            plan = merge_pending(pending, plan)
        intent_ok = plan.intent.value == expected_intent
        entity_ok = all(plan.entities.get(key) == value for key, value in expected_entities.items())
        new_intent_correct += intent_ok
        new_entity_correct += entity_ok
        rows.append({
            "utterance": utterance, "expected_intent": expected_intent,
            "legacy_intent": legacy_intent, "legacy_intent_ok": old_ok,
            "semantic_plan": plan.model_dump(mode="json"),
            "semantic_intent_ok": intent_ok, "semantic_entities_ok": entity_ok,
        })
    report = {
        "model": service.model, "cases": len(CASES),
        "old_router_intent_accuracy": old_correct / len(CASES),
        "semantic_planner_intent_accuracy": new_intent_correct / len(CASES),
        "semantic_planner_entity_case_accuracy": new_entity_correct / len(CASES),
        "rows": rows,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    asyncio.run(main())
