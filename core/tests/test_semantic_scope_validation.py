from datetime import date

from jarvis_core.semantic import Intent, PlanValidator, SemanticPlan


def test_invalid_scope_is_rejected_before_execution() -> None:
    result = PlanValidator().validate(SemanticPlan(
        intent=Intent.REMINDER_LIST, confidence=.99, entities={"scope": "user"},
    ), date(2026, 9, 22))
    assert result.execution is None
    assert result.clarification


def test_spanish_today_scope_is_normalized() -> None:
    result = PlanValidator().validate(SemanticPlan(
        intent=Intent.REMINDER_LIST, confidence=.99, entities={"scope": "hoy"},
    ), date(2026, 9, 22))
    assert result.execution.arguments == {"scope": "today"}


def test_current_date_has_no_reminder_tool() -> None:
    result = PlanValidator().validate(SemanticPlan(
        intent=Intent.DATETIME_CURRENT, confidence=.99,
    ), date(2026, 9, 22))
    assert result.execution.tool is None
    assert result.execution.mutation is False

