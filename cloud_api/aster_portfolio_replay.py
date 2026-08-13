"""Read-only counterfactual Strategy-2 portfolio replay.

The replay never owns an exchange client and therefore cannot submit orders.
It consumes immutable market/audit inputs prepared by the API boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal
import math

from aster_strategy2 import Strategy2Config, dca_level

Side = Literal["LONG", "SHORT"]


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


@dataclass(frozen=True)
class ReplayCandle:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class ReplaySeed:
    symbol: str
    side: Side
    timestamp_ms: int


@dataclass
class ReplayLeg:
    symbol: str
    side: Side
    opened_at_ms: int
    fills: list[tuple[float, float]]
    dca_count: int = 0
    entry_fees: float = 0.0

    @property
    def quantity(self) -> float:
        return sum(quantity for _, quantity in self.fills)

    @property
    def weighted_entry(self) -> float:
        quantity = self.quantity
        return sum(price * size for price, size in self.fills) / quantity if quantity else 0.0


def config_with_overrides(base: Strategy2Config, overrides: dict[str, Any]) -> Strategy2Config:
    allowed = {
        "takeProfit", "baseNotional", "longDcaDistance", "shortDcaDistance",
        "longMaxDca", "shortMaxDca", "dcaMultiplier", "leverage",
        "strategyBudget", "protectionEnabled", "autoRestart",
    }
    clean = {key: value for key, value in overrides.items() if key in allowed}
    return Strategy2Config.from_mapping({**base.public_dict(), **clean})


def _price_pnl(side: Side, entry: float, exit_price: float, quantity: float) -> float:
    return (exit_price - entry) * quantity if side == "LONG" else (entry - exit_price) * quantity


def run_portfolio_replay(
    *,
    candles: dict[str, list[ReplayCandle]],
    seeds: list[ReplaySeed],
    config: Strategy2Config,
    start_equity: float,
    comparison_at_ms: int,
    fee_rate: float = 0.0005,
    slippage_rate: float = 0.0003,
    observed_funding: float = 0.0,
    external_cashflow: float = 0.0,
    day_start_ms: int = 0,
    maintenance_rate: float = 0.0,
) -> dict[str, Any]:
    """Replay proven pair/side starts with the shared Strategy-2 DCA semantics.

    Pair selection is seeded by confirmed Strategy-2 audit events. This avoids
    inventing scanner decisions. A result is therefore indicative until the
    reference replay is shown to track the real account closely.
    """
    start_equity = max(0.0, number(start_equity))
    if start_equity <= 0:
        raise ValueError("Een bewezen positieve start-equity ontbreekt")
    ordered_seeds = sorted(seeds, key=lambda item: item.timestamp_ms)
    if not ordered_seeds:
        raise ValueError("Er zijn geen bewezen Strategy-2 instapmomenten gevonden")

    seed_queue: dict[str, list[ReplaySeed]] = {}
    for seed in ordered_seeds:
        seed_queue.setdefault(seed.symbol.upper(), []).append(seed)
    events: list[tuple[int, str, ReplayCandle]] = []
    for symbol, rows in candles.items():
        for candle in rows:
            if candle.timestamp_ms <= comparison_at_ms:
                events.append((candle.timestamp_ms, symbol.upper(), candle))
    events.sort(key=lambda item: (item[0], item[1]))
    if not events:
        raise ValueError("Historische Aster-candles ontbreken voor de replayperiode")

    cash = start_equity + external_cashflow
    realized = 0.0
    closed_result_today = 0.0
    fees = 0.0
    closed = 0
    dca_orders = 0
    tp_cycles = 0
    max_margin = 0.0
    max_maintenance_pct = 0.0
    high_water = start_equity
    min_equity = start_equity
    max_drawdown = 0.0
    legs: dict[tuple[str, Side], ReplayLeg] = {}
    activated: set[tuple[str, Side, int]] = set()
    last_price: dict[str, float] = {}

    for timestamp_ms, symbol, candle in events:
        last_price[symbol] = candle.close
        for seed in seed_queue.get(symbol, []):
            seed_key = (seed.symbol, seed.side, seed.timestamp_ms)
            key = (seed.symbol, seed.side)
            if seed.timestamp_ms <= timestamp_ms and seed_key not in activated and key not in legs:
                fill = candle.open * (1 + slippage_rate if seed.side == "LONG" else 1 - slippage_rate)
                quantity = config.base_notional / fill
                entry_fee = config.base_notional * fee_rate
                cash -= entry_fee
                fees += entry_fee
                legs[key] = ReplayLeg(seed.symbol, seed.side, timestamp_ms, [(fill, quantity)], entry_fees=entry_fee)
                activated.add(seed_key)

        for key, leg in list(legs.items()):
            if leg.symbol != symbol:
                continue
            average = leg.weighted_entry
            maximum = config.long_max_dca if leg.side == "LONG" else config.short_max_dca
            if config.dca_enabled and leg.dca_count < maximum:
                distance = dca_level(config, leg.side, leg.dca_count + 1)
                trigger = average * (1 - distance if leg.side == "LONG" else 1 + distance)
                touched = candle.low <= trigger if leg.side == "LONG" else candle.high >= trigger
                if touched:
                    notional = config.base_notional * config.dca_multiplier
                    current_margin = sum(sum(price * qty for price, qty in item.fills) / max(1, config.leverage) for item in legs.values())
                    if current_margin + notional / max(1, config.leverage) <= max(start_equity, cash) * config.strategy_budget:
                        fill = trigger * (1 + slippage_rate if leg.side == "LONG" else 1 - slippage_rate)
                        leg.fills.append((fill, notional / fill))
                        leg.dca_count += 1
                        dca_orders += 1
                        entry_fee = notional * fee_rate
                        cash -= entry_fee
                        fees += entry_fee
                        leg.entry_fees += entry_fee
                        average = leg.weighted_entry

            target = average * (1 + config.take_profit if leg.side == "LONG" else 1 - config.take_profit)
            hit = candle.high >= target if leg.side == "LONG" else candle.low <= target
            if hit:
                exit_price = target * (1 - slippage_rate if leg.side == "LONG" else 1 + slippage_rate)
                gross = _price_pnl(leg.side, average, exit_price, leg.quantity)
                exit_fee = exit_price * leg.quantity * fee_rate
                close_cashflow = gross - exit_fee
                net_closed = close_cashflow - leg.entry_fees
                cash += close_cashflow
                realized += net_closed
                if timestamp_ms >= day_start_ms:
                    closed_result_today += net_closed
                fees += exit_fee
                closed += 1
                tp_cycles += 1
                del legs[key]
                if config.auto_restart:
                    restart_fill = exit_price * (1 + slippage_rate if leg.side == "LONG" else 1 - slippage_rate)
                    quantity = config.base_notional / restart_fill
                    entry_fee = config.base_notional * fee_rate
                    cash -= entry_fee
                    fees += entry_fee
                    legs[key] = ReplayLeg(leg.symbol, leg.side, timestamp_ms, [(restart_fill, quantity)], entry_fees=entry_fee)

        unrealized = sum(
            _price_pnl(leg.side, leg.weighted_entry, last_price.get(leg.symbol, leg.weighted_entry), leg.quantity)
            for leg in legs.values()
        )
        equity = cash + unrealized + observed_funding
        high_water = max(high_water, equity)
        min_equity = min(min_equity, equity)
        max_drawdown = max(max_drawdown, (high_water - equity) / high_water if high_water > 0 else 0.0)
        max_margin = max(max_margin, sum(sum(price * qty for price, qty in leg.fills) / max(1, config.leverage) for leg in legs.values()))
        gross_exposure = sum(last_price.get(leg.symbol, leg.weighted_entry) * leg.quantity for leg in legs.values())
        estimated_maintenance = gross_exposure * max(0.0, maintenance_rate)
        max_maintenance_pct = max(max_maintenance_pct, estimated_maintenance / equity * 100 if equity > 0 else 100.0)

    unrealized = sum(
        _price_pnl(leg.side, leg.weighted_entry, last_price.get(leg.symbol, leg.weighted_entry), leg.quantity)
        for leg in legs.values()
    )
    ending = cash + unrealized + observed_funding
    long_exposure = sum(last_price.get(leg.symbol, leg.weighted_entry) * leg.quantity for leg in legs.values() if leg.side == "LONG")
    short_exposure = sum(last_price.get(leg.symbol, leg.weighted_entry) * leg.quantity for leg in legs.values() if leg.side == "SHORT")
    gross_exposure = long_exposure + short_exposure
    maintenance_margin = gross_exposure * max(0.0, maintenance_rate)
    maintenance_pct = maintenance_margin / ending * 100 if ending > 0 else (100.0 if gross_exposure else 0.0)
    return {
        "startPortfolio": start_equity,
        "endingPortfolio": ending,
        "totalPnl": ending - start_equity - external_cashflow,
        "returnPct": ((ending - external_cashflow) / start_equity - 1) * 100,
        "realizedPnl": realized,
        "closedResultToday": closed_result_today,
        "unrealizedPnl": unrealized,
        "fees": fees,
        "funding": observed_funding,
        "externalCashflow": external_cashflow,
        "openPositions": len(legs),
        "closedTrades": closed,
        "tpCycles": tp_cycles,
        "dcaOrders": dca_orders,
        "grossExposure": gross_exposure,
        "netExposure": long_exposure - short_exposure,
        "maxUsedMargin": max_margin,
        "maintenanceMargin": maintenance_margin,
        "maintenancePct": maintenance_pct,
        "maxMaintenancePct": max_maintenance_pct,
        "maintenanceEstimateReliable": maintenance_rate > 0,
        "maxDrawdownPct": max_drawdown * 100,
        "minimumEquity": min_equity,
        "settings": config.public_dict(),
    }


def comparison_conclusion(*, live_equity: float, reference: dict[str, Any], test_a: dict[str, Any], test_b: dict[str, Any], live_closed_today: float = 0.0, live_maintenance_pct: float = 0.0, tolerance_usd: float = 5.0, tolerance_pct: float = 2.0) -> dict[str, Any]:
    reference_deviation = number(reference.get("endingPortfolio")) - live_equity
    allowed = max(tolerance_usd, abs(live_equity) * tolerance_pct / 100)
    reliable = abs(reference_deviation) <= allowed
    candidates = {"Referentie": reference, "Test A": test_a, "Test B": test_b}
    winner, result = max(candidates.items(), key=lambda item: number(item[1].get("endingPortfolio")))
    delta = number(result.get("endingPortfolio")) - live_equity
    delta_pct = delta / live_equity * 100 if live_equity else 0.0
    if reliable:
        text = (f"{winner} presteerde op het belangrijkste criterium het beste: een geschatte portfoliowaarde van "
                f"US$ {number(result.get('endingPortfolio')):.2f}, oftewel US$ {delta:+.2f} ({delta_pct:+.2f}%) tegenover live. "
                f"Het gesloten resultaat vandaag is US$ {number(result.get('closedResultToday')):.2f} "
                f"(live US$ {live_closed_today:.2f}) en de geschatte maintenance is "
                f"{number(result.get('maintenancePct')):.2f}% (live {live_maintenance_pct:.2f}%).")
        status = "BETROUWBAAR"
    else:
        text = f"Geen betrouwbare winnaar: de referentiereplay wijkt US$ {reference_deviation:+.2f} af van het werkelijke liveverloop."
        status = "REFERENTIE_WIJKT_AF"
    return {"status": status, "reliable": reliable, "winner": winner if reliable else None, "primaryMetric": "endingPortfolio", "referenceDeviationUsd": reference_deviation, "allowedDeviationUsd": allowed, "differenceUsd": delta, "differencePct": delta_pct, "text": text}
