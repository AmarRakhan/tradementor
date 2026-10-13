"""Extreme Spike admission mathematics (read-only, no orders or API transport).

Uses the previous 20 completed candle closes. A spike is the current
candle's wick reaching the configured number of standard deviations.
The open/in-progress candle must never be treated as complete here.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Any

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
    if candle_close_ms <= 0 or candle_close_ms > now_ms or now_ms - candle_close_ms > max_staleness_ms:
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
