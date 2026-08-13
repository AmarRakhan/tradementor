"""Pure CoinMarketCap universe helpers, kept independent for safe unit tests."""

from __future__ import annotations

import math
from typing import Any


def normalize_universe_size(value: int) -> int:
    return max(1, min(500, int(value)))


def minimum_complete_count(value: int) -> int:
    return max(1, math.ceil(normalize_universe_size(value) * 0.90))


def ranked_symbols(payload: dict[str, Any], value: int) -> list[dict[str, Any]]:
    limit = normalize_universe_size(value)
    return [
        {"symbol": str(item.get("symbol", "")).upper(), "rank": int(item.get("cmc_rank", 0))}
        for item in payload.get("data", [])
        if str(item.get("symbol", "")).strip() and 1 <= int(item.get("cmc_rank", 0)) <= limit
    ]


def page_starts(value: int, page_size: int = 50) -> list[int]:
    """Return one-based page starts needed to fetch an arbitrary top-N universe."""
    limit = normalize_universe_size(value)
    size = max(1, min(100, int(page_size)))
    return list(range(1, limit + 1, size))


def merge_ranked_pages(payloads: list[dict[str, Any]], value: int) -> list[dict[str, Any]]:
    """Merge CMC pages by rank and remove duplicate symbols/ranks deterministically."""
    limit = normalize_universe_size(value)
    by_rank: dict[int, dict[str, Any]] = {}
    seen_symbols: set[str] = set()
    for payload in payloads:
        for item in ranked_symbols(payload, limit):
            symbol = item["symbol"]
            rank = item["rank"]
            if rank in by_rank or symbol in seen_symbols:
                continue
            by_rank[rank] = item
            seen_symbols.add(symbol)
    return [by_rank[rank] for rank in sorted(by_rank) if rank <= limit]


def symbol_codes(values: list[Any]) -> list[str]:
    """Accept the ranked CMC objects returned by the API (and legacy strings)."""
    result: list[str] = []
    for value in values:
        symbol = value.get("symbol", "") if isinstance(value, dict) else value
        code = str(symbol or "").strip().upper()
        if code and code not in result:
            result.append(code)
    return result
