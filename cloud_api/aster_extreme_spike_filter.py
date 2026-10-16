"""Extreme Spike admission mathematics (read-only, no orders or API transport).

Uses the previous 20 completed candle closes. The current in-progress candle's latest quoted close is checked against the
previous 20 completed closes; never use a historical wick as live evidence.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Any
import hashlib

LEVELS = {"2-3": (2.0,3.0), "3-4":(3.0,4.0), "4-5":(4.0,5.0),
          "5-6":(5.0,6.0), "6-7":(6.0,7.0), "7+":(7.0,None)}
TIMEFRAMES = ("1m","5m","15m","1h","4h","1d")
MODES = ("OFF","BOLLINGER","EXTREME_SPIKE")

class SpikeFilterRejected(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)

@dataclass(frozen=True)
class SpikeSnapshot:
    side: str
    level: str
    timeframe: str
    wick: float
    band: float
    score: float
    overshoot_pct: float
    candle_close_ms: int

def normalize_mode(raw: Any, legacy_bb_enabled: bool) -> str:
    if raw is None:
        return "BOLLINGER" if legacy_bb_enabled else "OFF"
    mode = str(raw).strip().upper()
    if mode not in MODES:
        raise ValueError("INVALID_ENTRY_FILTER_MODE")
    return mode

def validate_settings(*, mode: str, level: str, long_tf: str, short_tf: str, legacy_bb_enabled: bool) -> None:
    if mode not in MODES:
        raise ValueError("INVALID_ENTRY_FILTER_MODE")
    if level not in LEVELS:
        raise ValueError("INVALID_SPIKE_LEVEL")
    if long_tf not in TIMEFRAMES or short_tf not in TIMEFRAMES:
        raise ValueError("INVALID_SPIKE_TIMEFRAME")
    if mode == "EXTREME_SPIKE" and legacy_bb_enabled:
        raise ValueError("FILTERS_MUTUALLY_EXCLUSIVE")
    if mode == "BOLLINGER" and not legacy_bb_enabled:
        raise ValueError("BOLLINGER_FLAG_NOT_ENABLED")

def evaluate_spike(*, side: str, level: str, timeframe: str,
                   previous_closes: list[float], candle_high: float,
                   candle_low: float, candle_close_ms: int, now_ms: int,
                   max_staleness_ms: int) -> SpikeSnapshot:
    if side not in ("LONG","SHORT") or level not in LEVELS or timeframe not in TIMEFRAMES:
        raise SpikeFilterRejected("SPIKE_INVALID_SETTINGS")
    if len(previous_closes) != 20:
        raise SpikeFilterRejected("SPIKE_INSUFFICIENT_CANDLES")
    if candle_close_ms <= 0 or now_ms - candle_close_ms > max_staleness_ms or candle_close_ms - now_ms > max_staleness_ms:
        raise SpikeFilterRejected("SPIKE_STALE_OR_UNCLOSED")
    if not all(math.isfinite(v) and v > 0 for v in previous_closes):
        raise SpikeFilterRejected("SPIKE_BAD_CANDLES")
    if not (math.isfinite(candle_high) and math.isfinite(candle_low) and 0 < candle_low <= candle_high):
        raise SpikeFilterRejected("SPIKE_BAD_WICK")
    mean = sum(previous_closes)/20
    deviation = math.sqrt(sum((v-mean)**2 for v in previous_closes)/20)
    if not deviation > 0:
        raise SpikeFilterRejected("SPIKE_ZERO_VOLATILITY")
    wick = candle_low if side == "LONG" else candle_high
    score = (mean-wick)/deviation if side == "LONG" else (wick-mean)/deviation
    minimum,maximum = LEVELS[level]
    if score < minimum or (maximum is not None and score >= maximum):
        raise SpikeFilterRejected("SPIKE_OUTSIDE_SELECTED_RANGE")
    band = mean + (-2 if side == "LONG" else 2)*deviation
    if band <= 0:
        raise SpikeFilterRejected("SPIKE_INVALID_BAND")
    overshoot = (band-wick)/band if side == "LONG" else (wick-band)/band
    return SpikeSnapshot(side,level,timeframe,wick,band,score,100*overshoot,candle_close_ms)

def require_extreme_spike_entry(client: Any, *, symbol: str, side: str, level: str,
                                timeframe: str, now_ms: int) -> SpikeSnapshot:
    """Fail-closed read-only adapter; current in-progress candle price is checked.

    The candidate gate and final pre-order gate must both call this same
    function. Transport uses the existing client, not another scanner.
    """
    if timeframe not in TIMEFRAMES:
        raise SpikeFilterRejected("SPIKE_INVALID_TIMEFRAME")
    try:
        rows = client.klines(symbol=str(symbol).upper(), interval=timeframe, limit=23)
        if not isinstance(rows, list) or len(rows) < 22:
            raise SpikeFilterRejected("SPIKE_INSUFFICIENT_CANDLES")
        def close_ms(row: Any) -> int:
            return int(row[6] if isinstance(row, (list, tuple)) else row["closeTime"])
        def value(row: Any, position: int, key: str) -> float:
            return float(row[position] if isinstance(row, (list, tuple)) else row[key])
        # Reference is fixed to 20 completed candles. Evaluate the latest
        # in-progress candle's CURRENT traded/last price, not its historical wick:
        # a wick could have hit the level and already reversed before this scan.
        completed = [row for row in rows if close_ms(row) < now_ms]
        live = [row for row in rows if close_ms(row) >= now_ms]
        if len(completed) < 20 or not live:
            raise SpikeFilterRejected("SPIKE_INSUFFICIENT_LIVE_CANDLES")
        signal = live[-1]
        previous = completed[-20:]
        current_price = value(signal, 4, "close")
        interval_ms={"1m":60000,"5m":300000,"15m":900000,"1h":3600000,"4h":14400000,"1d":86400000}[timeframe]
        if close_ms(signal) - now_ms > interval_ms:
            raise SpikeFilterRejected("SPIKE_INVALID_LIVE_CANDLE")
        return evaluate_spike(side=side,level=level,timeframe=timeframe,
            previous_closes=[value(row,4,"close") for row in previous],
            candle_high=current_price,candle_low=current_price,
            candle_close_ms=close_ms(signal),now_ms=now_ms,
            max_staleness_ms=interval_ms+300000)
    except SpikeFilterRejected:
        raise
    except Exception as exc:
        raise SpikeFilterRejected("SPIKE_DATA_UNAVAILABLE") from exc

def spike_event_key(*, symbol: str, side: str, timeframe: str, candle_close_ms: int) -> str:
    """Deterministic event identity, independent of scheduler tick or TP cycle.

    This is not sufficient by itself for exactly-once execution. The order
    executor must durably claim/check this key atomically before submission.
    """
    if side not in ("LONG","SHORT") or timeframe not in TIMEFRAMES or candle_close_ms <= 0:
        raise SpikeFilterRejected("SPIKE_INVALID_EVENT_IDENTITY")
    raw=f"{symbol.upper()}|{side}|{timeframe}|{candle_close_ms}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

def claim_spike_entry_once(account_ref: Any, *, event_key: str, symbol: str,
                           side: str, timeframe: str, now_ms: int) -> None:
    """Atomically reserve a spike event within the existing account document tree.

    Firestore document.create is create-if-absent. Never automatically release
    an uncertain claim: missing an opportunity is safer than duplicate entry.
    The canonical order executor still performs the only order submission.
    """
    if not event_key or len(event_key) != 32:
        raise SpikeFilterRejected("SPIKE_INVALID_EVENT_IDENTITY")
    try:
        account_ref.collection("spikeEntryClaims").document(event_key).create({
            "eventId": event_key,
            "symbol": str(symbol).upper(),
            "side": side,
            "timeframe": timeframe,
            "claimedAtMs": int(now_ms),
            "status": "RESERVED",
        })
    except Exception as exc:
        # Includes ALREADY_EXISTS, transport uncertainty, and permission issues.
        # Never retry the claim or place an order when reservation is unclear.
        raise SpikeFilterRejected("SPIKE_EVENT_CLAIM_FAILED_OR_REPLAY") from exc
