"""Read-only shadow planner for future exchange-native TP/DCA orders.

No exchange calls, no Firestore writes, no order placement. The planner mirrors
the current Multi-BB TP/next-DCA formulas and emits the lifecycle action a future
native-order controller would need (place/keep/cancel-replace/hold).
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from aster_multi_bb import MultiBbConfig, position_action_preview


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _position(row: dict[str, Any]) -> dict[str, Any]:
    side = str(row.get("positionSide", row.get("side", ""))).upper().strip()
    quantity = abs(_f(row.get("positionAmt", row.get("quantity"))))
    entry = _f(row.get("entryPrice"))
    return {
        "symbol": str(row.get("symbol", "")).upper().strip(),
        "positionSide": side,
        "positionAmt": quantity,
        "entryPrice": entry,
        "markPrice": _f(row.get("markPrice"), entry),
        "leverage": max(1, int(_f(row.get("leverage"), 1))),
    }


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()[:24]


def _lifecycle(*, desired: dict[str, Any] | None, previous: dict[str, Any] | None,
               blockers: list[str]) -> dict[str, Any]:
    if blockers or desired is None:
        return {
            "action": "HOLD",
            "reason": blockers[0] if blockers else "NO_DESIRED_ORDER",
            "previousOrderShouldRemain": False,
        }
    desired_fp = _fingerprint(desired)
    previous_fp = str((previous or {}).get("fingerprint") or "")
    if not previous:
        action, reason = "WOULD_PLACE", "NO_PREVIOUS_SHADOW_ORDER"
    elif previous_fp == desired_fp:
        action, reason = "WOULD_KEEP", "DESIRED_ORDER_UNCHANGED"
    else:
        action, reason = "WOULD_CANCEL_REPLACE", "DESIRED_ORDER_CHANGED"
    return {
        "action": action,
        "reason": reason,
        "fingerprint": desired_fp,
        "previousFingerprint": previous_fp or None,
        "previousOrderShouldRemain": action == "WOULD_KEEP",
    }


def build_native_order_shadow(
    *,
    positions: list[dict[str, Any]],
    managed_positions: dict[str, dict[str, Any]],
    settings: MultiBbConfig,
    auto_hedge_symbols: set[str] | None = None,
    account_equity: float = 0.0,
    previous_shadow: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    protected = {str(symbol).upper() for symbol in (auto_hedge_symbols or set())}
    previous_shadow = previous_shadow or {}

    pmap: dict[str, dict[str, Any]] = {}
    for raw in positions or []:
        if not isinstance(raw, dict):
            continue
        row = _position(raw)
        if row["symbol"] and row["positionSide"] in {"LONG", "SHORT"} and row["positionAmt"] > 0:
            pmap[f'{row["symbol"]}|{row["positionSide"]}'] = row

    rows: list[dict[str, Any]] = []
    for key, state_raw in sorted((managed_positions or {}).items()):
        if not isinstance(state_raw, dict):
            continue
        key = str(key).upper()
        row = pmap.get(key)
        if row is None:
            continue

        state = dict(state_raw)
        preview = position_action_preview(
            row=row, state=state, settings=settings, account_equity=account_equity,
        )
        if not preview:
            continue

        symbol, side = row["symbol"], row["positionSide"]
        tp_price = preview.get("tpPrice")
        dca_price = preview.get("nextDcaPrice")
        stored_dca = _f(state.get("nextDcaPrice"))
        projected_dca = _f(dca_price)
        dca_parity = (
            dca_price is None and stored_dca <= 0
        ) or (
            projected_dca > 0 and stored_dca > 0
            and abs(projected_dca - stored_dca) <= max(1e-10, abs(projected_dca) * 1e-9)
        )

        tp_blockers: list[str] = []
        if not settings.take_profit_enabled or tp_price is None:
            tp_blockers.append("TAKE_PROFIT_DISABLED")
        if bool(state.get("longTpBlocked")) and side == "LONG":
            tp_blockers.append("ASYMMETRIC_LONG_TP_BLOCKED")
        if symbol in protected:
            tp_blockers.append("AUTO_HEDGE_CLOSE_GUARD")

        dca_blockers: list[str] = []
        if dca_price is None:
            dca_blockers.append("DCA_DISABLED_OR_LIMIT_REACHED")
        if bool(state.get("tpRecoveryOnly")):
            dca_blockers.append("TP_RECOVERY_ONLY")
        if not dca_parity:
            dca_blockers.append("RUNTIME_TARGET_DRIFT")
        persisted_version = int(_f(state.get("policyConfigVersion")))
        current_version = max(1, int(_f(getattr(settings, "version", 1), 1)))
        if persisted_version > 0 and persisted_version != current_version:
            dca_blockers.append("CONFIG_VERSION_CHANGED")

        tp_desired = None if tp_price is None else {
            "kind": "TP",
            "symbol": symbol,
            "side": side,
            "price": tp_price,
            "quantity": row["positionAmt"],
            "reduceOnly": True,
            "positionSide": side,
        }
        dca_desired = None if dca_price is None else {
            "kind": "NEXT_DCA",
            "symbol": symbol,
            "side": side,
            "price": dca_price,
            "dcaNumber": preview.get("nextDcaNumber"),
            "reduceOnly": False,
            "positionSide": side,
            "policyConfigVersion": current_version,
        }

        previous = previous_shadow.get(key) if isinstance(previous_shadow.get(key), dict) else {}
        previous_tp = previous.get("tp") if isinstance(previous.get("tp"), dict) else None
        previous_dca = previous.get("dca") if isinstance(previous.get("dca"), dict) else None

        tp_lifecycle = _lifecycle(desired=tp_desired, previous=previous_tp, blockers=tp_blockers)
        dca_lifecycle = _lifecycle(desired=dca_desired, previous=previous_dca, blockers=dca_blockers)

        rows.append({
            "key": key,
            "symbol": symbol,
            "side": side,
            "quantity": row["positionAmt"],
            "entryPrice": row["entryPrice"],
            "markPrice": row["markPrice"],
            "dcaCount": int(_f(state.get("dcaCount"))),
            "currentRuntime": "SOFTWARE_TRIGGERED",
            "tp": {
                "targetPrice": tp_price,
                "desiredOrder": tp_desired,
                "blockers": tp_blockers,
                "dynamicGuardsBeforeNativeMigration": [
                    "OWNERSHIP",
                    "AUTO_HEDGE_CLOSE_LOCK",
                    "CURRENT_QUANTITY",
                    "CLOSE_EVIDENCE",
                    "MANUAL_POSITION_CHANGE",
                ],
                "shadowEligible": not tp_blockers,
                "canPreplaceNow": False,
                "lifecycle": tp_lifecycle,
            },
            "dca": {
                "targetPrice": dca_price,
                "nextDcaNumber": preview.get("nextDcaNumber"),
                "desiredOrder": dca_desired,
                "storedTargetPrice": state.get("nextDcaPrice"),
                "targetParity": dca_parity,
                "blockers": dca_blockers,
                "dynamicGuardsBeforeNativeMigration": [
                    "AVAILABLE_MARGIN",
                    "LEVERAGE_TIER",
                    "ACCOUNT_COORDINATION",
                    "POSITION_OWNERSHIP",
                    "CURRENT_CONFIG_VERSION",
                    "MANUAL_POSITION_CHANGE",
                ],
                "shadowEligible": not dca_blockers,
                "canPreplaceNow": False,
                "lifecycle": dca_lifecycle,
            },
        })

    return {
        "mode": "SHADOW_ONLY",
        "ordersSent": 0,
        "ordersCancelled": 0,
        "ordersReplaced": 0,
        "exchangeCalls": 0,
        "managedOpenPositions": len(rows),
        "tpShadowEligible": sum(1 for row in rows if row["tp"]["shadowEligible"]),
        "dcaShadowEligible": sum(1 for row in rows if row["dca"]["shadowEligible"]),
        "allDcaTargetsMatchRuntimeState": all(row["dca"]["targetParity"] for row in rows),
        "wouldPlace": sum(
            int(row["tp"]["lifecycle"]["action"] == "WOULD_PLACE")
            + int(row["dca"]["lifecycle"]["action"] == "WOULD_PLACE")
            for row in rows
        ),
        "wouldCancelReplace": sum(
            int(row["tp"]["lifecycle"]["action"] == "WOULD_CANCEL_REPLACE")
            + int(row["dca"]["lifecycle"]["action"] == "WOULD_CANCEL_REPLACE")
            for row in rows
        ),
        "rows": rows,
    }
