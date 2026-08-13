"""Pure Hyperliquid DCA Pulse scanner rules.

No HTTP, database, signing or order side effects live in this module.  The
production scheduler may only consume these deterministic decisions after the
unit suite passes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from statistics import fmean, pstdev
from typing import Any, Iterable, Literal


EntryMode = Literal["direct", "bollinger"]


@dataclass(frozen=True)
class ScannerSettings:
    strategy_id: str = "strategy_3"
    base_order_usd: float = 20.0
    max_safety_orders: int = 3
    long_deviation_percent: float = 2.0
    short_deviation_percent: float = 8.0
    max_active_deals: int = 20
    cooldown_minutes: int = 15
    portfolio_target_percent: float = 10.0
    top_universe_size: int = 50
    entry_mode: EntryMode = "bollinger"
    leverage: int = 100
    stop_loss_enabled: bool = False
    stop_loss_percent: float = 25.0

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ScannerSettings":
        raw = value or {}
        aliases = {
            "strategyId": "strategy_id", "baseOrderUsd": "base_order_usd",
            "maxSafetyOrders": "max_safety_orders",
            "longDeviationPercent": "long_deviation_percent",
            "priceDeviationPercentage": "long_deviation_percent",
            "shortDeviationPercent": "short_deviation_percent",
            "shortPriceDeviationPercentage": "short_deviation_percent",
            "maxActiveDeals": "max_active_deals", "cooldownMinutes": "cooldown_minutes",
            "portfolioTargetPercent": "portfolio_target_percent",
            "portfolioTargetPercentage": "portfolio_target_percent",
            "topUniverseSize": "top_universe_size", "entryMode": "entry_mode",
            "stopLossEnabled": "stop_loss_enabled", "stopLossPercent": "stop_loss_percent",
            "stopLossPercentage": "stop_loss_percent",
        }
        translated = {aliases.get(key, key): item for key, item in raw.items()}
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: item for key, item in translated.items() if key in allowed})

    def validate(self) -> list[str]:
        errors: list[str] = []
        numeric = (self.base_order_usd, self.long_deviation_percent, self.short_deviation_percent,
                   self.portfolio_target_percent, self.stop_loss_percent)
        if any(not math.isfinite(float(item)) for item in numeric):
            errors.append("Scannerinstellingen bevatten een ongeldig getal")
        if self.strategy_id != "strategy_3": errors.append("Cloudscanner ondersteunt uitsluitend DCA Pulse")
        if not 10 <= self.base_order_usd <= 100_000: errors.append("Basisorder moet tussen $10 en $100.000 liggen")
        if not 0 <= self.max_safety_orders <= 20: errors.append("Maximaal aantal bijkopen moet tussen 0 en 20 liggen")
        if not .25 <= self.long_deviation_percent <= 25: errors.append("LONG-afwijking moet tussen 0,25% en 25% liggen")
        if not .25 <= self.short_deviation_percent <= 25: errors.append("SHORT-afwijking moet tussen 0,25% en 25% liggen")
        if not 1 <= self.max_active_deals <= 400: errors.append("Maximaal actieve deals moet tussen 1 en 400 liggen")
        if not 1 <= self.cooldown_minutes <= 10_080: errors.append("Scancyclus moet tussen 1 minuut en 7 dagen liggen")
        if not 1 <= self.portfolio_target_percent <= 1000: errors.append("Portfoliodoel moet tussen 1% en 1000% liggen")
        if not 1 <= self.top_universe_size <= 500: errors.append("Top-universum moet tussen 1 en 500 liggen")
        if self.entry_mode not in {"direct", "bollinger"}: errors.append("Kies direct of Bollinger als instapregel")
        if not 1 <= self.leverage <= 100: errors.append("Hyperliquid-hefboom moet tussen 1× en 100× liggen")
        if not 1 <= self.stop_loss_percent <= 25: errors.append("Stop-loss moet tussen 1% en 25% liggen")
        maximum_deal = self.base_order_usd * (self.max_safety_orders + 1)
        if maximum_deal > 100_000: errors.append("Maximale dealwaarde is hoger dan $100.000")
        return errors

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    mark_price: float
    previous_day_price: float
    max_leverage: int
    closed_one_minute_closes: tuple[float, ...] = ()

    @property
    def change_24h_percent(self) -> float:
        if self.mark_price <= 0 or self.previous_day_price <= 0: return 0.0
        return (self.mark_price / self.previous_day_price - 1.0) * 100.0


@dataclass(frozen=True)
class Candidate:
    symbol: str
    short: bool
    price: float
    change_24h_percent: float
    leverage: int
    reason: str


def normalize_symbol(value: str) -> str:
    return str(value).split(":")[-1].split("/")[0].split("-")[0].upper()


def universe_matches(symbol: str, allowed: set[str]) -> bool:
    base = normalize_symbol(symbol)
    values = {base}
    if base.startswith("K") and len(base) > 2: values.add(base[1:])
    if base.startswith("1000") and len(base) > 5: values.add(base[4:])
    return bool(values.intersection({item.upper() for item in allowed}))


def bollinger_position(closes: Iterable[float], price: float, period: int = 20, multiplier: float = 2.0) -> str:
    values = [float(item) for item in closes if math.isfinite(float(item)) and float(item) > 0]
    if len(values) < period or price <= 0: return "inside"
    window = values[-period:]
    average = fmean(window)
    deviation = pstdev(window)
    if price > average + multiplier * deviation: return "above"
    if price < average - multiplier * deviation: return "below"
    return "inside"


def select_candidates(markets: Iterable[MarketSnapshot], *, allowed_symbols: set[str],
                      active_symbols: set[str], settings: ScannerSettings) -> tuple[Candidate, ...]:
    active = {normalize_symbol(item) for item in active_symbols}
    by_base: dict[str, MarketSnapshot] = {}
    for market in markets:
        base = normalize_symbol(market.symbol)
        if base == "BTC" or base in active or not universe_matches(market.symbol, allowed_symbols): continue
        if market.mark_price <= 0 or market.previous_day_price <= 0 or market.change_24h_percent == 0: continue
        by_base.setdefault(base, market)
    ordered = sorted(by_base.values(), key=lambda item: (-abs(item.change_24h_percent), normalize_symbol(item.symbol)))
    result: list[Candidate] = []
    for market in ordered:
        short = market.change_24h_percent < 0
        position = bollinger_position(market.closed_one_minute_closes, market.mark_price)
        if settings.entry_mode == "bollinger":
            if short and position != "above": continue
            if not short and position != "below": continue
            condition = "boven BB(20,2)" if short else "onder BB(20,2)"
            reason = f"24u {market.change_24h_percent:+.2f}% · prijs {condition}"
        else:
            reason = f"Direct vullen · 24u {market.change_24h_percent:+.2f}%"
        result.append(Candidate(market.symbol, short, market.mark_price, market.change_24h_percent,
                                max(1, min(settings.leverage, market.max_leverage)), reason))
    return tuple(result)


def balance_permits(short: bool, long_count: int, short_count: int, maximum_difference: int = 3) -> bool:
    future_long = long_count + (0 if short else 1)
    future_short = short_count + (1 if short else 0)
    current_difference = abs(long_count - short_count)
    future_difference = abs(future_long - future_short)
    return future_difference < current_difference if current_difference > maximum_difference else future_difference <= maximum_difference


def choose_entries(candidates: Iterable[Candidate], *, active_count: int, maximum: int,
                   long_count: int, short_count: int) -> tuple[Candidate, ...]:
    selected: list[Candidate] = []
    for candidate in candidates:
        if active_count + len(selected) >= maximum: break
        if not balance_permits(candidate.short, long_count, short_count): continue
        selected.append(candidate)
        if candidate.short: short_count += 1
        else: long_count += 1
    return tuple(selected)


def required_deviation(settings: ScannerSettings, *, short: bool, safety_orders_completed: int) -> float:
    base = settings.short_deviation_percent if short else settings.long_deviation_percent
    return base * (max(0, safety_orders_completed) + 1)


def add_on_due(*, short: bool, current_price: float, initial_entry_price: float,
               safety_orders_completed: int, settings: ScannerSettings) -> bool:
    if current_price <= 0 or initial_entry_price <= 0 or safety_orders_completed >= settings.max_safety_orders: return False
    fraction = required_deviation(settings, short=short, safety_orders_completed=safety_orders_completed) / 100.0
    return current_price >= initial_entry_price * (1 + fraction) if short else current_price <= initial_entry_price * (1 - fraction)
