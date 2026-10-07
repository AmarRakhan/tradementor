"""Read-only shadow planner for future exchange-native TP/DCA orders.

This module never talks to Aster and never submits/cancels/replaces an order.
It projects the exact next levels already used by the Multi-BB runtime so we can
measure whether exchange-native resting orders would preserve current behavior
before any live migration is attempted.
"""
from __future__ import annotations

import math
from typing import Any

from aster_multi_bb import MultiBbConfig, position_action_preview


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _normalized_position(row: dict[str, Any]) -> dict[str, Any]:
    side = str(row.get("positionSide", row.get("side", ""))).upper().strip()
    quantity = abs(_f(row.get("positionAmt", row.get("quantity"))))
    return {
        "symbol": str(row.get("symbol", "")).upper().strip(),
        "positionSide": side,
        "positionAmt": quantity,
        "entryPrice": _f(row.get("entryPrice")),
        "markPrice": _f(row.get("markPrice"), _f(row.get("entryPrice"))),
        "leverage": max(1, int(_f(row.get("leverage"), 1))),
    }


def build_native_order_shadow(
    *,
    positions: list[dict[str, Any]],
    managed_positions: dict[str, dict[str, Any]],
    settings: MultiBbConfig,
    auto_hedge_symbols: set[str] | None = None,
    account_equity: float = 0.0,
) -> dict[str, Any]:
    """Project one TP and one next-DCA resting order per managed open leg.

    canPreplaceNow intentionally remains false. The report is evidence for a
    future migration and documents which dynamic guards must be preserved.
    """
    protected = {str(symbol).upper() for symbol in (auto_hedge_symbols or set())}
    position_map: dict[str, dict[str, Any]] = {}
    for raw in positions or []:
        if not isinstance(raw, dict):
            continue
        row = _normalized_position(raw)
        if row["symbol"] and row["positionSide"] in {"LONG", "SHORT"} and row["positionAmt"] > 0:
            position_map[f'{row["symbol"]}|{row["positionSide"]}'] = row

    rows: list[dict[str, Any]] = []
    for key, state_raw in sorted((managed_positions or {}).items()):
        if not isinstance(state_raw, dict):
            continue
        normalized_key = str(key).upper()
        row = position_map.get(normalized_key)
        if row is None:
            continue
        state = dict(state_raw)
        preview = position_action_preview(
            row=row, state=state, settings=settings, account_equity=account_equity,
        )
        if not preview:
            continue

        symbol = row["symbol"]
        side = row["positionSide"]
        tp_price = preview.get("tpPrice")
        dca_price = preview.get("nextDcaPrice")
        stored_dca = _f(state.get("nextDcaPrice"))
        projected_dca = _f(dca_price)
        dca_parity = (
            dca_price is None and stored_dca <= 0
        ) or (
            projected_dca > 0
            and stored_dca > 0
            and abs(projected_dca - stored_dca) <= max(1e-10, abs(projected_dca) * 1e-9)
        )

        tp_blockers: list[str] = []
        if not settings.take_profit_enabled or tp_price is None:
            tp_blockers.append("TAKE_PROFIT_DISABLED")
        if bool(state.get("longTpBlocked")) and side == "LONG":
            tp_blockers.append("ASYMMETRIC_LONG_TP_BLOCKED")
        if symbol in protected:
            tp_blockers.append("AUTO_HEDGE_CLOSE_GUARD")
        tp_dynamic_guards = [
            "OWNERSHIP",
            "AUTO_HEDGE_CLOSE_LOCK",
            "CURRENT_QUANTITY",
            "CLOSE_EVIDENCE",
        ]

        dca_blockers: list[str] = []
        if dca_price is None:
            dca_blockers.append("DCA_DISABLED_OR_LIMIT_REACHED")
        if bool(state.get("tpRecoveryOnly")):
            dca_blockers.append("TP_RECOVERY_ONLY")
        dca_dynamic_guards = [
            "AVAILABLE_MARGIN",
            "LEVERAGE_TIER",
            "ACCOUNT_COORDINATION",
            "POSITION_OWNERSHIP",
            "CURRENT_CONFIG_VERSION",
        ]

        rows.append({
            "key": normalized_key,
            "symbol": symbol,
            "side": side,
            "quantity": row["positionAmt"],
            "entryPrice": row["entryPrice"],
            "markPrice": row["markPrice"],
            "dcaCount": int(_f(state.get("dcaCount"))),
            "currentRuntime": "SOFTWARE_TRIGGERED",
            "tp": {
                "targetPrice": tp_price,
                "orderIntent": "REDUCE_ONLY_LIMIT_CLOSE" if tp_price is not None else None,
                "blockers": tp_blockers,
                "dynamicGuards": tp_dynamic_guards,
                "shadowEligible": not tp_blockers,
                "canPreplaceNow": False,
            },
            "dca": {
                "targetPrice": dca_price,
                "nextDcaNumber": preview.get("nextDcaNumber"),
                "orderIntent": "LIMIT_OPEN_NEXT_DCA" if dca_price is not None else None,
                "storedTargetPrice": state.get("nextDcaPrice"),
                "targetParity": dca_parity,
                "blockers": dca_blockers,
                "dynamicGuards": dca_dynamic_guards,
                "shadowEligible": not dca_blockers and dca_parity,
                "canPreplaceNow": False,
            },
        })

    return {
        "mode": "SHADOW_ONLY",
        "ordersSent": 0,
        "exchangeCalls": 0,
        "managedOpenPositions": len(rows),
        "tpShadowEligible": sum(1 for row in rows if row["tp"]["shadowEligible"]),
        "dcaShadowEligible": sum(1 for row in rows if row["dca"]["shadowEligible"]),
        "allDcaTargetsMatchRuntimeState": all(row["dca"]["targetParity"] for row in rows),
        "rows": rows,
    }


def build_shadow_transition_plan(
    *,
    before_position: dict[str, Any] | None,
    after_position: dict[str, Any] | None,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any] | None,
    before_settings: MultiBbConfig,
    after_settings: MultiBbConfig,
    auto_hedge_before: bool = False,
    auto_hedge_after: bool = False,
    account_equity: float = 0.0,
) -> dict[str, Any]:
    """Describe hypothetical cancel/replace work after a confirmed state change.

    The returned actions are instructions for comparison only. They never execute.
    """
    before_state = dict(before_state or {})
    after_state = dict(after_state or {})
    before_row = _normalized_position(before_position or {})
    after_row = _normalized_position(after_position or {})

    before_open = (
        before_row["symbol"]
        and before_row["positionSide"] in {"LONG", "SHORT"}
        and before_row["positionAmt"] > 0
    )
    after_open = (
        after_row["symbol"]
        and after_row["positionSide"] in {"LONG", "SHORT"}
        and after_row["positionAmt"] > 0
    )

    before_preview = (
        position_action_preview(
            row=before_row,
            state=before_state,
            settings=before_settings,
            account_equity=account_equity,
        )
        if before_open else {}
    )
    after_preview = (
        position_action_preview(
            row=after_row,
            state=after_state,
            settings=after_settings,
            account_equity=account_equity,
        )
        if after_open else {}
    )

    actions: list[dict[str, Any]] = []

    def add(kind: str, reason: str, **payload: Any) -> None:
        actions.append({"kind": kind, "reason": reason, **payload})

    if before_open and not after_open:
        if before_preview.get("tpPrice") is not None:
            add("CANCEL_TP", "POSITION_CLOSED")
        if before_preview.get("nextDcaPrice") is not None:
            add("CANCEL_DCA", "POSITION_CLOSED")
    elif after_open:
        before_tp = _f(before_preview.get("tpPrice"))
        after_tp = _f(after_preview.get("tpPrice"))
        before_dca = _f(before_preview.get("nextDcaPrice"))
        after_dca = _f(after_preview.get("nextDcaPrice"))

        if auto_hedge_after:
            if before_tp > 0 or after_tp > 0:
                add("CANCEL_TP", "AUTO_HEDGE_CLOSE_GUARD")
        else:
            if after_tp > 0 and before_tp <= 0:
                add("PLACE_TP", "TP_BECAME_ELIGIBLE", targetPrice=after_tp)
            elif before_tp > 0 and after_tp <= 0:
                add("CANCEL_TP", "TP_DISABLED_OR_BLOCKED")
            elif before_tp > 0 and after_tp > 0 and abs(before_tp - after_tp) > max(1e-10, abs(after_tp) * 1e-9):
                add(
                    "REPLACE_TP",
                    "WEIGHTED_ENTRY_OR_CONFIG_CHANGED",
                    oldTargetPrice=before_tp,
                    newTargetPrice=after_tp,
                )
            elif (
                before_open
                and abs(before_row["positionAmt"] - after_row["positionAmt"])
                > max(1e-10, abs(after_row["positionAmt"]) * 1e-9)
                and after_tp > 0
            ):
                add(
                    "REPLACE_TP_QUANTITY",
                    "POSITION_QUANTITY_CHANGED",
                    targetPrice=after_tp,
                    oldQuantity=before_row["positionAmt"],
                    newQuantity=after_row["positionAmt"],
                )

        if after_dca > 0 and before_dca <= 0:
            add("PLACE_DCA", "NEXT_DCA_BECAME_ELIGIBLE", targetPrice=after_dca)
        elif before_dca > 0 and after_dca <= 0:
            add("CANCEL_DCA", "DCA_DISABLED_OR_LIMIT_REACHED")
        elif before_dca > 0 and after_dca > 0 and abs(before_dca - after_dca) > max(1e-10, abs(after_dca) * 1e-9):
            reason = (
                "DCA_FILL_REARM"
                if int(_f(after_state.get("dcaCount"))) > int(_f(before_state.get("dcaCount")))
                else "DCA_CONFIG_OR_ANCHOR_CHANGED"
            )
            add(
                "REPLACE_DCA",
                reason,
                oldTargetPrice=before_dca,
                newTargetPrice=after_dca,
                nextDcaNumber=after_preview.get("nextDcaNumber"),
            )

        if auto_hedge_before and not auto_hedge_after and after_tp > 0:
            add("REVALIDATE_TP_AFTER_HEDGE_RELEASE", "AUTO_HEDGE_RELEASED", targetPrice=after_tp)

    return {
        "mode": "SHADOW_ONLY",
        "ordersSent": 0,
        "exchangeCalls": 0,
        "beforeOpen": bool(before_open),
        "afterOpen": bool(after_open),
        "actions": actions,
        "requiresCancelReplace": bool(actions),
        "safetyContract": {
            "mustConfirmFillBeforeRearm": True,
            "mustRevalidateMarginBeforeDca": True,
            "mustRespectAutoHedgeCloseLock": True,
            "mustReconcileAfterRestart": True,
            "neverBlindRetryUncertainSubmission": True,
        },
    }
