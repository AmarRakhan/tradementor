"""Read-only Portfolio Koers chart primitives.

This module owns no exchange client and submits no orders. It only normalizes
confirmed portfolio-equity samples, display zones and read-only chart markers.
"""
from __future__ import annotations

import math
from typing import Any

TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1u": 60 * 60_000,
    "4u": 4 * 60 * 60_000,
    "24u": 24 * 60 * 60_000,
}
COLLECTION_BY_TIMEFRAME: dict[str, str] = {
    "1m": "asterPortfolioChart1m",
    "5m": "asterPortfolioChart5m",
    "15m": "asterPortfolioChart15m",
    "1u": "asterPortfolioChart1h",
    "4u": "asterPortfolioChart4h",
    "24u": "asterPortfolioChart24h",
}
EXTERNAL_CASHFLOW_TYPES = frozenset({
    "TRANSFER", "DEPOSIT", "WITHDRAWAL", "WALLET_TRANSFER", "INTERNAL_TRANSFER",
    "WELCOME_BONUS", "INSURANCE_CLEAR", "BALANCE_ADJUSTMENT",
})
CASHFLOW_ADJUSTMENT_TYPES = frozenset({"WELCOME_BONUS", "INSURANCE_CLEAR", "BALANCE_ADJUSTMENT"})


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def bucket_start_ms(timestamp_ms: int, timeframe: str) -> int:
    interval = TIMEFRAME_MS.get(str(timeframe))
    if not interval:
        raise ValueError("Onbekend Portfolio Koers-timeframe")
    stamp = max(0, int(timestamp_ms))
    return stamp // interval * interval


def latest_contiguous_candles(candles: list[dict[str, Any]] | None, timeframe: str) -> list[dict[str, Any]]:
    """Return only the newest uninterrupted candle run.

    Missing equity buckets are never fabricated. A zone calculation must not
    bridge an unobserved time gap because that would turn one discontinuity into
    artificial ATR/support/resistance evidence.
    """
    interval = TIMEFRAME_MS.get(str(timeframe))
    if not interval:
        raise ValueError("Onbekend Portfolio Koers-timeframe")
    rows = [dict(row) for row in candles or [] if isinstance(row, dict)]
    rows.sort(key=lambda row: int(_number(row.get("atMs"))) or int(_number(row.get("time"))) * 1000)
    if not rows:
        return []
    start = 0
    previous_ms = int(_number(rows[0].get("atMs"))) or int(_number(rows[0].get("time"))) * 1000
    for index in range(1, len(rows)):
        current_ms = int(_number(rows[index].get("atMs"))) or int(_number(rows[index].get("time"))) * 1000
        if previous_ms > 0 and current_ms - previous_ms > interval:
            start = index
        previous_ms = current_ms
    return rows[start:]


def collection_for_timeframe(timeframe: str) -> str:
    try:
        return COLLECTION_BY_TIMEFRAME[str(timeframe)]
    except KeyError as exc:
        raise ValueError("Onbekend Portfolio Koers-timeframe") from exc


def merge_equity_sample(existing: dict[str, Any] | None, *, equity: float, source_at_ms: int, timeframe: str) -> dict[str, Any]:
    """Merge one exchange-confirmed equity sample into one OHLC bucket."""
    value = _number(equity)
    stamp = int(source_at_ms)
    if value <= 0 or stamp <= 0:
        raise ValueError("Portfolio-equity sample is ongeldig")
    bucket = bucket_start_ms(stamp, timeframe)
    current = existing if isinstance(existing, dict) else {}
    if int(_number(current.get("bucketMs"))) != bucket:
        current = {}
    first = int(_number(current.get("firstSampleAtMs"))) or stamp
    last = int(_number(current.get("lastSampleAtMs"))) or stamp
    opened = _number(current.get("open")) or value
    high = _number(current.get("high")) or value
    low = _number(current.get("low")) or value
    close = _number(current.get("close")) or value
    samples = max(0, int(_number(current.get("sampleCount"))))
    duplicate = bool(current and stamp == last and abs(value - close) <= 1e-12)

    if stamp < first:
        first, opened = stamp, value
    if stamp >= last:
        last, close = stamp, value

    return {
        "timeframe": timeframe,
        "bucketMs": bucket,
        "open": opened,
        "high": max(high, value),
        "low": min(low, value),
        "close": close,
        "firstSampleAtMs": first,
        "lastSampleAtMs": last,
        "sampleCount": samples if duplicate else samples + 1,
        "source": "aster-account-equity",
    }


def public_candle(row: dict[str, Any]) -> dict[str, Any] | None:
    bucket = int(_number(row.get("bucketMs")))
    opened, high, low, close = (_number(row.get(key)) for key in ("open", "high", "low", "close"))
    if bucket <= 0 or min(opened, high, low, close) <= 0 or high < low:
        return None
    return {
        "time": bucket // 1000,
        "atMs": bucket,
        "open": opened,
        "high": high,
        "low": low,
        "close": close,
        "samples": max(1, int(_number(row.get("sampleCount")))),
        "firstSampleAtMs": int(_number(row.get("firstSampleAtMs"))) or bucket,
        "sourceAtMs": int(_number(row.get("lastSampleAtMs"))),
    }


def _event_timestamp_ms(row: dict[str, Any]) -> int:
    return int(_number(row.get("timestampMs"))) or int(_number(row.get("time")))


def aggregate_trade_activity(activity: dict[str, Any] | None, timeframe: str) -> list[dict[str, Any]]:
    """Aggregate confirmed Aster entries/exits into compact portfolio markers."""
    if timeframe not in TIMEFRAME_MS:
        return []
    groups: dict[tuple[int, str, str], dict[str, Any]] = {}
    payload = activity if isinstance(activity, dict) else {}
    for list_name, kind in (("entries", "entry"), ("exits", "tp")):
        for raw in payload.get(list_name, []) if isinstance(payload.get(list_name), list) else []:
            if not isinstance(raw, dict):
                continue
            stamp = _event_timestamp_ms(raw)
            side = str(raw.get("side", "")).upper()
            if stamp <= 0 or side not in {"LONG", "SHORT"}:
                continue
            bucket = bucket_start_ms(stamp, timeframe)
            group_side = side if kind == "entry" else "ALL"
            key = (bucket, kind, group_side)
            group = groups.setdefault(key, {
                "time": bucket // 1000,
                "atMs": bucket,
                "kind": kind,
                "side": group_side,
                "count": 0,
                "notionalUsd": 0.0,
                "realizedPnlUsd": 0.0,
                "source": "aster-confirmed-fills",
            })
            group["count"] += 1
            group["notionalUsd"] += abs(_number(raw.get("executedNotionalUsd", raw.get("notionalUsd"))))
            group["realizedPnlUsd"] += _number(raw.get("realizedPnlUsd"))
            if kind == "entry":
                origin = raw.get("originZone")
                if isinstance(origin, int) or (isinstance(origin, str) and origin.lstrip("-+").isdigit()):
                    group.setdefault("originZones", [])
                    value = int(origin)
                    if value not in group["originZones"]:
                        group["originZones"].append(value)
                role = str(raw.get("soldierRole", "")).upper().strip()
                if role:
                    group.setdefault("soldierRoles", [])
                    if role not in group["soldierRoles"]:
                        group["soldierRoles"].append(role)
    result = []
    for group in groups.values():
        if isinstance(group.get("originZones"), list):
            group["originZones"].sort()
        if isinstance(group.get("soldierRoles"), list):
            group["soldierRoles"].sort()
        if group["kind"] == "entry":
            side_letter = "L" if group["side"] == "LONG" else "S"
            amount = group["notionalUsd"]
            group["label"] = f"ENTRY {side_letter}" + (f" · ${amount:.2f}" if amount > 0 else "")
        else:
            pnl = group["realizedPnlUsd"]
            prefix = "TP" if pnl >= 0 else "EXIT"
            group["label"] = f"{prefix} · {pnl:+.2f} USD"
        result.append(group)
    return sorted(result, key=lambda row: (int(row["atMs"]), str(row["kind"]), str(row["side"])))


def strategy_audit_trade_markers(rows: list[dict[str, Any]] | None, timeframe: str) -> list[dict[str, Any]]:
    """Project fresh confirmed Strategy-2 audit actions into chart markers.

    This is intentionally independent from Aster fill-history polling.  The
    trading runtime writes these audit rows only after an execution path has
    confirmed its action, so Portfolio Koers can surface the event immediately
    while the heavier exchange fill cache catches up later.
    """
    if timeframe not in TIMEFRAME_MS:
        return []
    event_map = {
        "MULTI_BB_ENTRY": ("entry", None, "ENTRY"),
        "MULTI_BB_DCA": ("entry", None, "DCA"),
        "MULTI_BB_TP": ("tp", "ALL", "TP"),
        "MULTI_BB_ASYM_SHORT_ENTRY": ("entry", "SHORT", "ENTRY"),
        "MANUAL_DCA_DETECTED": ("entry", None, "DCA"),
    }
    groups: dict[tuple[int, str, str], dict[str, Any]] = {}
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        event = str(raw.get("event", "")).upper().strip()
        mapped = event_map.get(event)
        if mapped is None:
            continue
        kind, forced_side, activity_type = mapped
        stamp = _event_timestamp_ms(raw)
        side = str(forced_side or raw.get("side", "")).upper()
        if stamp <= 0:
            continue
        if kind == "entry" and side not in {"LONG", "SHORT"}:
            continue
        group_side = side if kind == "entry" else "ALL"
        bucket = bucket_start_ms(stamp, timeframe)
        key = (bucket, kind, group_side)
        group = groups.setdefault(key, {
            "time": bucket // 1000,
            "atMs": bucket,
            "kind": kind,
            "side": group_side,
            "count": 0,
            "notionalUsd": 0.0,
            "realizedPnlUsd": 0.0,
            "source": "strategy2-confirmed-audit",
            "activityTypes": [],
        })
        group["count"] += 1
        if activity_type not in group["activityTypes"]:
            group["activityTypes"].append(activity_type)
        if kind == "entry":
            origin = raw.get("originZone")
            if isinstance(origin, int) or (isinstance(origin, str) and origin.lstrip("-+").isdigit()):
                group.setdefault("originZones", [])
                value = int(origin)
                if value not in group["originZones"]:
                    group["originZones"].append(value)
            role = str(raw.get("soldierRole", "")).upper().strip()
            if role:
                group.setdefault("soldierRoles", [])
                if role not in group["soldierRoles"]:
                    group["soldierRoles"].append(role)

    result: list[dict[str, Any]] = []
    for group in groups.values():
        if isinstance(group.get("originZones"), list):
            group["originZones"].sort()
        if isinstance(group.get("soldierRoles"), list):
            group["soldierRoles"].sort()
        group["activityTypes"].sort()
        if group["kind"] == "entry":
            side_letter = "L" if group["side"] == "LONG" else "S"
            prefix = "DCA" if group["activityTypes"] == ["DCA"] else "ENTRY"
            group["label"] = f"{prefix} {side_letter}"
        else:
            group["label"] = "TP"
        result.append(group)
    return sorted(result, key=lambda row: (int(row["atMs"]), str(row["kind"]), str(row["side"])))


def external_cashflow_markers(rows: list[dict[str, Any]] | None, timeframe: str) -> list[dict[str, Any]]:
    """Keep external balance movements separate from trading performance.

    TRANSFER-like rows are classified by their signed amount so deposits and
    withdrawals inside the same chart candle never cancel into one ambiguous
    marker.  Adjustment/bonus rows remain a separate category.
    """
    if timeframe not in TIMEFRAME_MS:
        return []
    grouped: dict[tuple[int, str], dict[str, Any]] = {}
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        ledger_type = str(raw.get("incomeType", "")).upper().strip()
        if ledger_type not in EXTERNAL_CASHFLOW_TYPES:
            continue
        stamp = int(_number(raw.get("time", raw.get("timestamp"))))
        amount = _number(raw.get("income", raw.get("amount")))
        if stamp <= 0 or abs(amount) <= 1e-12:
            continue
        cashflow_type = (
            "ADJUSTMENT" if ledger_type in CASHFLOW_ADJUSTMENT_TYPES
            else "DEPOSIT" if amount > 0
            else "WITHDRAWAL"
        )
        bucket = bucket_start_ms(stamp, timeframe)
        key = (bucket, cashflow_type)
        group = grouped.setdefault(key, {
            "time": bucket // 1000,
            "atMs": bucket,
            "kind": "cashflow",
            "cashflowType": cashflow_type,
            "ledgerTypes": [],
            "amountUsd": 0.0,
            "count": 0,
            "source": "aster-income-ledger",
        })
        if ledger_type not in group["ledgerTypes"]:
            group["ledgerTypes"].append(ledger_type)
        group["amountUsd"] += amount
        group["count"] += 1
    result = []
    labels = {"DEPOSIT": "STORTING", "WITHDRAWAL": "OPNAME", "ADJUSTMENT": "AANPASSING"}
    for group in grouped.values():
        amount = _number(group.get("amountUsd"))
        group["ledgerTypes"].sort()
        group["label"] = f"{labels.get(str(group['cashflowType']), 'CASHFLOW')} · {amount:+.2f} USD"
        result.append(group)
    return sorted(result, key=lambda row: (int(row["atMs"]), str(row["cashflowType"])))

def _true_ranges(candles: list[dict[str, Any]]) -> list[float]:
    result: list[float] = []
    previous_close = 0.0
    for candle in candles:
        high, low, close = (_number(candle.get(key)) for key in ("high", "low", "close"))
        if min(high, low, close) <= 0 or high < low:
            continue
        tr = high - low if previous_close <= 0 else max(high - low, abs(high - previous_close), abs(low - previous_close))
        result.append(tr)
        previous_close = close
    return result


def atr(candles: list[dict[str, Any]], period: int = 14) -> float:
    ranges = _true_ranges(candles)
    if not ranges:
        return 0.0
    window = ranges[-max(1, int(period)):]
    return sum(window) / len(window)


def _confirmed_swings(candles: list[dict[str, Any]], wing: int = 2) -> list[dict[str, Any]]:
    """Confirm swings only after later candle closes exist; no look-ahead in live use."""
    result: list[dict[str, Any]] = []
    width = max(1, int(wing))
    for index in range(width, len(candles) - width):
        candle = candles[index]
        high, low = _number(candle.get("high")), _number(candle.get("low"))
        if high <= 0 or low <= 0:
            continue
        left = candles[index-width:index]
        right = candles[index+1:index+width+1]
        left_highs = [_number(row.get("high")) for row in left]
        right_highs = [_number(row.get("high")) for row in right]
        left_lows = [_number(row.get("low")) for row in left]
        right_lows = [_number(row.get("low")) for row in right]
        right_closes = [_number(row.get("close")) for row in right]
        # Equal neighbouring highs/lows form real market plateaus. Treat the
        # plateau edge as a confirmed swing when it still dominates one side;
        # subsequent ATR clustering collapses duplicate touches into one zone.
        high_is_local = high >= max(left_highs + right_highs) and (high > max(left_highs) or high > max(right_highs))
        low_is_local = low <= min(left_lows + right_lows) and (low < min(left_lows) or low < min(right_lows))
        if high_is_local and any(0 < close < high for close in right_closes):
            result.append({"price": high, "kind": "resistance", "index": index, "atMs": int(_number(candle.get("atMs")))})
        if low_is_local and any(close > low for close in right_closes):
            result.append({"price": low, "kind": "support", "index": index, "atMs": int(_number(candle.get("atMs")))})
    return result


def derive_equity_zones(candles: list[dict[str, Any]], cycle_start_equity: float = 0.0) -> list[dict[str, Any]]:
    """Build relative Zone 0/±N solely from confirmed swings, S/R clustering and ATR."""
    clean = [row for row in candles if isinstance(row, dict) and _number(row.get("close")) > 0]
    if len(clean) < 7:
        return []
    volatility = atr(clean, 14)
    if volatility <= 0:
        return []
    swings = _confirmed_swings(clean, 2)
    if len(swings) < 2:
        return []

    threshold = max(volatility * 0.55, 1e-9)
    clusters: list[dict[str, Any]] = []
    for swing in sorted(swings, key=lambda row: _number(row.get("price"))):
        price = _number(swing.get("price"))
        target = next((cluster for cluster in clusters if abs(price - _number(cluster["center"])) <= threshold), None)
        if target is None:
            clusters.append({"center": price, "prices": [price], "touches": 1, "latestIndex": int(swing["index"])})
        else:
            target["prices"].append(price)
            target["touches"] += 1
            target["latestIndex"] = max(int(target["latestIndex"]), int(swing["index"]))
            target["center"] = sum(target["prices"]) / len(target["prices"])

    recent_cutoff = max(0, len(clean) - 30)
    qualified = [cluster for cluster in clusters if int(cluster["touches"]) >= 2 or int(cluster["latestIndex"]) >= recent_cutoff]
    if not qualified:
        return []
    qualified.sort(key=lambda row: _number(row["center"]))
    latest = _number(clean[-1].get("close"))
    requested_anchor = _number(cycle_start_equity) or latest
    anchor_index = min(range(len(qualified)), key=lambda index: abs(_number(qualified[index]["center"]) - requested_anchor))
    half_width = volatility * 0.22

    output = []
    for index, cluster in enumerate(qualified):
        relative = index - anchor_index
        if relative < -3 or relative > 3:
            continue
        center = _number(cluster["center"])
        output.append({
            "index": relative,
            "label": "Zone 0" if relative == 0 else f"Zone {relative:+d}",
            "center": center,
            "lower": max(0.0, center - half_width),
            "upper": center + half_width,
            "touches": int(cluster["touches"]),
            "atr": volatility,
            "source": "confirmed-swings+sr-cluster+atr",
        })
    return output


def active_zone(zones: list[dict[str, Any]], price: float) -> int | None:
    value = _number(price)
    if value <= 0 or not zones:
        return None
    inside = [zone for zone in zones if _number(zone.get("lower")) <= value <= _number(zone.get("upper"))]
    if inside:
        return int(inside[0]["index"])
    nearest = min(zones, key=lambda zone: abs(_number(zone.get("center")) - value))
    return int(nearest["index"])


def zone_shadow_backtest(candles: list[dict[str, Any]], cycle_start_equity: float = 0.0) -> dict[str, Any]:
    """Replay the display-only zone detector prefix by prefix; never emits orders."""
    previous: int | None = None
    transitions = 0
    evaluated = 0
    for end in range(7, len(candles) + 1):
        prefix = candles[:end]
        zones = derive_equity_zones(prefix, cycle_start_equity)
        current = active_zone(zones, _number(prefix[-1].get("close")))
        if current is None:
            continue
        evaluated += 1
        if previous is not None and current != previous:
            transitions += 1
        previous = current
    return {
        "mode": "shadow",
        "readOnly": True,
        "ordersSent": 0,
        "evaluatedCandles": evaluated,
        "zoneTransitions": transitions,
        "usesFutureCandles": False,
    }
