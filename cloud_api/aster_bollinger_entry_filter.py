from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math
import time

TIMEFRAME = "15m"
PERIOD = 20
STDDEV_MULTIPLIER = 2.0
MAX_KLINE_AGE_MS = 20 * 60 * 1000
CACHE_TTL_SECONDS = 5.0
PREORDER_MARKET_TTL_SECONDS = 1


@dataclass(frozen=True)
class BollingerEntrySnapshot:
    symbol: str
    side: str
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


_BAND_CACHE: dict[str, tuple[float, float, float, int]] = {}


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
    """Use AsterV3Client's guarded public transport for a near-submit read.

    AsterV3Client intentionally caches normal dashboard/scanner market reads.
    The primary-entry pre-submit guard needs a much tighter freshness bound, so
    it uses a separate canonical query-key with a one-second TTL while retaining
    the client's shared REST rate-limit guard and response validation.
    """
    reader = getattr(client, "_public_get", None)
    if not callable(reader):
        raise AttributeError("guarded public market reader unavailable")
    return reader(
        path,
        ttl_seconds=PREORDER_MARKET_TTL_SECONDS,
        invalid_message=invalid_message,
    )


def _read_klines(client: Any, symbol: str, *, force_refresh: bool) -> list[Any]:
    symbol = str(symbol).upper()
    if force_refresh and callable(getattr(client, "_public_get", None)):
        # Query parameter order deliberately differs from AsterV3Client.klines,
        # giving this pre-order path its own <=1s cache instead of inheriting the
        # normal 15s scanner/dashboard cache entry.
        payload = _guarded_public_read(
            client,
            f"/fapi/v1/klines?interval={TIMEFRAME}&symbol={symbol}&limit=25",
            invalid_message="Aster 15m-candles konden niet betrouwbaar worden gelezen",
        )
        if not isinstance(payload, list):
            raise ValueError("invalid 15m kline payload")
        return [row for row in payload if isinstance(row, (list, tuple, dict))]
    rows = client.klines(symbol=symbol, interval=TIMEFRAME, limit=25)
    if not isinstance(rows, list):
        raise ValueError("invalid 15m kline payload")
    return rows


def _current_bands(client: Any, symbol: str, *, now_ms: int, force_refresh: bool) -> tuple[float, float, int]:
    symbol = str(symbol).upper()
    cached = _BAND_CACHE.get(symbol)
    if not force_refresh and cached and time.monotonic() - cached[0] <= CACHE_TTL_SECONDS:
        return cached[1], cached[2], cached[3]
    rows = _read_klines(client, symbol, force_refresh=force_refresh)
    if len(rows) < PERIOD:
        raise ValueError("insufficient 15m klines")
    window = rows[-PERIOD:]
    closes = [_row_close(row) for row in window]
    latest_open_ms = _row_open_ms(window[-1])
    if latest_open_ms <= 0 or latest_open_ms > now_ms + 60_000 or now_ms - latest_open_ms > MAX_KLINE_AGE_MS:
        raise ValueError("stale 15m kline")
    mean = sum(closes) / PERIOD
    variance = sum((value - mean) ** 2 for value in closes) / PERIOD
    sigma = math.sqrt(max(0.0, variance))
    lower = mean - STDDEV_MULTIPLIER * sigma
    upper = mean + STDDEV_MULTIPLIER * sigma
    if lower <= 0 or upper <= 0 or lower > upper:
        raise ValueError("invalid 15m Bollinger bands")
    _BAND_CACHE[symbol] = (time.monotonic(), lower, upper, latest_open_ms)
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
            payload = next(
                (row for row in rows if isinstance(row, dict) and str(row.get("symbol", "")).upper() == symbol),
                None,
            )
    if not isinstance(payload, dict):
        raise ValueError("invalid live ticker")
    price = _finite(payload.get("price"))
    if price <= 0:
        raise ValueError("invalid live price")
    return price


def _event(side: str, passed: bool) -> str:
    return f"BB_ENTRY_FILTER_{side}_{'PASS' if passed else 'REJECT'}"


def _log(*, symbol: str, side: str, live_price: float | None, lower: float | None, upper: float | None,
         checked_at_ms: int, stage: str, passed: bool, reason: str) -> None:
    print(
        f"{_event(side, passed)} symbol={symbol} side={side} livePrice={live_price if live_price is not None else 'NA'} "
        f"lowerBand={lower if lower is not None else 'NA'} upperBand={upper if upper is not None else 'NA'} "
        f"timeframe={TIMEFRAME} timestampMs={checked_at_ms} enabled=true stage={stage} result={'PASS' if passed else 'REJECT'} reason={reason}",
        flush=True,
    )


def require_bollinger_entry(client: Any, *, symbol: str, side: str, enabled: bool,
                            live_price: float | None = None, force_refresh: bool = False,
                            stage: str = "candidate", now_ms: int | None = None) -> BollingerEntrySnapshot | None:
    """Fail closed for one NEW primary entry; disabled mode is a true no-op.

    15m klines define the bands. The decision uses a live/current price and does
    not wait for a candle close. Strict inequalities intentionally reject exact
    equality with the relevant band.
    """
    if not enabled:
        return None
    symbol = str(symbol).upper()
    side = str(side).upper()
    if side not in {"LONG", "SHORT"}:
        raise BollingerEntryRejected("BB_INVALID_SIDE", symbol, side)
    checked_at_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    try:
        lower, upper, latest_open_ms = _current_bands(client, symbol, now_ms=checked_at_ms, force_refresh=force_refresh)
        price = _latest_price(client, symbol, force_refresh=force_refresh) if live_price is None else _finite(live_price)
        if price <= 0:
            raise ValueError("invalid live price")
    except Exception as exc:
        _log(symbol=symbol, side=side, live_price=None, lower=None, upper=None, checked_at_ms=checked_at_ms,
             stage=stage, passed=False, reason="BB_DATA_UNAVAILABLE_OR_STALE")
        raise BollingerEntryRejected("BB_DATA_UNAVAILABLE_OR_STALE", symbol, side) from exc
    snapshot = BollingerEntrySnapshot(symbol, side, price, lower, upper, latest_open_ms, checked_at_ms)
    passed = price < lower if side == "LONG" else price > upper
    reason = "PRICE_BELOW_LOWER_BAND" if side == "LONG" and passed else \
             "PRICE_ABOVE_UPPER_BAND" if side == "SHORT" and passed else \
             "PRICE_NOT_BELOW_LOWER_BAND" if side == "LONG" else "PRICE_NOT_ABOVE_UPPER_BAND"
    _log(symbol=symbol, side=side, live_price=price, lower=lower, upper=upper, checked_at_ms=checked_at_ms,
         stage=stage, passed=passed, reason=reason)
    if not passed:
        raise BollingerEntryRejected(reason, symbol, side, snapshot)
    return snapshot
