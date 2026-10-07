"""Read-only exchange-order shadow planner for Aster Multi-BB.

This module never submits, cancels or replaces an exchange order.  It projects
which *single next* TP and DCA orders could be staged exchange-side if a later
migration proves all existing runtime safety gates can be preserved.

The production execution engine remains authoritative.
"""
from __future__ import annotations

from typing import Any

from aster_multi_bb_core import MultiBbConfig, position_action_preview


def _side(value: Any) -> str:
    text = str(value or "").upper().strip()
    return text if text in {"LONG", "SHORT"} else ""


def shadow_exchange_orders(
    *,
    row: dict[str, Any],
    state: dict[str, Any],
    settings: MultiBbConfig,
    auto_hedge_managed: bool = False,
    portfolio_tp_active: bool = False,
) -> dict[str, Any]:
    """Project at most one TP and one next-DCA order without any side effects.

    The result is deliberately conservative.  It does not claim a DCA is safe
    to pre-place until the current engine's pre-submit margin/leverage/ownership
    checks have also been proven equivalent for resting orders.
    """
    preview = position_action_preview(row=row, state=state, settings=settings)
    side = _side(row.get("positionSide"))
    symbol = str(row.get("symbol") or "").upper().strip()
    quantity = abs(float(row.get("positionAmt") or 0))
    if not preview or not symbol or not side or quantity <= 0:
        return {
            "shadowOnly": True,
            "eligible": False,
            "reason": "POSITION_TRUTH_INCOMPLETE",
            "orders": [],
        }

    orders: list[dict[str, Any]] = []

    tp_price = preview.get("tpPrice")
    if tp_price:
        tp_blockers: list[str] = []
        if auto_hedge_managed:
            tp_blockers.append("AUTO_HEDGE_MANAGED")
        if portfolio_tp_active:
            tp_blockers.append("PORTFOLIO_TP_OWNS_EXIT")
        if bool(state.get("longTpBlocked")) and side == "LONG":
            tp_blockers.append("ASYMMETRIC_LONG_TP_BLOCKED")
        if bool(state.get("disableShortTp")) and side == "SHORT":
            tp_blockers.append("ASYMMETRIC_SHORT_TP_DISABLED")
        orders.append({
            "kind": "TAKE_PROFIT",
            "symbol": symbol,
            "side": side,
            "exchangeSide": "SELL" if side == "LONG" else "BUY",
            "positionSide": side,
            "price": float(tp_price),
            "quantity": quantity,
            "reduceOnly": True,
            "candidateStatus": "BLOCKED" if tp_blockers else "SHADOW_READY",
            "blockers": tp_blockers,
            "requiresCancelReplaceAfterFill": True,
        })

    dca_price = preview.get("nextDcaPrice")
    if dca_price:
        dca_blockers: list[str] = []
        if bool(state.get("tpRecoveryOnly")):
            dca_blockers.append("TP_RECOVERY_ONLY")
        if auto_hedge_managed:
            dca_blockers.append("AUTO_HEDGE_REVALIDATION_REQUIRED")
        # Current runtime performs these checks immediately before every DCA.
        # A future resting-order migration must preserve the same guarantees.
        required_checks = [
            "ACCOUNT_COORDINATION_LEASE",
            "STRATEGY_QUEUE_LEASE",
            "CURRENT_MARGIN_AVAILABLE",
            "CURRENT_CONTRACT_LEVERAGE_TIER",
            "CURRENT_CONFIG_VERSION",
            "POSITION_OWNERSHIP",
            "PRICE_ZONE_POLICY_WHERE_APPLICABLE",
        ]
        orders.append({
            "kind": "NEXT_DCA",
            "symbol": symbol,
            "side": side,
            "exchangeSide": "BUY" if side == "LONG" else "SELL",
            "positionSide": side,
            "price": float(dca_price),
            "dcaNumber": preview.get("nextDcaNumber"),
            "reduceOnly": False,
            "candidateStatus": "BLOCKED" if dca_blockers else "SHADOW_CONDITIONAL",
            "blockers": dca_blockers,
            "requiresBeforePlacementChecks": required_checks,
            "placeOnlyOneNextDca": True,
            "recomputeAfterFill": True,
        })

    return {
        "shadowOnly": True,
        "eligible": bool(orders),
        "symbol": symbol,
        "side": side,
        "orders": orders,
        "source": "position_action_preview",
        "executionChanged": False,
    }
