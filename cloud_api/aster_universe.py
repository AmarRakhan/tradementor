"""Shared fail-closed Aster USDT perpetual trading universe.

The module is deliberately pure: callers fetch Aster ``exchangeInfo`` and
24-hour ticker rows, then pass both payloads here.  It never submits orders and
never consults an external ranking provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Callable, Iterable


UNIVERSE_SOURCE = "aster"
QUOTE_ASSET = "USDT"
MARKET_TYPE = "perpetual"
RANKING_METHOD = "aster_24h_quote_volume_usdt_desc_then_symbol"
DEFAULT_TTL_SECONDS = 300

# Conservative entry-only defaults.  They are intentionally centralized and
# apply before Top-N.  USD 1m/day is about USD 11.57/second: comfortably above
# a Strategy-2 base order while still retaining a broad perpetual universe.
# A 50% daily move or a 100% high/low range is treated as disorderly.  Spread
# is capped at 50 bps only when Aster provides a synchronized bid and ask;
# Aster's current bulk V3 24h response does not, so absence is reported rather
# than fabricated. Existing-position management never consumes this policy.
MIN_QUOTE_VOLUME_24H_USDT = 1_000_000.0
MAX_SPREAD_RATIO = 0.005
MAX_ABS_PRICE_CHANGE_24H_PCT = 50.0
MAX_HIGH_LOW_RANGE_24H_RATIO = 1.0
MAX_TICKER_AGE_SECONDS = 360


def normalize_top_n(value: Any) -> int:
    """Accept every positive integer without rounding to a preset option."""
    if isinstance(value, bool):
        raise ValueError("Aster Top-N moet een positief geheel getal zijn")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Aster Top-N moet een positief geheel getal zijn") from exc
    if not math.isfinite(parsed) or parsed < 1 or not parsed.is_integer():
        raise ValueError("Aster Top-N moet een positief geheel getal zijn")
    return int(parsed)


def _positive(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) and parsed > 0 else 0.0


def _filter_map(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("filterType", "")).upper(): item
        for item in row.get("filters", ())
        if isinstance(item, dict)
    }


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _minimum_executable_notional(row: dict[str, Any], price: float) -> float | None:
    """Compute the smallest market order from exchangeInfo without rounding risk."""
    filters = _filter_map(row)
    lot = filters.get("MARKET_LOT_SIZE", filters.get("LOT_SIZE", {}))
    step = _positive(lot.get("stepSize"))
    minimum_quantity = _positive(lot.get("minQty"))
    notional = filters.get("MIN_NOTIONAL", filters.get("NOTIONAL", {}))
    minimum_notional = _positive(notional.get("notional", notional.get("minNotional")))
    if not step or not price or not minimum_notional:
        return None
    required = max(minimum_quantity, minimum_notional / price)
    rounded_quantity = math.ceil((required / step) - 1e-12) * step
    return rounded_quantity * price


def eligible_contract(row: dict[str, Any]) -> bool:
    """Return whether one exchangeInfo row is an orderable USDT perpetual."""
    if str(row.get("status", "")).upper() != "TRADING":
        return False
    contract_type = str(row.get("contractType", row.get("type", ""))).upper()
    if "PERPETUAL" not in contract_type:
        return False
    quote = str(row.get("quoteAsset", "")).upper()
    settlement = str(row.get("marginAsset", row.get("settleAsset", quote))).upper()
    if quote != QUOTE_ASSET or settlement != QUOTE_ASSET:
        return False
    filters = _filter_map(row)
    price = filters.get("PRICE_FILTER", {})
    lot = filters.get("LOT_SIZE", {})
    market_lot = filters.get("MARKET_LOT_SIZE", lot)
    notional = filters.get("MIN_NOTIONAL", filters.get("NOTIONAL", {}))
    return all((
        _positive(price.get("tickSize")),
        _positive(lot.get("stepSize")),
        _positive(market_lot.get("stepSize")),
        _positive(notional.get("notional", notional.get("minNotional"))),
    ))


@dataclass(frozen=True)
class RankedAsterMarket:
    symbol: str
    quote_volume_24h: float
    trade_count_24h: int
    spread_ratio: float | None
    price_change_24h_pct: float
    high_low_range_24h_ratio: float

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quoteVolume24h": self.quote_volume_24h,
            "tradeCount24h": self.trade_count_24h,
            "spreadRatio": self.spread_ratio,
            "priceChange24hPct": self.price_change_24h_pct,
            "highLowRange24hRatio": self.high_low_range_24h_ratio,
        }


@dataclass(frozen=True)
class AsterUniverseSnapshot:
    requested_top_n: int
    eligible_markets: tuple[RankedAsterMarket, ...]
    fetched_at: datetime
    expires_at: datetime
    stale: bool = False
    entry_block_reason: str = ""
    discovered_market_count: int = 0
    rejection_counts: tuple[tuple[str, int], ...] = ()
    rejection_samples: tuple[tuple[str, str], ...] = ()
    unavailable_filters: tuple[str, ...] = ()

    @property
    def selected(self) -> tuple[RankedAsterMarket, ...]:
        return self.eligible_markets[: self.requested_top_n]

    @property
    def entry_blocked(self) -> bool:
        return self.stale or not self.selected or bool(self.entry_block_reason)

    def public_dict(self) -> dict[str, Any]:
        return {
            "universeSource": UNIVERSE_SOURCE,
            "quoteAsset": QUOTE_ASSET,
            "marketType": MARKET_TYPE,
            "rankingMethod": RANKING_METHOD,
            "requestedTopN": self.requested_top_n,
            "eligibleMarketCount": len(self.eligible_markets),
            "selectedMarketCount": len(self.selected),
            "selectedSymbols": [item.symbol for item in self.selected],
            "fetchedAt": self.fetched_at.isoformat(),
            "expiresAt": self.expires_at.isoformat(),
            "stale": self.stale,
            "entryBlocked": self.entry_blocked,
            "entryBlockReason": self.entry_block_reason or (
                "Actuele Aster USDT-universumdata ontbreekt; nieuwe instappen zijn geblokkeerd"
                if self.entry_blocked else ""
            ),
            "discoveredMarketCount": self.discovered_market_count,
            "rejectionCounts": dict(self.rejection_counts),
            "rejectionSamples": dict(self.rejection_samples),
            "unavailableFilters": list(self.unavailable_filters),
            "thresholds": {
                "minimumQuoteVolume24hUsdt": MIN_QUOTE_VOLUME_24H_USDT,
                "maximumSpreadRatio": MAX_SPREAD_RATIO,
                "maximumAbsolutePriceChange24hPct": MAX_ABS_PRICE_CHANGE_24H_PCT,
                "maximumHighLowRange24hRatio": MAX_HIGH_LOW_RANGE_24H_RATIO,
                "maximumTickerAgeSeconds": MAX_TICKER_AGE_SECONDS,
            },
        }


def build_snapshot(
    exchange_info: dict[str, Any],
    tickers_24h: Iterable[dict[str, Any]],
    requested_top_n: Any,
    *,
    fetched_at: datetime | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    base_notional: float | None = None,
) -> AsterUniverseSnapshot:
    requested = normalize_top_n(requested_top_n)
    now = (fetched_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    all_rows = [row for row in exchange_info.get("symbols", ()) if isinstance(row, dict)]
    contracts = {
        str(row.get("symbol", "")).upper(): row
        for row in exchange_info.get("symbols", ())
        if isinstance(row, dict) and eligible_contract(row) and str(row.get("symbol", "")).strip()
    }
    markets: list[RankedAsterMarket] = []
    seen: set[str] = set()
    rejection_counts: dict[str, int] = {}
    rejection_samples: dict[str, str] = {}
    ticker_by_symbol = {str(row.get("symbol", "")).upper(): row for row in tickers_24h if isinstance(row, dict)}

    def reject(symbol: str, reason: str) -> None:
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        rejection_samples.setdefault(symbol, reason)

    for row in all_rows:
        symbol = str(row.get("symbol", "")).upper()
        if symbol and symbol not in contracts:
            reject(symbol, "geen actieve verhandelbare Aster USDT-perpetual")
    for ticker in ticker_by_symbol.values():
        if not isinstance(ticker, dict):
            continue
        symbol = str(ticker.get("symbol", "")).upper()
        if symbol in seen or symbol not in contracts:
            continue
        last = _positive(ticker.get("lastPrice", ticker.get("price")))
        volume = _positive(ticker.get("quoteVolume", ticker.get("turnover")))
        # Aster's real /fapi/v3/ticker/24hr payload does not expose bidPrice
        # or askPrice.  Treat spread as optional ranking evidence instead of
        # rejecting every otherwise complete, active perpetual contract.
        bid = _positive(ticker.get("bidPrice"))
        ask = _positive(ticker.get("askPrice"))
        try:
            trades = max(0, int(ticker.get("count", ticker.get("tradeCount", 0))))
        except (TypeError, ValueError):
            trades = 0
        if not last or not volume:
            reject(symbol, "ontbrekende of ongeldige prijs/quotevolume")
            continue
        spread = (ask - bid) / last if bid and ask and ask >= bid else None
        change = _finite(ticker.get("priceChangePercent"))
        high, low = _positive(ticker.get("highPrice")), _positive(ticker.get("lowPrice"))
        if change is None or not high or not low or high < low:
            reject(symbol, "onvolledige Aster 24-uurs koersdata")
            continue
        if volume < MIN_QUOTE_VOLUME_24H_USDT:
            reject(symbol, "onvoldoende Aster 24-uurs quotevolume")
            continue
        if spread is not None and spread > MAX_SPREAD_RATIO:
            reject(symbol, "bid/ask-spread boven veiligheidsgrens")
            continue
        if abs(change) > MAX_ABS_PRICE_CHANGE_24H_PCT:
            reject(symbol, "abnormale 24-uurskoersbeweging")
            continue
        range_ratio = (high - low) / low
        if range_ratio > MAX_HIGH_LOW_RANGE_24H_RATIO:
            reject(symbol, "extreme 24-uurs high/low-volatiliteit")
            continue
        if base_notional is not None:
            minimum = _minimum_executable_notional(contracts[symbol], last)
            if minimum is None or minimum > float(base_notional) + 1e-9:
                reject(symbol, "basisorder voldoet niet aan Aster minimum/precision")
                continue
        markets.append(RankedAsterMarket(symbol, volume, trades, spread, change, range_ratio))
        seen.add(symbol)
    for symbol in contracts:
        if symbol not in ticker_by_symbol:
            reject(symbol, "actuele Aster ticker ontbreekt")
    markets.sort(key=lambda item: (
        -item.quote_volume_24h,
        item.symbol,
    ))
    reason = "" if markets else "Aster retourneerde geen complete actieve USDT-perpetualmarkten"
    return AsterUniverseSnapshot(
        requested,
        tuple(markets),
        now,
        now + timedelta(seconds=max(1, int(ttl_seconds))),
        False,
        reason,
        len(contracts),
        tuple(sorted(rejection_counts.items())),
        tuple(list(sorted(rejection_samples.items()))[:100]),
        ("listingdatum", "kortetermijnvolatiliteit", "bulk bid/ask-spread"),
    )


def stale_snapshot(snapshot: AsterUniverseSnapshot, *, now: datetime | None = None, reason: str) -> AsterUniverseSnapshot:
    checked = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return AsterUniverseSnapshot(
        snapshot.requested_top_n,
        snapshot.eligible_markets,
        snapshot.fetched_at,
        snapshot.expires_at,
        checked >= snapshot.expires_at,
        reason,
        snapshot.discovered_market_count,
        snapshot.rejection_counts,
        snapshot.rejection_samples,
        snapshot.unavailable_filters,
    )


def server_snapshot_contract(stored: Any, requested_top_n: Any,
                             refresh: Callable[[int], AsterUniverseSnapshot], *,
                             now: datetime | None = None) -> tuple[dict[str, Any], bool]:
    """Use only a complete fresh Aster contract, otherwise refresh it.

    ``refresh`` is injected so contract tests stay pure and production callers
    can use the public-data-only Aster client.  The boolean indicates whether
    the caller should persist the returned server evidence.
    """
    requested = normalize_top_n(requested_top_n)
    checked = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    value = dict(stored) if isinstance(stored, dict) else {}
    try:
        expires = datetime.fromisoformat(str(value.get("expiresAt", "")).replace("Z", "+00:00")).astimezone(timezone.utc)
        symbols = value.get("selectedSymbols") if isinstance(value.get("selectedSymbols"), list) else []
        valid = all((
            value.get("universeSource") == UNIVERSE_SOURCE,
            value.get("quoteAsset") == QUOTE_ASSET,
            value.get("marketType") == MARKET_TYPE,
            int(value.get("requestedTopN", 0)) == requested,
            int(value.get("selectedMarketCount", -1)) == len(symbols),
            len(symbols) > 0,
            checked < expires,
            value.get("stale") is False,
            value.get("entryBlocked") is False,
        ))
    except (TypeError, ValueError):
        valid = False
    if valid:
        return value, False
    return refresh(requested).public_dict(), True
