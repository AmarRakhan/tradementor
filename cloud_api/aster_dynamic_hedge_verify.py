"""Independent read-only verification for Dynamic Hedge production activation.

The verifier compares the controller projection with raw Aster account and
position-risk fields. It never signs orders and never mutates state.
"""
from __future__ import annotations

from typing import Any
import math


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _close(actual: Any, expected: Any, *, floor: float = 0.02, rel: float = 1e-6) -> bool:
    a = _finite(actual); e = _finite(expected)
    if a is None or e is None:
        return False
    return abs(a - e) <= max(floor, abs(e) * rel)


def verify_read_only_projection(
    account: dict[str, Any],
    rows: list[dict[str, Any]],
    risk: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(code: str, passed: bool, actual: Any, expected: Any) -> None:
        checks.append({"code": code, "passed": bool(passed), "actual": actual, "expected": expected})

    margin_balance = _finite(account.get("totalMarginBalance"))
    maintenance = _finite(account.get("totalMaintMargin"))
    available = _finite(account.get("availableBalance"))
    check("RAW_MARGIN_BALANCE_PRESENT", margin_balance is not None, margin_balance, "finite totalMarginBalance")
    check("RAW_MAINTENANCE_PRESENT", maintenance is not None, maintenance, "finite totalMaintMargin")
    check("RAW_AVAILABLE_PRESENT", available is not None, available, "finite availableBalance")

    long_value = 0.0
    short_value = 0.0
    active_count = 0
    invalid_count = 0
    for row in rows:
        if not isinstance(row, dict):
            invalid_count += 1
            continue
        qty = _finite(row.get("positionAmt", row.get("quantity")))
        if qty is None or abs(qty) <= 1e-12:
            continue
        margin_type = str(row.get("marginType", "isolated" if row.get("isolated") is True else "cross")).lower()
        if margin_type == "isolated":
            continue
        active_count += 1
        side = str(row.get("positionSide", row.get("side", ""))).upper()
        mark = _finite(row.get("markPrice"))
        if mark is None or mark <= 0 or side not in {"LONG", "SHORT"}:
            invalid_count += 1
            continue
        notional = abs(qty) * mark
        if side == "LONG": long_value += notional
        else: short_value += notional

    gross = long_value + short_value
    signed_net = long_value - short_value
    dominant = max(long_value, short_value)
    coverage = 100.0 if dominant <= 0 else min(long_value, short_value) / dominant * 100.0
    margin_buffer = None if margin_balance is None or maintenance is None else margin_balance - maintenance
    buffer_ratio = None if margin_balance is None or maintenance is None or maintenance <= 0 else margin_balance / maintenance

    check("POSITION_ROWS_CLASSIFIABLE", invalid_count == 0, invalid_count, 0)
    check("POSITION_COUNT_MATCH", int(risk.get("positionCountIncluded", -1)) == active_count, risk.get("positionCountIncluded"), active_count)
    check("LONG_EXPOSURE_MATCH", _close(risk.get("longNotional"), long_value), risk.get("longNotional"), long_value)
    check("SHORT_EXPOSURE_MATCH", _close(risk.get("shortNotional"), short_value), risk.get("shortNotional"), short_value)
    check("GROSS_EXPOSURE_MATCH", _close(risk.get("grossExposure"), gross), risk.get("grossExposure"), gross)
    check("SIGNED_NET_MATCH", _close(risk.get("signedNetExposure"), signed_net), risk.get("signedNetExposure"), signed_net)
    check("HEDGE_COVERAGE_MATCH", _close(risk.get("hedgeCoveragePercent"), coverage, floor=1e-4), risk.get("hedgeCoveragePercent"), coverage)
    if margin_balance is not None:
        check("EQUITY_MATCH", _close(risk.get("equity"), margin_balance), risk.get("equity"), margin_balance)
    if maintenance is not None:
        check("MAINTENANCE_MATCH", _close(risk.get("maintenanceMarginUsd"), maintenance), risk.get("maintenanceMarginUsd"), maintenance)
    if margin_buffer is not None:
        check("MARGIN_BUFFER_MATCH", _close(risk.get("marginBufferUsd"), margin_buffer), risk.get("marginBufferUsd"), margin_buffer)
    if buffer_ratio is not None:
        check("BUFFER_RATIO_MATCH", _close(risk.get("bufferRatio"), buffer_ratio, floor=1e-8), risk.get("bufferRatio"), buffer_ratio)

    failures = [item for item in checks if not item["passed"]]
    return {
        "passed": not failures,
        "readOnly": True,
        "ordersSubmitted": 0,
        "checks": checks,
        "failureCodes": [item["code"] for item in failures],
        "raw": {
            "equity": margin_balance,
            "maintenanceMarginUsd": maintenance,
            "availableBalance": available,
            "longExposureUsd": long_value,
            "shortExposureUsd": short_value,
            "grossExposureUsd": gross,
            "netExposureUsd": signed_net,
            "hedgeCoveragePercent": coverage,
            "positionCount": active_count,
        },
    }
