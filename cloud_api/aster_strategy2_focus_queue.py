"""Pure Focus queue ordering for Strategy 2.

Focus never executes here. The result is a list of intents that a future live
adapter must submit through the existing account-scoped Strategy-2 coordinator.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Literal

MAX_ACCOUNT_SCAN_ACTIONS = 15
FocusQueueKind = Literal[
    "EMERGENCY_CLOSE", "RISK_CLOSE", "FOCUS_CLOSE", "FOCUS_PARTIAL_TP",
    "FOCUS_DCA", "FOCUS_ENTRY", "LEGACY_MANAGEMENT"
]

_PRIORITY = {
    "EMERGENCY_CLOSE": 0,
    "RISK_CLOSE": 1,
    "FOCUS_CLOSE": 2,
    "FOCUS_PARTIAL_TP": 3,
    "FOCUS_DCA": 4,
    "FOCUS_ENTRY": 5,
    "LEGACY_MANAGEMENT": 6,
}

@dataclass(frozen=True)
class FocusQueueIntent:
    kind: FocusQueueKind
    symbol: str
    side: str
    notional: float = 0.0
    reduce_only: bool = False
    reason: str = ""
    sequence: int = 0

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def order_focus_intents(intents: list[FocusQueueIntent], *, orders_used: int = 0,
                        maximum_orders: int = MAX_ACCOUNT_SCAN_ACTIONS) -> list[FocusQueueIntent]:
    """Stable-priority order constrained by the existing per-scan order budget."""
    cap = min(MAX_ACCOUNT_SCAN_ACTIONS, max(0, int(maximum_orders)))
    remaining = max(0, cap - max(0, int(orders_used)))
    ordered = sorted(enumerate(intents), key=lambda row: (_PRIORITY[row[1].kind], row[1].sequence, row[0]))
    return [intent for _, intent in ordered[:remaining]]


def validate_focus_queue(intents: list[FocusQueueIntent]) -> None:
    """Fail closed on invariants required before a future execution adapter."""
    focus_entries = [x for x in intents if x.kind == "FOCUS_ENTRY"]
    if len({x.symbol.upper() for x in focus_entries}) > 1:
        raise ValueError("Focus mag maximaal één nieuwe pair tegelijk plannen")
    for intent in intents:
        if intent.kind in {"EMERGENCY_CLOSE", "RISK_CLOSE", "FOCUS_CLOSE", "FOCUS_PARTIAL_TP"} and not intent.reduce_only:
            raise ValueError(f"{intent.kind} moet reduce-only zijn")
        if intent.kind in {"FOCUS_DCA", "FOCUS_ENTRY"} and intent.side.upper() != "LONG":
            raise ValueError("Focus opent uitsluitend LONG-risico")
