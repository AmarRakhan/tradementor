"""Account-wide Aster cross-margin risk projection.

Liquidation proximity is derived from Aster account totals, never from averaging
position-level percentages. Position rows are used only for diagnostics and the
separate weighted maintenance-rate gauge.
"""
from __future__ import annotations

import math
from typing import Any

from aster_dynamic_hedge import DynamicHedgeConfig, robust_hedge_coverage, safety_status


def _f(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _present(mapping: dict[str, Any], key: str) -> bool:
    return key in mapping and mapping.get(key) not in (None, "")


def _active(row: dict[str, Any]) -> bool:
    return abs(_f(row.get("positionAmt", row.get("quantity")))) > 1e-12


def _cross(row: dict[str, Any]) -> bool:
    if row.get("isolated") is True:
        return False
    margin_type = str(row.get("marginType", row.get("margin_type", "cross"))).lower()
    return margin_type != "isolated"


def _official_ratio_percent(account: dict[str, Any]) -> float | None:
    # Some Aster account variants expose a ready margin ratio. Accept either a
    # 0..1 ratio or an already-percent value, but only when it is finite/nonnegative.
    for key in ("marginRatio", "crossMarginRatio", "totalMarginRatio"):
        raw = account.get(key)
        if raw in (None, ""):
            continue
        value = _f(raw)
        if value < 0:
            continue
        return value * 100 if value <= 1.5 else value
    return None


def cross_account_risk(account: dict[str, Any], positions: list[dict[str, Any]]) -> dict[str, Any]:
    active = [row for row in positions if isinstance(row, dict) and _active(row)]
    cross = [row for row in active if _cross(row)]
    margin_balance = _f(account.get("totalMarginBalance"))
    wallet = _f(account.get("totalWalletBalance"))
    unrealized = _f(account.get("totalUnrealizedProfit"))
    equity = margin_balance if _present(account, "totalMarginBalance") else wallet + unrealized
    maintenance = _f(account.get("totalMaintMargin"))

    long_notional = 0.0
    short_notional = 0.0
    for row in cross:
        quantity = abs(_f(row.get("positionAmt", row.get("quantity"))))
        mark = _f(row.get("markPrice")) or _f(row.get("entryPrice"))
        notional = quantity * mark
        side = str(row.get("positionSide", row.get("side", ""))).upper()
        if side == "LONG":
            long_notional += notional
        elif side == "SHORT":
            short_notional += notional

    gross = long_notional + short_notional
    signed_net = long_notional - short_notional
    net = abs(signed_net)
    official = _official_ratio_percent(account)
    if official is not None:
        liquidation_pct = official
        source = "ASTER_ACCOUNT_RATIO"
    elif equity > 0:
        liquidation_pct = maintenance / equity * 100
        source = "SERVER_RECONSTRUCTED"
    else:
        liquidation_pct = 100.0 if active and maintenance > 0 else 0.0
        source = "SERVER_RECONSTRUCTED"

    maintenance_pct = maintenance / gross * 100 if gross > 0 else 0.0
    margin_buffer = equity - maintenance
    buffer_ratio = equity / maintenance if maintenance > 0 else None
    reliable = (
        (_present(account, "totalMarginBalance") or _present(account, "totalWalletBalance"))
        and _present(account, "totalMaintMargin")
    )
    result = {
        "reliable": reliable,
        "maintenanceMarginUsd": maintenance,
        "maintenanceMarginPct": max(0.0, maintenance_pct),
        "liquidationRiskPct": max(0.0, min(100.0, liquidation_pct)),
        "liquidationRiskSource": source,
        "marginBalance": margin_balance,
        "equity": equity,
        "totalUnrealizedPnl": unrealized,
        "totalCrossNotional": gross,
        "longNotional": long_notional,
        "shortNotional": short_notional,
        "netExposure": net,
        "signedNetExposure": signed_net,
        "netSide": "FLAT" if abs(signed_net) < 1e-9 else ("LONG" if signed_net > 0 else "SHORT"),
        "grossExposure": gross,
        "hedgeCoveragePercent": robust_hedge_coverage(long_notional, short_notional),
        "marginBufferUsd": margin_buffer,
        "bufferRatio": buffer_ratio,
        "positionCountIncluded": len(cross),
    }
    result["liquidationSafetyStatus"] = safety_status(result, DynamicHedgeConfig())
    return result
