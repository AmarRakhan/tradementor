"""Single execution boundary for AsterBot mutating leg orders.

Callers must provide an approved canonical decision. This module deliberately
wraps the low-level Aster executor so normal AsterBot runtime code cannot submit
an OPEN/CLOSE without an explicit action classification and decision.
"""
from __future__ import annotations

from typing import Any, Callable

from aster_execution import execute_leg_once
from aster_unified_engine import ActionType, AdmissionDecision, PositionActionDecision


ApprovedDecision = AdmissionDecision | PositionActionDecision


def _validate_decision(decision: ApprovedDecision, expected_action: ActionType) -> ApprovedDecision:
    if decision is None:
        raise PermissionError("ASTERBOT_EXECUTION_DENIED:MISSING_DECISION")
    if not bool(getattr(decision, "allowed", False)):
        reason = str(getattr(decision, "reason_code", "DENIED"))
        raise PermissionError(f"ASTERBOT_EXECUTION_DENIED:{reason}")
    actual = getattr(decision, "action_type", None)
    if actual is not expected_action:
        actual_value = getattr(actual, "value", str(actual))
        raise PermissionError(
            f"ASTERBOT_EXECUTION_DENIED:ACTION_TYPE_MISMATCH:{actual_value}!={expected_action.value}"
        )
    return decision


def execute_approved_leg_once(
    client: Any,
    plan: Any,
    *,
    side: Any,
    action: str,
    id_prefix: str,
    confirm: bool,
    expected_action: ActionType,
    decision: ApprovedDecision | None = None,
    decision_provider: Callable[[], ApprovedDecision] | None = None,
    before_submit: Callable[[Any], None] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute one leg only after a canonical decision has allowed it.

    decision_provider is used for INITIAL_ENTRY so exchange/config truth can be
    re-read at the last possible point, directly before submission.
    """
    holder: dict[str, ApprovedDecision] = {}

    if decision is not None:
        holder["decision"] = _validate_decision(decision, expected_action)

    def guarded_before_submit(intent: Any) -> None:
        current = holder.get("decision")
        if decision_provider is not None:
            current = _validate_decision(decision_provider(), expected_action)
            holder["decision"] = current
        if current is None:
            raise PermissionError("ASTERBOT_EXECUTION_DENIED:MISSING_DECISION")
        if before_submit is not None:
            before_submit(intent)

    result = execute_leg_once(
        client,
        plan,
        side=side,
        action=action,
        id_prefix=id_prefix,
        confirm=confirm,
        before_submit=guarded_before_submit,
        **kwargs,
    )
    approved = holder.get("decision")
    if approved is not None:
        result["unifiedDecision"] = approved.public_dict()
    return result
