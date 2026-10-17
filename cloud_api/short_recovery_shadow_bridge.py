"""Shadow-only integration with existing Auto Hedge reconciliation.

A deliberate recovery allocation is never handed to exact 1:1 reconciliation.
This module never calls an exchange executor or mutates persisted state.
"""
from decimal import Decimal
from short_recovery_reduction import ReductionState, plan_reduction, rehedge_permission


def preview_reconciliation(*, protected_sides: dict[str, str],
                           existing_skip_symbols: set[str],
                           recovery_states: dict[str, ReductionState],
                           exchange_short_quantities: dict[str, Decimal],
                           long_quantities: dict[str, Decimal],
                           net_exits: set[str] | None = None) -> dict:
    net_exits = net_exits or set()
    skip = set(existing_skip_symbols)
    results = {}
    for symbol, state in recovery_states.items():
        if symbol not in protected_sides or protected_sides[symbol] != "LONG":
            results[symbol] = {"status": "BLOCKED_NOT_LONG_OWNER"}
            skip.add(symbol)
            continue
        skip.add(symbol)
        reduction = plan_reduction(state)
        rehedge = rehedge_permission(
            state, remaining_exchange_short_qty=exchange_short_quantities.get(symbol, Decimal("-1")),
            long_qty=long_quantities.get(symbol, Decimal(0)),
            net_exit_due=symbol in net_exits, pending=state.pending)
        results[symbol] = {"status": "SHADOW_ONLY", "reduction": reduction, "rehedge": rehedge}
    return {"protected_sides": dict(protected_sides),
            "skip_symbols": skip, "recovery_previews": results, "orders_sent": 0}
