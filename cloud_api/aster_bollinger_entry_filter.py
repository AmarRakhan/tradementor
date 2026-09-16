from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math
import time

DEFAULT_TIMEFRAME = "15m"
SUPPORTED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}
PERIOD = 20
STDDEV_MULTIPLIER = 2.0
CACHE_TTL_SECONDS = 5.0
PREORDER_MARKET_TTL_SECONDS = 1


def normalize_bollinger_timeframe(value: Any) -> str:
    raw = str(value or DEFAULT_TIMEFRAME).strip().lower()
    aliases = {"1u": "1h", "4u": "4h"}
    timeframe = aliases.get(raw, raw)
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Ongeldig Bollinger-timeframe: {value}")
    return timeframe


def _maximum_kline_age_ms(timeframe: str) -> int:
    # The latest Aster row is the current, still-forming candle. Allow one full
    # selected interval plus five minutes of transport/scheduling slack. This
    # preserves the previous 20-minute freshness limit for the 15m default.
    return TIMEFRAME_MS[timeframe] + 5 * 60_000


@dataclass(frozen=True)
class BollingerEntrySnapshot:
    symbol: str
    side: str
    timeframe: str
    live_price: float
    lower_band: float
    upper_band: float
    latest_kline_open_ms: int
    checked_at_ms: int


class BollingerEntryRejected(ValueError):
    def __init__(self, reason_code: str, symbol: str, side: str, snapshot: BollingerEntrySnapshot | None = None):
        self.reason_code = reason_code
        self.symbol = str(symbol).upper()
        self.side = str(side).upper()
        self.snapshot = snapshot
        super().__init__(f"{self.symbol} {self.side}: {reason_code}")


# Cache is isolated by BOTH symbol and timeframe so changing 15m -> 1m can
# never reuse bands from the prior interval.
_BAND_CACHE: dict[tuple[str, str], tuple[float, float, float, int]] = {}


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite market value")
    return number


def _row_close(row: Any) -> float:
    if isinstance(row, (list, tuple)) and len(row) > 4:
        return _finite(row[4])
    if isinstance(row, dict):
        return _finite(row.get("close", row.get("c")))
    raise ValueError("invalid kline row")


def _row_open_ms(row: Any) -> int:
    if isinstance(row, (list, tuple)) and row:
        return int(float(row[0]))
    if isinstance(row, dict):
        return int(float(row.get("openTime", row.get("open_time", row.get("t", 0)))))
    return 0


def _guarded_public_read(client: Any, path: str, *, invalid_message: str) -> Any:
    """Use AsterV3Client's guarded public transport for a near-submit read."""
    reader = getattr(client, "_public_get", None)
    if not callable(reader):
        raise AttributeError("guarded public market reader unavailable")
    return reader(path, ttl_seconds=PREORDER_MARKET_TTL_SECONDS, invalid_message=invalid_message)


def _read_klines(client: Any, symbol: str, timeframe: str, *, force_refresh: bool) -> list[Any]:
    symbol = str(symbol).upper()
    timeframe = normalize_bollinger_timeframe(timeframe)
    if force_refresh and callable(getattr(client, "_public_get", None)):
        # Query order deliberately remains separate from the normal scanner key,
        # keeping the pre-order validation on its own <=1 second cache.
        payload = _guarded_public_read(
            client,
            f"/fapi/v1/klines?interval={timeframe}&symbol={symbol}&limit=25",
            invalid_message=f"Aster {timeframe}-candles konden niet betrouwbaar worden gelezen",
        )
        if not isinstance(payload, list):
            raise ValueError(f"invalid {timeframe} kline payload")
        return [row for row in payload if isinstance(row, (list, tuple, dict))]
    rows = client.klines(symbol=symbol, interval=timeframe, limit=25)
    if not isinstance(rows, list):
        raise ValueError(f"invalid {timeframe} kline payload")
    return rows


def _current_bands(client: Any, symbol: str, timeframe: str, *, now_ms: int, force_refresh: bool) -> tuple[float, float, int]:
    symbol = str(symbol).upper()
    timeframe = normalize_bollinger_timeframe(timeframe)
    cache_key = (symbol, timeframe)
    cached = _BAND_CACHE.get(cache_key)
    if not force_refresh and cached and time.monotonic() - cached[0] <= CACHE_TTL_SECONDS:
        return cached[1], cached[2], cached[3]
    rows = _read_klines(client, symbol, timeframe, force_refresh=force_refresh)
    if len(rows) < PERIOD:
        raise ValueError(f"insufficient {timeframe} klines")
    window = rows[-PERIOD:]
    closes = [_row_close(row) for row in window]
    latest_open_ms = _row_open_ms(window[-1])
    maximum_age_ms = _maximum_kline_age_ms(timeframe)
    if latest_open_ms <= 0 or latest_open_ms > now_ms + 60_000 or now_ms - latest_open_ms > maximum_age_ms:
        raise ValueError(f"stale {timeframe} kline")
    mean = sum(closes) / PERIOD
    variance = sum((value - mean) ** 2 for value in closes) / PERIOD
    sigma = math.sqrt(max(0.0, variance))
    lower = mean - STDDEV_MULTIPLIER * sigma
    upper = mean + STDDEV_MULTIPLIER * sigma
    if lower <= 0 or upper <= 0 or lower > upper:
        raise ValueError(f"invalid {timeframe} Bollinger bands")
    _BAND_CACHE[cache_key] = (time.monotonic(), lower, upper, latest_open_ms)
    return lower, upper, latest_open_ms


def _latest_price(client: Any, symbol: str, *, force_refresh: bool) -> float:
    symbol = str(symbol).upper()
    payload: Any = None
    if force_refresh and callable(getattr(client, "_public_get", None)):
        payload = _guarded_public_read(
            client,
            f"/fapi/v3/ticker/price?symbol={symbol}",
            invalid_message="Aster-prijs kon niet betrouwbaar worden gelezen",
        )
    else:
        single = getattr(client, "ticker_price", None)
        if callable(single):
            payload = single(symbol=symbol)
        else:
            rows = client.ticker_prices()
            payload = next((row for row in rows if isinstance(row, dict) and str(row.get("symbol", "")).upper() == symbol), None)
    if not isinstance(payload, dict):
        raise ValueError("invalid live ticker")
    price = _finite(payload.get("price"))
    if price <= 0:
        raise ValueError("invalid live price")
    return price


def _event(side: str, passed: bool) -> str:
    return f"BB_ENTRY_FILTER_{side}_{'PASS' if passed else 'REJECT'}"


def _log(*, symbol: str, side: str, timeframe: str, live_price: float | None, lower: float | None, upper: float | None,
         checked_at_ms: int, stage: str, passed: bool, reason: str) -> None:
    print(
        f"{_event(side, passed)} symbol={symbol} side={side} livePrice={live_price if live_price is not None else 'NA'} "
        f"lowerBand={lower if lower is not None else 'NA'} upperBand={upper if upper is not None else 'NA'} "
        f"timeframe={timeframe} timestampMs={checked_at_ms} enabled=true stage={stage} result={'PASS' if passed else 'REJECT'} reason={reason}",
        flush=True,
    )


def require_bollinger_entry(client: Any, *, symbol: str, side: str, enabled: bool,
                            timeframe: str = DEFAULT_TIMEFRAME,
                            live_price: float | None = None, force_refresh: bool = False,
                            stage: str = "candidate", now_ms: int | None = None) -> BollingerEntrySnapshot | None:
    """Fail closed for one NEW primary entry; disabled mode is a true no-op.

    The selected timeframe's klines define the existing Bollinger formula. The
    decision uses a live/current price and does not add a candle-close rule.
    Strict inequalities intentionally reject equality with the relevant band.
    """
    if not enabled:
        return None
    symbol = str(symbol).upper()
    side = str(side).upper()
    if side not in {"LONG", "SHORT"}:
        raise BollingerEntryRejected("BB_INVALID_SIDE", symbol, side)
    checked_at_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    try:
        selected_timeframe = normalize_bollinger_timeframe(timeframe)
        lower, upper, latest_open_ms = _current_bands(client, symbol, selected_timeframe, now_ms=checked_at_ms, force_refresh=force_refresh)
        price = _latest_price(client, symbol, force_refresh=force_refresh) if live_price is None else _finite(live_price)
        if price <= 0:
            raise ValueError("invalid live price")
    except Exception as exc:
        log_timeframe = str(timeframe or DEFAULT_TIMEFRAME)
        _log(symbol=symbol, side=side, timeframe=log_timeframe, live_price=None, lower=None, upper=None, checked_at_ms=checked_at_ms,
             stage=stage, passed=False, reason="BB_DATA_UNAVAILABLE_OR_STALE")
        raise BollingerEntryRejected("BB_DATA_UNAVAILABLE_OR_STALE", symbol, side) from exc
    snapshot = BollingerEntrySnapshot(symbol, side, selected_timeframe, price, lower, upper, latest_open_ms, checked_at_ms)
    passed = price < lower if side == "LONG" else price > upper
    reason = "PRICE_BELOW_LOWER_BAND" if side == "LONG" and passed else              "PRICE_ABOVE_UPPER_BAND" if side == "SHORT" and passed else              "PRICE_NOT_BELOW_LOWER_BAND" if side == "LONG" else "PRICE_NOT_ABOVE_UPPER_BAND"
    _log(symbol=symbol, side=side, timeframe=selected_timeframe, live_price=price, lower=lower, upper=upper, checked_at_ms=checked_at_ms,
         stage=stage, passed=passed, reason=reason)
    if not passed:
        raise BollingerEntryRejected(reason, symbol, side, snapshot)
    return snapshot
