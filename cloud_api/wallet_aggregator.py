"""Transparent wallet aggregation without double-counting open PnL."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class ExchangeWalletSnapshot:
    exchange: str
    wallet_balance: float
    unrealized_pnl: float
    equity: float
    available_to_trade: float
    used_margin: float
    maintenance_margin: float
    captured_at_ms: int
    read_ok: bool


@dataclass(frozen=True)
class AggregatedWallet:
    configured_exchanges: tuple[str, ...]
    fresh_exchanges: tuple[str, ...]
    missing_or_stale_exchanges: tuple[str, ...]
    total_wallet_balance: float
    total_unrealized_pnl: float
    total_equity: float
    total_available_to_trade: float
    total_used_margin: float
    total_maintenance_margin: float
    margin_ratio: float
    is_complete: bool
    label: str


def aggregate_wallets(
    snapshots: Iterable[ExchangeWalletSnapshot],
    *,
    configured_exchanges: Iterable[str] = ("mexc", "hyperliquid", "aster"),
    now_ms: int,
    maximum_age_ms: int = 30_000,
) -> AggregatedWallet:
    configured = tuple(str(item).lower() for item in configured_exchanges)
    by_exchange = {item.exchange.lower(): item for item in snapshots}
    fresh: list[ExchangeWalletSnapshot] = []
    missing: list[str] = []
    for exchange in configured:
        row = by_exchange.get(exchange)
        if row is None or not row.read_ok or now_ms - row.captured_at_ms > maximum_age_ms:
            missing.append(exchange)
            continue
        values = (
            row.wallet_balance, row.unrealized_pnl, row.equity,
            row.available_to_trade, row.used_margin, row.maintenance_margin,
        )
        if any(not math.isfinite(value) for value in values):
            missing.append(exchange)
            continue
        fresh.append(row)

    wallet_balance = sum(item.wallet_balance for item in fresh)
    unrealized = sum(item.unrealized_pnl for item in fresh)
    # Equity is exchange-reported equity and already contains open PnL. Never
    # add unrealized PnL to this total a second time.
    equity = sum(item.equity for item in fresh)
    available = sum(item.available_to_trade for item in fresh)
    used = sum(max(item.used_margin, 0.0) for item in fresh)
    maintenance = sum(max(item.maintenance_margin, 0.0) for item in fresh)
    ratio = maintenance / equity if equity > 0 else math.inf
    complete = not missing
    label = "Totaal van alle exchanges" if complete else "Voorlopig totaal — exchange-data ontbreekt"
    return AggregatedWallet(
        configured_exchanges=configured,
        fresh_exchanges=tuple(item.exchange.lower() for item in fresh),
        missing_or_stale_exchanges=tuple(missing),
        total_wallet_balance=wallet_balance,
        total_unrealized_pnl=unrealized,
        total_equity=equity,
        total_available_to_trade=available,
        total_used_margin=used,
        total_maintenance_margin=maintenance,
        margin_ratio=ratio,
        is_complete=complete,
        label=label,
    )

