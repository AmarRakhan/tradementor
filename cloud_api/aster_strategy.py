"""Pure decision model for the Aster multi-pair hedge/DCA strategy.

No network or order submission lives here.  The cloud adapter must reconcile
exchange truth before applying an action returned by this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Side = Literal["LONG", "SHORT"]


@dataclass(frozen=True)
class AsterStrategySettings:
    enabled: bool = False
    mode: Literal["paper", "live"] = "paper"
    base_notional: float = 10.0
    maximum_pairs: int = 5
    universe_top_n: int = 50
    scan_interval_seconds: int = 60
    long_dca_deviation: float = .02
    short_dca_deviation: float = .05
    maximum_long_dca: int = 3
    maximum_short_dca: int = 3
    dca_multiplier: float = 1.0
    net_take_profit: float = .005
    bot_margin_budget_ratio: float = .50
    pair_budget_tolerance: float = .05
    momentum_reinvest_ratio: float = .50
    block_risk_ratio: float = .50
    reduce_risk_ratio: float = .70
    emergency_risk_ratio: float = .80
    daily_new_pair_pause: float = .05
    margin_mode: Literal["cross"] = "cross"
    use_maximum_leverage: bool = True

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "AsterStrategySettings":
        raw = raw or {}
        def n(name: str, default: float) -> float:
            try: return float(raw.get(name, default))
            except (TypeError, ValueError): return default
        def i(name: str, default: int) -> int:
            return int(n(name, default))
        return cls(
            enabled=bool(raw.get("enabled", False)),
            mode="live" if raw.get("mode") == "live" else "paper",
            base_notional=n("baseNotional", 10), maximum_pairs=i("maximumPairs", 5),
            universe_top_n=i("universeTopN", 50), scan_interval_seconds=i("scanIntervalSeconds", 60),
            long_dca_deviation=n("longDcaDeviation", .02), short_dca_deviation=n("shortDcaDeviation", .05),
            maximum_long_dca=i("maximumLongDca", 3), maximum_short_dca=i("maximumShortDca", 3),
            dca_multiplier=n("dcaMultiplier", 1), net_take_profit=n("netTakeProfit", .005),
            bot_margin_budget_ratio=n("botMarginBudgetRatio", .5),
            pair_budget_tolerance=n("pairBudgetTolerance", .05),
            momentum_reinvest_ratio=n("momentumReinvestRatio", .5),
            block_risk_ratio=n("blockRiskRatio", .5), reduce_risk_ratio=n("reduceRiskRatio", .7),
            emergency_risk_ratio=n("emergencyRiskRatio", .8),
            daily_new_pair_pause=n("dailyNewPairPause", .05),
        ).validated()

    def validated(self) -> "AsterStrategySettings":
        if not 5 <= self.base_notional <= 100_000: raise ValueError("Basisorder moet tussen 5 en 100.000 USD liggen")
        if not 1 <= self.maximum_pairs <= 100: raise ValueError("Maximaal aantal pairs moet tussen 1 en 100 liggen")
        if not 1 <= self.universe_top_n <= 200: raise ValueError("CoinMarketCap top-N moet tussen 1 en 200 liggen")
        if self.scan_interval_seconds != 60: raise ValueError("Aster-scanner draait veilig eenmaal per minuut")
        if not 0 < self.long_dca_deviation <= .50 or not 0 < self.short_dca_deviation <= .50:
            raise ValueError("DCA-afstanden moeten tussen 0 en 50% liggen")
        if not 0 <= self.maximum_long_dca <= 50 or not 0 <= self.maximum_short_dca <= 50:
            raise ValueError("Maximaal aantal DCA-orders moet tussen 0 en 50 liggen")
        if not 1 <= self.dca_multiplier <= 5: raise ValueError("DCA-vermenigvuldiger moet tussen 1 en 5 liggen")
        if not .001 <= self.net_take_profit <= .10: raise ValueError("Netto winstdoel moet tussen 0,1 en 10% liggen")
        if not 0 < self.bot_margin_budget_ratio <= .90: raise ValueError("Botbudget moet maximaal 90% zijn")
        if not 0 <= self.pair_budget_tolerance <= .50: raise ValueError("Pairspeling moet tussen 0 en 50% liggen")
        if not 0 <= self.momentum_reinvest_ratio <= 1: raise ValueError("Herinvestering moet tussen 0 en 100% liggen")
        if not 0 < self.block_risk_ratio < self.reduce_risk_ratio < self.emergency_risk_ratio < 1:
            raise ValueError("Margin-noodremniveaus moeten oplopend en onder 100% zijn")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled, "mode": self.mode, "baseNotional": self.base_notional,
            "maximumPairs": self.maximum_pairs, "universeTopN": self.universe_top_n,
            "scanIntervalSeconds": self.scan_interval_seconds,
            "longDcaDeviation": self.long_dca_deviation, "shortDcaDeviation": self.short_dca_deviation,
            "maximumLongDca": self.maximum_long_dca, "maximumShortDca": self.maximum_short_dca,
            "dcaMultiplier": self.dca_multiplier, "netTakeProfit": self.net_take_profit,
            "botMarginBudgetRatio": self.bot_margin_budget_ratio,
            "pairBudgetTolerance": self.pair_budget_tolerance,
            "momentumReinvestRatio": self.momentum_reinvest_ratio,
            "blockRiskRatio": self.block_risk_ratio, "reduceRiskRatio": self.reduce_risk_ratio,
            "emergencyRiskRatio": self.emergency_risk_ratio, "dailyNewPairPause": self.daily_new_pair_pause,
            "marginMode": self.margin_mode, "useMaximumLeverage": self.use_maximum_leverage,
        }


@dataclass(frozen=True)
class Leg:
    side: Side
    notional: float
    entry_price: float
    dca_count: int = 0
    unrealized_pnl: float = 0.0
    funding: float = 0.0


@dataclass(frozen=True)
class Pair:
    symbol: str
    long: Leg | None = None
    short: Leg | None = None
    realized_profit: float = 0.0
    momentum_pot: float = 0.0


@dataclass(frozen=True)
class Account:
    equity: float
    available: float
    margin_ratio: float
    cycle_start_equity: float
    used_bot_margin: float = 0.0


@dataclass(frozen=True)
class Action:
    kind: str
    symbol: str = ""
    side: Side | None = None
    notional: float = 0.0
    reason: str = ""
    safety: bool = False


def risk_mode(settings: AsterStrategySettings, account: Account) -> str:
    if account.margin_ratio >= settings.emergency_risk_ratio: return "EMERGENCY"
    if account.margin_ratio >= settings.reduce_risk_ratio: return "REDUCE"
    if account.margin_ratio >= settings.block_risk_ratio: return "BLOCK"
    return "NORMAL"


def dca_trigger(settings: AsterStrategySettings, leg: Leg, current_price: float) -> bool:
    maximum = settings.maximum_long_dca if leg.side == "LONG" else settings.maximum_short_dca
    if leg.dca_count >= maximum or current_price <= 0 or leg.entry_price <= 0: return False
    spacing = settings.long_dca_deviation if leg.side == "LONG" else settings.short_dca_deviation
    level = leg.dca_count + 1
    trigger = leg.entry_price * (1 - spacing * level if leg.side == "LONG" else 1 + spacing * level)
    tolerance = max(abs(trigger), 1.0) * 1e-12
    return current_price <= trigger + tolerance if leg.side == "LONG" else current_price + tolerance >= trigger


def harvest_due(settings: AsterStrategySettings, leg: Leg, expected_close_fee: float,
                expected_reopen_fee: float) -> bool:
    net = leg.unrealized_pnl + leg.funding - expected_close_fee - expected_reopen_fee
    return net >= leg.notional * settings.net_take_profit


def pair_margin_cap(settings: AsterStrategySettings, account: Account) -> float:
    total_budget = account.equity * settings.bot_margin_budget_ratio
    return total_budget / settings.maximum_pairs * (1 + settings.pair_budget_tolerance)


def choose_next(settings: AsterStrategySettings, account: Account, pairs: list[Pair],
                ranked_symbols: list[str], prices: dict[str, float], *,
                estimated_pair_margin: dict[str, float]) -> Action:
    mode = risk_mode(settings, account)
    if not settings.enabled: return Action("HOLD", reason="Aster-bot staat uit", safety=True)
    if mode != "NORMAL": return Action("HOLD", reason=f"Marginbeveiliging: {mode}", safety=True)
    if account.cycle_start_equity > 0 and account.equity <= account.cycle_start_equity * (1-settings.daily_new_pair_pause):
        return Action("HOLD", reason="Nieuwe pairs gepauzeerd door cyclus-drawdown", safety=True)
    active = {pair.symbol.upper() for pair in pairs if pair.long or pair.short}
    if len(active) >= settings.maximum_pairs: return Action("HOLD", reason="Maximaal aantal actieve pairs bereikt")
    remaining_budget = account.equity * settings.bot_margin_budget_ratio - account.used_bot_margin
    for symbol in ranked_symbols:
        symbol = symbol.upper()
        if symbol in active or prices.get(symbol, 0) <= 0: continue
        needed = estimated_pair_margin.get(symbol, float("inf"))
        if needed <= remaining_budget and needed <= pair_margin_cap(settings, account):
            return Action("OPEN_PAIR", symbol=symbol, notional=settings.base_notional,
                          reason="Hoogst gerangschikte niet-actieve top-N stijger")
    return Action("HOLD", reason="Geen kandidaat past binnen budget en exchangefilters")
