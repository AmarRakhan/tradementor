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
RANKING_METHOD = "aster_24h_quote_volume_desc_then_trade_count_desc_then_spread_asc"
DEFAULT_TTL_SECONDS = 300


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
    spread_ratio: float

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quoteVolume24h": self.quote_volume_24h,
            "tradeCount24h": self.trade_count_24h,
            "spreadRatio": self.spread_ratio,
        }


@dataclass(frozen=True)
class AsterUniverseSnapshot:
    requested_top_n: int
    eligible_markets: tuple[RankedAsterMarket, ...]
    fetched_at: datetime
    expires_at: datetime
    stale: bool = False
    entry_block_reason: str = ""

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
        }


def build_snapshot(
    exchange_info: dict[str, Any],
    tickers_24h: Iterable[dict[str, Any]],
    requested_top_n: Any,
    *,
    fetched_at: datetime | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> AsterUniverseSnapshot:
    requested = normalize_top_n(requested_top_n)
    now = (fetched_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    contracts = {
        str(row.get("symbol", "")).upper(): row
        for row in exchange_info.get("symbols", ())
        if isinstance(row, dict) and eligible_contract(row) and str(row.get("symbol", "")).strip()
    }
    markets: list[RankedAsterMarket] = []
    seen: set[str] = set()
    for ticker in tickers_24h:
        if not isinstance(ticker, dict):
            continue
        symbol = str(ticker.get("symbol", "")).upper()
        if symbol in seen or symbol not in contracts:
            continue
        last = _positive(ticker.get("lastPrice", ticker.get("price")))
        volume = _positive(ticker.get("quoteVolume", ticker.get("turnover")))
        bid = _positive(ticker.get("bidPrice"))
        ask = _positive(ticker.get("askPrice"))
        try:
            trades = max(0, int(ticker.get("count", ticker.get("tradeCount", 0))))
        except (TypeError, ValueError):
            trades = 0
        if not last or not volume or not bid or not ask or ask < bid:
            continue
        markets.append(RankedAsterMarket(symbol, volume, trades, (ask - bid) / last))
        seen.add(symbol)
    markets.sort(key=lambda item: (-item.quote_volume_24h, -item.trade_count_24h, item.spread_ratio, item.symbol))
    reason = "" if markets else "Aster retourneerde geen complete actieve USDT-perpetualmarkten"
    return AsterUniverseSnapshot(
        requested,
        tuple(markets),
        now,
        now + timedelta(seconds=max(1, int(ttl_seconds))),
        False,
        reason,
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
