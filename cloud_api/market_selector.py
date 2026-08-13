"""Pure CoinMarketCap-driven candidate selection for multiple exchanges."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

from dca_universe import minimum_complete_count, normalize_universe_size


@dataclass(frozen=True)
class MarketCandidate:
    symbol: str
    cmc_rank: int
    change_24h_percent: float
    absolute_movement_percent: float
    exchange_symbol: str


@dataclass(frozen=True)
class MarketSelection:
    ready: bool
    reason: str
    requested_universe_size: int
    received_rank_count: int
    candidates: tuple[MarketCandidate, ...]


def select_candidates(
    cmc_rows: Iterable[dict[str, Any]],
    *,
    requested_universe_size: int,
    exchange_symbols: Iterable[str],
    quote_asset: str = "USDT",
    excluded_base_assets: Iterable[str] = (),
) -> MarketSelection:
    """Rank exchange-tradable top-N assets by absolute 24h movement.

    This is a market selector only. It never creates direction, leverage or
    order permission; those remain strategy and risk-manager decisions.
    """
    limit = normalize_universe_size(requested_universe_size)
    quote = quote_asset.upper()
    supported = {str(item).replace("_", "").upper() for item in exchange_symbols}
    excluded = {str(item).upper() for item in excluded_base_assets}
    by_rank: dict[int, tuple[str, float]] = {}
    seen_symbols: set[str] = set()

    for raw in cmc_rows:
        try:
            rank = int(raw.get("cmc_rank", raw.get("rank", 0)))
            symbol = str(raw.get("symbol", "")).strip().upper()
            quote_block = raw.get("quote") if isinstance(raw.get("quote"), dict) else {}
            usd_block = quote_block.get("USD") if isinstance(quote_block.get("USD"), dict) else {}
            change = float(raw.get("percent_change_24h", usd_block.get("percent_change_24h")))
        except (TypeError, ValueError):
            continue
        if not symbol or symbol in seen_symbols or not 1 <= rank <= limit or not math.isfinite(change):
            continue
        by_rank[rank] = (symbol, change)
        seen_symbols.add(symbol)

    received = len(by_rank)
    required = minimum_complete_count(limit)
    if received < required:
        return MarketSelection(
            False,
            f"CoinMarketCap top-{limit} is onvolledig ({received}/{required} minimaal)",
            limit,
            received,
            (),
        )

    candidates: list[MarketCandidate] = []
    for rank in sorted(by_rank):
        symbol, change = by_rank[rank]
        exchange_symbol = f"{symbol}{quote}"
        if symbol in excluded or exchange_symbol not in supported:
            continue
        candidates.append(MarketCandidate(
            symbol=symbol,
            cmc_rank=rank,
            change_24h_percent=change,
            absolute_movement_percent=abs(change),
            exchange_symbol=exchange_symbol,
        ))
    candidates.sort(key=lambda item: (-item.absolute_movement_percent, item.cmc_rank, item.symbol))
    return MarketSelection(
        True,
        "CoinMarketCap-universum en exchange-contracten zijn gecontroleerd",
        limit,
        received,
        tuple(candidates),
    )

