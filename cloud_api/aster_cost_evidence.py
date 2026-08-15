"""Complete, read-only Aster fee and funding evidence for owned positions.

The helpers in this module only call signed GET endpoints.  A full page is
never accepted as complete history: fills are continued by ``fromId`` and
income is continued by timestamp.  Invalid or non-progressing pagination
fails closed for the affected symbol.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from aster_strategy2_runtime import enrich_confirmed_costs
from aster_strategy2_state import OwnedLeg, number


@dataclass(frozen=True)
class SymbolCostEvidence:
    symbol: str
    trades: tuple[dict[str, Any], ...]
    income: tuple[dict[str, Any], ...]


def _rows(value: Any, *, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} gaf geen geldige lijst terug")
    if any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{label} bevat een ongeldig record")
    return list(value)


def paged_user_trades(client: Any, symbol: str, *, start_time: int | None = None,
                      page_size: int = 1000, maximum_pages: int = 100) -> list[dict[str, Any]]:
    """Read every fill from ``start_time`` or fail closed on an unsafe cursor."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    from_id: int | None = None
    for page_number in range(maximum_pages):
        if page_number == 0:
            page = _rows(client.user_trades(symbol, start_time=start_time, limit=page_size), label="Aster-fillhistorie")
        else:
            page = _rows(client.user_trades(symbol, from_id=from_id, limit=page_size), label="Aster-fillhistorie")
        for row in page:
            identity = str(row.get("id", row.get("tradeId", ""))).strip()
            fallback = f"{row.get('time', row.get('timestamp', ''))}|{row.get('orderId', '')}|{row.get('positionSide', '')}|{row.get('qty', row.get('quantity', ''))}"
            key = identity or fallback
            if key not in seen:
                seen.add(key)
                result.append(row)
        if len(page) < page_size:
            return result
        ids = [int(number(row.get("id", row.get("tradeId")))) for row in page]
        ids = [value for value in ids if value > 0]
        if not ids:
            raise ValueError(f"{symbol}: volle fillpagina zonder veilige vervolgcursor")
        next_id = max(ids) + 1
        if from_id is not None and next_id <= from_id:
            raise ValueError(f"{symbol}: fillpaginatie maakte geen voortgang")
        from_id = next_id
    raise ValueError(f"{symbol}: fillhistorie overschrijdt de veilige paginatiegrens")


def paged_income_history(client: Any, *, symbol: str, start_time: int | None = None,
                         page_size: int = 1000, maximum_pages: int = 100) -> list[dict[str, Any]]:
    """Read complete symbol income, continuing full pages by event timestamp."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor = start_time
    for _ in range(maximum_pages):
        page = _rows(client.income_history(symbol=symbol, start_time=cursor, limit=page_size), label="Aster-inkomstenhistorie")
        for row in page:
            identity = str(row.get("tranId", row.get("id", ""))).strip()
            fallback = f"{row.get('time', row.get('timestamp', ''))}|{row.get('incomeType', '')}|{row.get('positionSide', '')}|{row.get('income', '')}"
            key = identity or fallback
            if key not in seen:
                seen.add(key)
                result.append(row)
        if len(page) < page_size:
            return result
        times = [int(number(row.get("time", row.get("timestamp")))) for row in page]
        times = [value for value in times if value > 0]
        if not times:
            raise ValueError(f"{symbol}: volle inkomstenpagina zonder veilige vervolgcursor")
        next_cursor = max(times) + 1
        if cursor is not None and next_cursor <= cursor:
            raise ValueError(f"{symbol}: inkomstenpaginatie maakte geen voortgang")
        cursor = next_cursor
    raise ValueError(f"{symbol}: inkomstenhistorie overschrijdt de veilige paginatiegrens")


def read_symbol_cost_evidence(client: Any, symbol: str, legs: Iterable[OwnedLeg]) -> SymbolCostEvidence:
    values = list(legs)
    start_time = min((leg.created_at_ms for leg in values if leg.created_at_ms > 0), default=0) or None
    trades = paged_user_trades(client, symbol, start_time=start_time)
    for leg in values:
        if not any(
            str(row.get("symbol", "")).upper() == leg.symbol
            and str(row.get("positionSide", "")).upper() == leg.side
            and (leg.created_at_ms <= 0 or int(number(row.get("time", row.get("timestamp")))) >= leg.created_at_ms)
            for row in trades
        ):
            raise ValueError(f"{leg.symbol} {leg.side}: geen bevestigde openingsfill in de complete historie")
    income = paged_income_history(client, symbol=symbol, start_time=start_time)
    return SymbolCostEvidence(symbol.upper(), tuple(trades), tuple(income))


def refresh_owned_costs(client: Any, owned: list[OwnedLeg], symbols: Iterable[str], *,
                        checked_at_ms: int) -> tuple[list[OwnedLeg], dict[str, str]]:
    """Refresh only symbols with complete evidence; preserve all others unchanged."""
    result = list(owned)
    failures: dict[str, str] = {}
    by_symbol: dict[str, list[OwnedLeg]] = {}
    for leg in owned:
        by_symbol.setdefault(leg.symbol, []).append(leg)
    for symbol in sorted({str(value).upper() for value in symbols if str(value)}):
        legs = by_symbol.get(symbol, [])
        if not legs:
            continue
        try:
            evidence = read_symbol_cost_evidence(client, symbol, legs)
        except Exception as exc:
            failures[symbol] = str(exc)
            continue
        result = enrich_confirmed_costs(
            result, list(evidence.trades), list(evidence.income),
            refreshed_symbols={symbol}, checked_at_ms=checked_at_ms,
        )
    return result, failures


def bounded_history_symbols(priority_symbols: Iterable[str], background_symbols: Iterable[str], *,
                            maximum_symbols: int = 8, rotation_slot: int = 0) -> list[str]:
    """Bound one browser history refresh and rotate non-urgent symbols."""
    maximum = max(1, int(maximum_symbols))
    priority = list(dict.fromkeys(str(value).upper() for value in priority_symbols if str(value)))
    if len(priority) >= maximum:
        return priority[:maximum]
    background = [value for value in dict.fromkeys(
        str(item).upper() for item in background_symbols if str(item)
    ) if value not in priority]
    if not background:
        return priority
    offset = (max(0, int(rotation_slot)) * maximum) % len(background)
    rotated = background[offset:] + background[:offset]
    return priority + rotated[:maximum - len(priority)]


def cost_refresh_symbols(owned: list[OwnedLeg], positions: list[dict[str, Any]], *,
                         maximum_background: int = 4, maximum_total: int = 6) -> list[str]:
    """Select a rotating, rate-budgeted fee/funding refresh batch.

    Profitable and changed positions remain first, but no class can bypass the
    genuine Aster REST request budget.  Within each class the oldest persisted
    evidence wins, so repeated minute ticks rotate instead of starving legs.
    """
    pos = {(str(row.get("symbol", "")).upper(), str(row.get("positionSide", row.get("side", ""))).upper()): row
        for row in positions}
    urgent: set[str] = set()
    changed: set[str] = set()
    for leg in owned:
        row = pos.get((leg.symbol, leg.side))
        if not row:
            continue
        if number(row.get("unRealizedProfit", row.get("unrealizedPnl"))) > 0:
            urgent.add(leg.symbol)
        quantity = abs(number(row.get("positionAmt", row.get("quantity"))))
        entry = number(row.get("entryPrice"))
        if abs(quantity - leg.quantity) > max(1e-8, abs(leg.quantity) * 1e-7) or abs(entry - leg.weighted_entry) > max(1e-8, abs(leg.weighted_entry) * 1e-7):
            changed.add(leg.symbol)
    oldest_by_symbol: dict[str, int] = {}
    for leg in owned:
        oldest_by_symbol[leg.symbol] = min(oldest_by_symbol.get(leg.symbol, leg.costs_updated_at_ms), leg.costs_updated_at_ms)
    candidates = sorted(oldest_by_symbol, key=lambda symbol: (
        symbol not in urgent,
        symbol not in changed,
        oldest_by_symbol[symbol],
        symbol,
    ))
    background_used = 0
    selected: list[str] = []
    for symbol in candidates:
        is_priority = symbol in urgent or symbol in changed
        if not is_priority and background_used >= max(0, maximum_background):
            continue
        selected.append(symbol)
        if not is_priority:
            background_used += 1
        if len(selected) >= max(1, maximum_total):
            break
    return selected
