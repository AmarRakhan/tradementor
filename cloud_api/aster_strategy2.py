"""Pure Strategy-2 engine: Dual Profit Harvest DCA + Dynamic Protection.

The module contains no network calls. Paper and live execution consume the
same decisions; only the adapter that applies an Action differs.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal
import math
from aster_universe import normalize_top_n

Side = Literal["LONG", "SHORT"]
Role = Literal["HARVEST", "HARVEST_PROTECTION", "PROTECTION"]
RiskMode = Literal["NORMAL", "CAUTION", "DEFENSIVE", "EMERGENCY"]


@dataclass(frozen=True)
class Strategy2Config:
    strategy_id: str = "aster-strategy-2"
    name: str = "Dual Profit Harvest DCA"
    version: int = 1
    mode: Literal["paper", "live"] = "paper"
    base_notional: float = 10.0
    take_profit: float = .015
    auto_restart: bool = True
    dca_enabled: bool = True
    dca_mode: Literal["fixed", "progressive", "custom"] = "fixed"
    long_dca_distance: float = .02
    short_dca_distance: float = .02
    long_max_dca: int = 3
    short_max_dca: int = 3
    dca_multiplier: float = 1.0
    long_custom_levels: tuple[float, ...] = ()
    short_custom_levels: tuple[float, ...] = ()
    maximum_pairs: int = 5
    universe_top_n: int = 50
    leverage: int = 10
    margin_mode: Literal["cross", "isolated"] = "cross"
    strategy_budget: float = .50
    protection_enabled: bool = True
    caution_drawdown: float = .03
    defensive_drawdown: float = .06
    emergency_drawdown: float = .10
    caution_margin_ratio: float = .35
    defensive_margin_ratio: float = .50
    emergency_margin_ratio: float = .70
    max_protection_ratio: float = .50
    max_net_exposure_ratio: float = .30
    max_gross_exposure_ratio: float = 1.00

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "Strategy2Config":
        raw = raw or {}
        def f(key: str, default: float) -> float:
            try: value = float(raw.get(key, default))
            except (TypeError, ValueError): value = default
            return value if math.isfinite(value) else default
        def i(key: str, default: int) -> int: return int(f(key, default))
        def levels(key: str) -> tuple[float, ...]:
            values = raw.get(key, ())
            return tuple(float(x) for x in values) if isinstance(values, (list, tuple)) else ()
        value = cls(
            strategy_id=str(raw.get("strategyId", cls.strategy_id)), name=str(raw.get("name", cls.name)),
            version=i("version", 1), mode="live" if raw.get("mode") == "live" else "paper",
            base_notional=f("baseNotional", 10), take_profit=f("takeProfit", .015),
            auto_restart=bool(raw.get("autoRestart", True)), dca_enabled=bool(raw.get("dcaEnabled", True)),
            dca_mode=str(raw.get("dcaMode", "fixed")).lower(),
            long_dca_distance=f("longDcaDistance", .02), short_dca_distance=f("shortDcaDistance", .02),
            long_max_dca=i("longMaxDca", 3), short_max_dca=i("shortMaxDca", 3),
            dca_multiplier=f("dcaMultiplier", 1), long_custom_levels=levels("longCustomLevels"),
            short_custom_levels=levels("shortCustomLevels"), maximum_pairs=i("maximumPairs", 5),
            universe_top_n=normalize_top_n(raw.get("universeTopN", 50)), leverage=i("leverage", 10),
            margin_mode="isolated" if raw.get("marginMode") == "isolated" else "cross",
            strategy_budget=f("strategyBudget", .5), protection_enabled=bool(raw.get("protectionEnabled", True)),
            caution_drawdown=f("cautionDrawdown", .03), defensive_drawdown=f("defensiveDrawdown", .06),
            emergency_drawdown=f("emergencyDrawdown", .10), caution_margin_ratio=f("cautionMarginRatio", .35),
            defensive_margin_ratio=f("defensiveMarginRatio", .50), emergency_margin_ratio=f("emergencyMarginRatio", .70),
            max_protection_ratio=f("maxProtectionRatio", .50), max_net_exposure_ratio=f("maxNetExposureRatio", .30),
            max_gross_exposure_ratio=f("maxGrossExposureRatio", 1.0),
        )
        return value.validated()

    def validated(self) -> "Strategy2Config":
        if self.dca_mode not in {"fixed", "progressive", "custom"}: raise ValueError("Ongeldige DCA-modus")
        if not 1 <= self.base_notional <= 100_000: raise ValueError("Base Order moet tussen 1 en 100.000 USD liggen")
        if not .001 <= self.take_profit <= .20: raise ValueError("Take Profit moet tussen 0,1% en 20% liggen")
        if not 1 <= self.maximum_pairs <= 100: raise ValueError("Max Active Pairs moet tussen 1 en 100 liggen")
        if self.universe_top_n < 1: raise ValueError("Aster USDT Top-N moet een positief geheel getal zijn")
        if not 1 <= self.leverage <= 200: raise ValueError("Leverage moet tussen 1 en 200 liggen en wordt nog aan het contract getoetst")
        if not 0 <= self.long_max_dca <= 50 or not 0 <= self.short_max_dca <= 50: raise ValueError("Max DCA moet tussen 0 en 50 liggen")
        if not 0 < self.long_dca_distance <= .80 or not 0 < self.short_dca_distance <= .80: raise ValueError("DCA-afstand moet tussen 0 en 80% liggen")
        if not 0 < self.dca_multiplier <= 10: raise ValueError("DCA multiplier moet groter dan 0 en maximaal 10 zijn")
        if self.dca_mode == "custom":
            for values, maximum in ((self.long_custom_levels, self.long_max_dca), (self.short_custom_levels, self.short_max_dca)):
                if len(values) < maximum or any(x <= 0 for x in values) or list(values) != sorted(values):
                    raise ValueError("Custom DCA-levels moeten positief, oplopend en volledig zijn")
        if not 0 < self.strategy_budget <= .90: raise ValueError("Strategy Budget moet tussen 0 en 90% liggen")
        if not 0 < self.caution_drawdown < self.defensive_drawdown < self.emergency_drawdown < 1: raise ValueError("Drawdown-drempels moeten oplopen")
        if not 0 < self.caution_margin_ratio < self.defensive_margin_ratio < self.emergency_margin_ratio < 1: raise ValueError("Margin-drempels moeten oplopen")
        if not 0 <= self.max_protection_ratio <= 1: raise ValueError("Maximum Protection moet tussen 0 en 100% liggen")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {"strategyId":self.strategy_id,"name":self.name,"version":self.version,"mode":self.mode,
            "baseNotional":self.base_notional,"takeProfit":self.take_profit,"autoRestart":self.auto_restart,
            "dcaEnabled":self.dca_enabled,"dcaMode":self.dca_mode,"longDcaDistance":self.long_dca_distance,
            "shortDcaDistance":self.short_dca_distance,"longMaxDca":self.long_max_dca,"shortMaxDca":self.short_max_dca,
            "dcaMultiplier":self.dca_multiplier,"longCustomLevels":list(self.long_custom_levels),
            "shortCustomLevels":list(self.short_custom_levels),"maximumPairs":self.maximum_pairs,
            "universeTopN":self.universe_top_n,"leverage":self.leverage,"marginMode":self.margin_mode,
            "strategyBudget":self.strategy_budget,"protectionEnabled":self.protection_enabled,
            "cautionDrawdown":self.caution_drawdown,"defensiveDrawdown":self.defensive_drawdown,
            "emergencyDrawdown":self.emergency_drawdown,"cautionMarginRatio":self.caution_margin_ratio,
            "defensiveMarginRatio":self.defensive_margin_ratio,"emergencyMarginRatio":self.emergency_margin_ratio,
            "maxProtectionRatio":self.max_protection_ratio,"maxNetExposureRatio":self.max_net_exposure_ratio,
            "maxGrossExposureRatio":self.max_gross_exposure_ratio}


@dataclass(frozen=True)
class LegState:
    side: Side
    cycle_id: str
    size: float
    weighted_entry: float
    current_price: float
    dca_count: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fees: float = 0.0
    funding: float = 0.0
    role: Role = "HARVEST"
    config_version: int = 1
    lifecycle: Literal["IDLE","OPENING","HARVEST","DCA","HARVEST_PROTECTION","PROTECTION","TP_PENDING","CLOSING","CLOSED","RECOVERY"] = "HARVEST"


@dataclass(frozen=True)
class PortfolioState:
    equity: float
    adjusted_high_water_mark: float
    margin_ratio: float
    long_exposure: float
    short_exposure: float
    strategy_exposure: float
    exchange_reliable: bool = True
    ownership_reliable: bool = True
    open_orders_unknown: bool = False
    # Actual margin reserved by Strategy 2. Exposure is leveraged notional.
    strategy_margin: float = 0.0

    @property
    def drawdown(self) -> float:
        return max(0.0, 1 - self.equity / self.adjusted_high_water_mark) if self.adjusted_high_water_mark > 0 else 0.0


@dataclass(frozen=True)
class Decision:
    kind: str
    side: Side | None = None
    notional: float = 0.0
    retain_notional: float = 0.0
    role: Role | None = None
    reason: str = ""
    risk_reducing: bool = False


def risk_mode(config: Strategy2Config, portfolio: PortfolioState) -> RiskMode:
    if portfolio.margin_ratio >= config.emergency_margin_ratio or portfolio.drawdown >= config.emergency_drawdown: return "EMERGENCY"
    if portfolio.margin_ratio >= config.defensive_margin_ratio or portfolio.drawdown >= config.defensive_drawdown: return "DEFENSIVE"
    if portfolio.margin_ratio >= config.caution_margin_ratio or portfolio.drawdown >= config.caution_drawdown: return "CAUTION"
    return "NORMAL"


def dca_level(config: Strategy2Config, side: Side, level: int) -> float:
    custom = config.long_custom_levels if side == "LONG" else config.short_custom_levels
    base = config.long_dca_distance if side == "LONG" else config.short_dca_distance
    if config.dca_mode == "custom": return custom[level - 1]
    if config.dca_mode == "progressive": return base * level * (level + 1) / 2
    return base * level


def dca_due(config: Strategy2Config, leg: LegState) -> bool:
    maximum = config.long_max_dca if leg.side == "LONG" else config.short_max_dca
    if not config.dca_enabled or leg.dca_count >= maximum or leg.weighted_entry <= 0: return False
    deviation = dca_level(config, leg.side, leg.dca_count + 1)
    trigger = leg.weighted_entry * (1 - deviation if leg.side == "LONG" else 1 + deviation)
    return leg.current_price <= trigger if leg.side == "LONG" else leg.current_price >= trigger


def net_profit(leg: LegState, estimated_close_fee: float = 0.0) -> float:
    return leg.unrealized_pnl + leg.funding - leg.fees - estimated_close_fee


def tp_due(config: Strategy2Config, leg: LegState, estimated_close_fee: float = 0.0) -> bool:
    return leg.size > 0 and net_profit(leg, estimated_close_fee) >= leg.size * config.take_profit


def required_protection(config: Strategy2Config, portfolio: PortfolioState, winning_side: Side) -> float:
    """Minimum opposite exposure retained to keep net exposure inside its cap."""
    if not config.protection_enabled or risk_mode(config, portfolio) == "NORMAL": return 0.0
    cap = portfolio.equity * config.max_net_exposure_ratio
    if winning_side == "LONG": return max(0.0, portfolio.short_exposure - cap)
    return max(0.0, portfolio.long_exposure - cap)


def decide_leg(config: Strategy2Config, leg: LegState, portfolio: PortfolioState, *, estimated_close_fee: float = 0.0) -> Decision:
    if not portfolio.exchange_reliable or not portfolio.ownership_reliable or portfolio.open_orders_unknown:
        return Decision("HOLD", leg.side, reason="Exchange-state, ownership of orderstatus is onzeker; geen nieuw risico", risk_reducing=True)
    mode = risk_mode(config, portfolio)
    if tp_due(config, leg, estimated_close_fee):
        retain = min(leg.size, required_protection(config, portfolio, leg.side))
        if retain >= leg.size - 1e-9:
            return Decision("ASSIGN_PROTECTION", leg.side, retain_notional=leg.size, role="PROTECTION", reason=f"TP bereikt maar volledige sluiting verslechtert portfoliorisico in {mode}", risk_reducing=True)
        if retain > 0:
            return Decision("PARTIAL_TP", leg.side, notional=leg.size-retain, retain_notional=retain, role="HARVEST_PROTECTION", reason=f"Veilig deel oogsten; {retain:.2f} USD blijft als protection", risk_reducing=True)
        return Decision("FULL_TP", leg.side, notional=leg.size, role="HARVEST", reason="Netto TP bereikt en volledige sluiting is portfolioveilig", risk_reducing=True)
    if mode in {"DEFENSIVE", "EMERGENCY"}: return Decision("HOLD", leg.side, role=leg.role, reason=f"{mode}: nieuwe normale DCA geblokkeerd", risk_reducing=True)
    if dca_due(config, leg):
        proposed = config.base_notional * config.dca_multiplier
        budget = portfolio.equity * config.strategy_budget
        proposed_margin = proposed / max(1, config.leverage)
        if portfolio.strategy_margin + proposed_margin > budget: return Decision("HOLD", leg.side, reason="DCA geblokkeerd door Strategy Margin Budget", risk_reducing=True)
        return Decision("ADD_DCA", leg.side, notional=proposed, role=leg.role, reason=f"DCA-level {leg.dca_count+1} bereikt")
    return Decision("HOLD", leg.side, role=leg.role, reason="Geen veilige beheeractie nodig")


def apply_fill(leg: LegState, *, fill_notional: float, fill_price: float, fee: float = 0.0) -> LegState:
    if fill_notional <= 0 or fill_price <= 0: raise ValueError("Alleen werkelijk positieve fills mogen state wijzigen")
    total = leg.size + fill_notional
    average = (leg.size * leg.weighted_entry + fill_notional * fill_price) / total
    return replace(leg, size=total, weighted_entry=average, dca_count=leg.dca_count+1, fees=leg.fees+fee, lifecycle="DCA")


def transition(leg: LegState, event: str) -> LegState:
    allowed={
        "IDLE":{"OPEN":"OPENING"},"OPENING":{"FILLED":"HARVEST","UNKNOWN":"RECOVERY"},
        "HARVEST":{"DCA":"DCA","PROTECT":"HARVEST_PROTECTION","TP":"TP_PENDING"},
        "DCA":{"FILLED":"HARVEST","PROTECT":"HARVEST_PROTECTION","UNKNOWN":"RECOVERY"},
        "HARVEST_PROTECTION":{"ESCALATE":"PROTECTION","RELEASE":"HARVEST","TP":"TP_PENDING"},
        "PROTECTION":{"RELEASE":"HARVEST_PROTECTION","REDUCE":"CLOSING"},
        "TP_PENDING":{"CLOSE":"CLOSING","PROTECT":"HARVEST_PROTECTION","UNKNOWN":"RECOVERY"},
        "CLOSING":{"FILLED":"CLOSED","UNKNOWN":"RECOVERY"},"CLOSED":{"RESTART":"OPENING"},
        "RECOVERY":{"RECONCILED":"HARVEST"},
    }
    target=allowed.get(leg.lifecycle,{}).get(event)
    if not target: raise ValueError(f"Ongeldige Strategy-2-transition: {leg.lifecycle} + {event}")
    role="PROTECTION" if target=="PROTECTION" else "HARVEST_PROTECTION" if target=="HARVEST_PROTECTION" else "HARVEST" if target=="HARVEST" else leg.role
    return replace(leg,lifecycle=target,role=role)


def cashflow_adjusted_return(start_equity: float, end_equity: float, deposits: float = 0.0, withdrawals: float = 0.0) -> float:
    if start_equity <= 0: return 0.0
    return (end_equity - deposits + withdrawals - start_equity) / start_equity


def adjusted_high_water_mark(previous: float, equity: float, deposits: float = 0.0, withdrawals: float = 0.0) -> float:
    adjusted_previous = max(0.0, previous + deposits - withdrawals)
    return max(adjusted_previous, equity)


def compounded_return(period_returns: list[float]) -> float:
    product = 1.0
    for value in period_returns: product *= 1 + value
    return product - 1


def validate_worst_case(config: Strategy2Config, equity: float, contract_minimum: float, maximum_leverage: int) -> list[str]:
    errors=[]
    if config.base_notional < contract_minimum: errors.append(f"Minimum order for this contract: ${contract_minimum:.2f}.")
    if config.leverage > maximum_leverage: errors.append(f"Leverage is hoger dan de contractlimiet van {maximum_leverage}x.")
    effective_leverage=max(1,min(config.leverage,maximum_leverage))
    # DCA capacity is not reserved up front. Every real DCA is independently
    # admitted against current exchange equity and current Strategy-2 margin.
    # Normal entries alternate between one LONG and one SHORT opportunity.
    # A same-symbol opposite hedge is added only by Portfolio Protection.
    initial_exposure=config.base_notional
    required_margin=initial_exposure/effective_leverage
    budget=equity*config.strategy_budget
    if required_margin > budget:
        errors.append(f"De eerstvolgende zelfstandige positie gebruikt ${initial_exposure:.2f} geleveragede exposure; geschatte margin bij {effective_leverage}x is ${required_margin:.2f} en is hoger dan het actuele Strategy Margin Budget ${budget:.2f}.")
    return errors
