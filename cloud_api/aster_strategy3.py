"""Pure paper-first Strategy-3 engine: Dual Harvest Adaptive Shield.

This module deliberately has no exchange or network adapter.  Strategy 3 is
not allowed to place live orders until a later, explicit release gate.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal
import math
from aster_universe import normalize_top_n

Side = Literal["LONG", "SHORT"]
Role = Literal["HARVEST", "HARVEST_PROTECTION", "PROTECTION"]
RiskMode = Literal["NORMAL", "CAUTION", "DEFENSIVE", "EMERGENCY"]


def account_entry_side(active_keys:set[tuple[str,str]],maximum_positions:int)->Side|None:
    """Apply Strategy 3's configured ceiling to the complete Aster account."""
    active={(str(symbol).upper(),str(side).upper()) for symbol,side in active_keys
        if str(symbol) and str(side).upper() in {"LONG","SHORT"}}
    if len(active)>=maximum_positions:
        return None
    long_count=sum(1 for _,side in active if side=="LONG")
    short_count=sum(1 for _,side in active if side=="SHORT")
    return "LONG" if long_count<=short_count else "SHORT"


def account_canary_proven(state:dict[str,Any],canary:dict[str,Any])->bool:
    """Only a persisted completed account canary may authorize live runtime."""
    del state
    return str(canary.get("status","")).upper()=="COMPLETED"


def persisted_runtime_mode(raw:dict[str,Any],canary:dict[str,Any])->Literal["paper","live"]:
    """Restore live only for trusted persisted state with current canary proof."""
    return "live" if str(raw.get("mode","")).lower()=="live" and account_canary_proven({},canary) else "paper"


@dataclass(frozen=True)
class Strategy3Config:
    strategy_id: str = "aster-strategy-3"
    name: str = "Dual Harvest Adaptive Shield"
    version: int = 1
    mode: Literal["paper", "live"] = "paper"
    base_notional: float = 10.0
    take_profit: float = .015
    auto_restart: bool = True
    dca_enabled: bool = True
    long_dca_distance: float = .02
    short_dca_distance: float = .02
    long_max_dca: int = 5
    short_max_dca: int = 5
    dca_multiplier: float = 1.0
    maximum_positions: int = 20
    universe_top_n: int = 100
    leverage: int = 20
    margin_mode: Literal["cross", "isolated"] = "cross"
    strategy_budget: float = .35
    protection_enabled: bool = True
    caution_drawdown: float = .03
    defensive_drawdown: float = .06
    emergency_drawdown: float = .10
    caution_margin_ratio: float = .35
    defensive_margin_ratio: float = .50
    emergency_margin_ratio: float = .70
    max_net_exposure_ratio: float = .30
    trailing_enabled: bool = False
    trailing_activation: float = .015
    trailing_distance: float = .005
    trailing_min_net_profit: float = .003
    long_trailing_distance: float | None = None
    short_trailing_distance: float | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "Strategy3Config":
        raw = raw or {}
        def f(key: str, default: float) -> float:
            try: value = float(raw.get(key, default))
            except (TypeError, ValueError): value = default
            return value if math.isfinite(value) else default
        def optional(key: str) -> float | None:
            value = raw.get(key)
            if value in (None, ""): return None
            try: parsed = float(value)
            except (TypeError, ValueError): return None
            return parsed if math.isfinite(parsed) else None
        value = cls(
            strategy_id=str(raw.get("strategyId", cls.strategy_id)),
            name=str(raw.get("name", cls.name)), version=int(f("version", 1)),
            # User/config payloads can never open the live gate. Only the
            # authenticated start route may replace this immutable value.
            mode="paper",
            base_notional=f("baseNotional", 10), take_profit=f("takeProfit", .015),
            auto_restart=bool(raw.get("autoRestart", True)), dca_enabled=bool(raw.get("dcaEnabled", True)),
            long_dca_distance=f("longDcaDistance", .02), short_dca_distance=f("shortDcaDistance", .02),
            long_max_dca=int(f("longMaxDca", 5)), short_max_dca=int(f("shortMaxDca", 5)),
            dca_multiplier=f("dcaMultiplier", 1), maximum_positions=int(f("maximumPositions", 20)),
            universe_top_n=normalize_top_n(raw.get("universeTopN", 100)), leverage=int(f("leverage", 20)),
            margin_mode="isolated" if raw.get("marginMode") == "isolated" else "cross",
            strategy_budget=f("strategyBudget", .35), protection_enabled=bool(raw.get("protectionEnabled", True)),
            caution_drawdown=f("cautionDrawdown", .03), defensive_drawdown=f("defensiveDrawdown", .06),
            emergency_drawdown=f("emergencyDrawdown", .10), caution_margin_ratio=f("cautionMarginRatio", .35),
            defensive_margin_ratio=f("defensiveMarginRatio", .50), emergency_margin_ratio=f("emergencyMarginRatio", .70),
            max_net_exposure_ratio=f("maxNetExposureRatio", .30), trailing_enabled=bool(raw.get("trailingEnabled", False)),
            trailing_activation=f("trailingActivation", .015), trailing_distance=f("trailingDistance", .005),
            trailing_min_net_profit=f("trailingMinNetProfit", .003),
            long_trailing_distance=optional("longTrailingDistance"), short_trailing_distance=optional("shortTrailingDistance"),
        )
        return value.validated()

    def validated(self) -> "Strategy3Config":
        if not 1 <= self.base_notional <= 100_000: raise ValueError("Basisorder moet tussen US$ 1 en US$ 100.000 liggen")
        if not .001 <= self.take_profit <= .20: raise ValueError("Take Profit moet tussen 0,1% en 20% liggen")
        if not 1 <= self.maximum_positions <= 200: raise ValueError("Aantal posities moet tussen 1 en 200 liggen")
        if self.universe_top_n < 1: raise ValueError("Aster USDT Top-N moet een positief geheel getal zijn")
        if not 1 <= self.leverage <= 200: raise ValueError("Leverage moet tussen 1x en 200x liggen")
        if not 0 <= self.long_max_dca <= 50 or not 0 <= self.short_max_dca <= 50: raise ValueError("DCA-limiet moet tussen 0 en 50 liggen")
        if not 0 < self.long_dca_distance <= .80 or not 0 < self.short_dca_distance <= .80: raise ValueError("DCA-afstand moet tussen 0 en 80% liggen")
        if not 0 < self.strategy_budget <= .90: raise ValueError("Strategy Budget moet tussen 0 en 90% liggen")
        if not 0 < self.caution_drawdown < self.defensive_drawdown < self.emergency_drawdown < 1: raise ValueError("Drawdown-drempels moeten oplopen")
        if not 0 < self.caution_margin_ratio < self.defensive_margin_ratio < self.emergency_margin_ratio < 1: raise ValueError("Margin-drempels moeten oplopen")
        if not .001 <= self.trailing_distance <= .10: raise ValueError("Trailing-afstand moet tussen 0,1% en 10% liggen")
        if self.trailing_activation < self.take_profit: raise ValueError("Trailing-activatie mag niet onder Take Profit liggen")
        if not 0 <= self.trailing_min_net_profit < self.trailing_activation: raise ValueError("Minimale trailingwinst moet onder de activatie liggen")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {"strategyId":self.strategy_id,"name":self.name,"version":self.version,"mode":self.mode,
            "baseNotional":self.base_notional,"takeProfit":self.take_profit,"autoRestart":self.auto_restart,
            "dcaEnabled":self.dca_enabled,"longDcaDistance":self.long_dca_distance,"shortDcaDistance":self.short_dca_distance,
            "longMaxDca":self.long_max_dca,"shortMaxDca":self.short_max_dca,"dcaMultiplier":self.dca_multiplier,
            "maximumPositions":self.maximum_positions,"universeTopN":self.universe_top_n,"leverage":self.leverage,
            "marginMode":self.margin_mode,"strategyBudget":self.strategy_budget,"protectionEnabled":self.protection_enabled,
            "cautionDrawdown":self.caution_drawdown,"defensiveDrawdown":self.defensive_drawdown,
            "emergencyDrawdown":self.emergency_drawdown,"cautionMarginRatio":self.caution_margin_ratio,
            "defensiveMarginRatio":self.defensive_margin_ratio,"emergencyMarginRatio":self.emergency_margin_ratio,
            "maxNetExposureRatio":self.max_net_exposure_ratio,"trailingEnabled":self.trailing_enabled,
            "trailingActivation":self.trailing_activation,"trailingDistance":self.trailing_distance,
            "trailingMinNetProfit":self.trailing_min_net_profit,"longTrailingDistance":self.long_trailing_distance,
            "shortTrailingDistance":self.short_trailing_distance}


@dataclass(frozen=True)
class LegState:
    side: Side
    size: float
    weighted_entry: float
    current_price: float
    dca_count: int = 0
    unrealized_pnl: float = 0.0
    fees: float = 0.0
    funding: float = 0.0
    role: Role = "HARVEST"
    trailing_peak_return: float | None = None


@dataclass(frozen=True)
class PortfolioState:
    equity: float
    high_water_mark: float
    margin_ratio: float
    long_exposure: float
    short_exposure: float
    strategy_margin: float = 0.0
    exchange_reliable: bool = True
    ownership_reliable: bool = True
    open_orders_unknown: bool = False

    @property
    def drawdown(self) -> float:
        return max(0.0, 1-self.equity/self.high_water_mark) if self.high_water_mark > 0 else 0.0


@dataclass(frozen=True)
class Decision:
    kind: str
    side: Side
    notional: float = 0.0
    retain_notional: float = 0.0
    role: Role = "HARVEST"
    reason: str = ""


def risk_mode(config: Strategy3Config, portfolio: PortfolioState) -> RiskMode:
    if portfolio.margin_ratio >= config.emergency_margin_ratio or portfolio.drawdown >= config.emergency_drawdown: return "EMERGENCY"
    if portfolio.margin_ratio >= config.defensive_margin_ratio or portfolio.drawdown >= config.defensive_drawdown: return "DEFENSIVE"
    if portfolio.margin_ratio >= config.caution_margin_ratio or portfolio.drawdown >= config.caution_drawdown: return "CAUTION"
    return "NORMAL"


def net_return(leg: LegState, close_fee: float = 0.0) -> float:
    return (leg.unrealized_pnl + leg.funding - leg.fees - close_fee) / leg.size if leg.size > 0 else 0.0


def protection_required(config: Strategy3Config, portfolio: PortfolioState, side: Side) -> float:
    if not config.protection_enabled or risk_mode(config, portfolio) == "NORMAL": return 0.0
    cap = portfolio.equity * config.max_net_exposure_ratio
    return max(0.0, (portfolio.short_exposure if side == "LONG" else portfolio.long_exposure) - cap)


def trailing_distance(config: Strategy3Config, side: Side) -> float:
    custom = config.long_trailing_distance if side == "LONG" else config.short_trailing_distance
    return custom if custom is not None else config.trailing_distance


def decide(config: Strategy3Config, leg: LegState, portfolio: PortfolioState, close_fee: float = 0.0) -> Decision:
    if not portfolio.exchange_reliable or not portfolio.ownership_reliable or portfolio.open_orders_unknown:
        return Decision("HOLD", leg.side, role=leg.role, reason="Onzekere exchange-state of ownership; geen nieuw risico")
    mode = risk_mode(config, portfolio)
    result = net_return(leg, close_fee)
    retain = min(leg.size, protection_required(config, portfolio, leg.side))
    # Protection always outranks fixed TP and trailing.
    if retain >= leg.size - 1e-9 and result >= config.take_profit:
        return Decision("ASSIGN_PROTECTION", leg.side, retain_notional=leg.size, role="PROTECTION", reason=f"Winstdoel bereikt, maar {mode} vereist volledige bescherming")
    if retain > 0 and result >= config.take_profit:
        return Decision("PARTIAL_TP", leg.side, notional=leg.size-retain, retain_notional=retain, role="HARVEST_PROTECTION", reason="Veilig winstdeel sluiten; dynamisch berekend restant beschermt de andere zijde")
    trailing_was_armed = leg.trailing_peak_return is not None and leg.trailing_peak_return >= config.trailing_activation
    if config.trailing_enabled and (result >= config.trailing_activation or trailing_was_armed):
        peak = max(result, leg.trailing_peak_return or result)
        if result <= peak-trailing_distance(config, leg.side) and result >= config.trailing_min_net_profit:
            return Decision("TRAILING_TP", leg.side, notional=leg.size, role="HARVEST", reason="Protected trailing is teruggevallen tot de ingestelde afstand")
        return Decision("ARM_TRAILING", leg.side, role=leg.role, reason="Trailing actief; bescherming blijft leidend")
    if result >= config.take_profit:
        return Decision("FULL_TP", leg.side, notional=leg.size, role="HARVEST", reason="Netto TP bereikt en bescherming is niet nodig")
    if mode in {"DEFENSIVE", "EMERGENCY"}: return Decision("HOLD", leg.side, role=leg.role, reason=f"{mode}: DCA en nieuwe exposure geblokkeerd")
    distance = config.long_dca_distance if leg.side == "LONG" else config.short_dca_distance
    maximum = config.long_max_dca if leg.side == "LONG" else config.short_max_dca
    adverse = leg.current_price <= leg.weighted_entry*(1-distance*(leg.dca_count+1)) if leg.side == "LONG" else leg.current_price >= leg.weighted_entry*(1+distance*(leg.dca_count+1))
    proposed = config.base_notional*config.dca_multiplier
    if config.dca_enabled and adverse and leg.dca_count < maximum:
        if portfolio.strategy_margin + proposed/max(1, config.leverage) > portfolio.equity*config.strategy_budget:
            return Decision("HOLD", leg.side, role=leg.role, reason="DCA geblokkeerd door eigen Strategy-3-budget")
        return Decision("ADD_DCA", leg.side, notional=proposed, role=leg.role, reason=f"Strategy-3 DCA {leg.dca_count+1}")
    return Decision("HOLD", leg.side, role=leg.role, reason="Geen veilige actie nodig")


def update_trailing_peak(leg: LegState, current_return: float) -> LegState:
    return replace(leg, trailing_peak_return=max(current_return, leg.trailing_peak_return or current_return))
