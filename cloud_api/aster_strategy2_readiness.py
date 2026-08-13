"""Read-only live-readiness checks for Aster Strategy 2.

Passing this gate proves that state can be read and reconciled. It deliberately
does not place a canary order and therefore cannot by itself unlock live trade.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


def _number(value: Any) -> float:
    try: return float(value)
    except (TypeError, ValueError): return 0.0


@dataclass(frozen=True)
class ReadinessCheck:
    key: str
    passed: bool
    message: str


def build_readiness_report(
    *, hedge_mode: bool, account: dict[str, Any], positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]], ownership_keys: set[tuple[str, str]],
    order_history_readable: bool, fills_readable: bool, income_readable: bool,
    reconciliation_passed: bool, canary_validated: bool = False,
) -> dict[str, Any]:
    active = [p for p in positions if abs(_number(p.get("positionAmt"))) > 0]
    unowned = sorted({
        (str(p.get("symbol", "")).upper(), str(p.get("positionSide", "")).upper())
        for p in active
    } - ownership_keys)
    equity = max(_number(account.get("totalMarginBalance")), _number(account.get("totalWalletBalance")))
    checks = [
        ReadinessCheck("hedge_mode", hedge_mode, "Aster Hedge Mode is bevestigd" if hedge_mode else "Aster Hedge Mode staat niet aan"),
        ReadinessCheck("account_equity", equity > 0, "Account-equity is leesbaar" if equity > 0 else "Geen geldige account-equity ontvangen"),
        ReadinessCheck("order_history", order_history_readable, "Orderhistorie is leesbaar"),
        ReadinessCheck("fills", fills_readable, "Werkelijke fills en partial fills zijn leesbaar"),
        ReadinessCheck("funding", income_readable, "Funding, fees en realized PnL zijn leesbaar"),
        ReadinessCheck("reconciliation", reconciliation_passed, "Herstart/reconciliation is consistent"),
        ReadinessCheck("ownership", not unowned, "Alle actieve exposure heeft bewezen Strategy-ownership" if not unowned else f"{len(unowned)} actieve leg(s) hebben geen bewezen Strategy-2-ownership"),
        ReadinessCheck("open_orders", not open_orders, "Geen onbeoordeelde open orders" if not open_orders else f"{len(open_orders)} open order(s) moeten eerst worden gereconcilieerd"),
        ReadinessCheck("live_canary", canary_validated, "Minimale echte open/fill/close-canary is gevalideerd" if canary_validated else "Echte canary is nog niet met aparte toestemming uitgevoerd"),
    ]
    software_ready = all(x.passed for x in checks if x.key != "live_canary")
    live_ready = software_ready and canary_validated
    return {
        "softwareReady": software_ready, "liveReady": live_ready,
        "ordersSent": 0, "activePositions": len(active),
        "checks": [x.__dict__ for x in checks],
        "unownedPositions": [{"symbol": s, "side": side} for s, side in unowned],
        "message": "Live blijft vergrendeld tot alle controles én de afzonderlijk bevestigde canary slagen.",
    }
