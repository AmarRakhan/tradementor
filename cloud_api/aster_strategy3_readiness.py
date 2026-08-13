"""Strategy-3-specific, read-only live readiness gate."""
from __future__ import annotations

from typing import Any

from aster_strategy2_readiness import build_readiness_report


def build_strategy3_readiness_report(
    *,
    hedge_mode: bool,
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    strategy3_ownership_keys: set[tuple[str, str]],
    all_known_ownership_keys: set[tuple[str, str]],
    conflicting_ownership_keys: set[tuple[str, str]] | None = None,
    order_history_readable: bool,
    fills_readable: bool,
    income_readable: bool,
    reconciliation_passed: bool,
    coexistence_safe: bool,
    canary_validated: bool = False,
) -> dict[str, Any]:
    report = build_readiness_report(
        hedge_mode=hedge_mode,
        account=account,
        positions=positions,
        open_orders=open_orders,
        ownership_keys=all_known_ownership_keys,
        order_history_readable=order_history_readable,
        fills_readable=fills_readable,
        income_readable=income_readable,
        reconciliation_passed=reconciliation_passed,
        canary_validated=canary_validated,
    )
    # A union cannot retain which strategy supplied a key, so the caller
    # supplies proven cross-strategy collisions separately.
    collisions = sorted(conflicting_ownership_keys or set())
    coexistence = coexistence_safe and not collisions
    report["checks"].insert(-1, {
        "key": "strategy_coexistence",
        "passed": coexistence,
        "message": "Strategy 2 en 3 hebben gescheiden ownership" if coexistence else "Strategy-ownership botst of is niet bewijsbaar",
    })
    report["ownershipCollisions"] = [{"symbol": symbol, "side": side} for symbol, side in collisions]
    report["softwareReady"] = bool(report["softwareReady"] and coexistence)
    report["liveReady"] = bool(report["softwareReady"] and canary_validated)
    report["ordersSent"] = 0
    return report
