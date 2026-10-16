"""Pure, conservative attribution of exchange-aggregate SHORT fills to zone LONGs.

No trading, Firestore, API, or order side effects. Reconciliation must precede use.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


def dec(value):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('non-finite quantity')
    return number


@dataclass(frozen=True)
class ZoneLong:
    account_id: str
    symbol: str
    zone_position_id: str
    long_qty: Decimal
    hedge_allocated_qty: Decimal


@dataclass(frozen=True)
class ClosedFill:
    account_id: str
    symbol: str
    exchange_fill_id: str
    closed_qty: Decimal
    realized_pnl: Decimal
    fee: Decimal
    funding: Decimal = Decimal('0')


def check_ownership(rows: Iterable[ZoneLong], *, account_id: str, symbol: str,
                    exchange_long_qty, exchange_short_qty) -> str:
    """Refuse ambiguous aggregate allocation; exchange does not expose zone-specific legs."""
    rows = tuple(rows)
    if not rows or not account_id or not symbol:
        return 'BLOCKED_MISSING_OWNERSHIP'
    if any(not r.zone_position_id or r.account_id != account_id or r.symbol != symbol for r in rows):
        return 'BLOCKED_SCOPE_MISMATCH'
    if len({r.zone_position_id for r in rows}) != len(rows):
        return 'BLOCKED_DUPLICATE_ZONE_POSITION'
    if any(r.long_qty <= 0 or r.hedge_allocated_qty < 0 or r.hedge_allocated_qty > r.long_qty for r in rows):
        return 'BLOCKED_BAD_ALLOCATION'
    if dec(exchange_long_qty) != sum((r.long_qty for r in rows), Decimal(0)):
        return 'BLOCKED_LONG_RECONCILIATION'
    if dec(exchange_short_qty) != sum((r.hedge_allocated_qty for r in rows), Decimal(0)):
        return 'BLOCKED_SHORT_RECONCILIATION'
    return 'RECONCILED_FOR_PREVIEW_ONLY'


def attribute_fill(fill: ClosedFill, *, expected_account: str, expected_symbol: str,
                   seen_ids: frozenset[str], cycle_id: str, intended_qty,
                   outstanding_allocated_qty) -> dict:
    """One fill in an unambiguous cycle; caller persists confirmed IDs atomically."""
    if not cycle_id or not fill.exchange_fill_id:
        raise ValueError('missing ownership/fill identity')
    if fill.account_id != expected_account or fill.symbol != expected_symbol:
        raise ValueError('cross-account or symbol fill')
    if fill.exchange_fill_id in seen_ids:
        raise ValueError('duplicate fill')
    if fill.closed_qty <= 0 or fill.closed_qty > dec(intended_qty) or fill.closed_qty > dec(outstanding_allocated_qty):
        raise ValueError('invalid partial fill')
    return {'cycle_id': cycle_id, 'fill_id': fill.exchange_fill_id,
            'closed_qty': fill.closed_qty,
            'net_realized_pnl': fill.realized_pnl - fill.fee + fill.funding}


def combined_cycle_pnl(*, long_open, short_open, confirmed_fill_net_pnls, other_fees=0, funding=0):
    return (dec(long_open) + dec(short_open) + sum((dec(x) for x in confirmed_fill_net_pnls), Decimal(0))
            - dec(other_fees) + dec(funding))
