"""Pure Strategy-2 engine: Dual Profit Harvest DCA + Dynamic Protection.

The module contains no network calls. Paper and live execution consume the
same decisions; only the adapter that applies an Action differs.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal
from statistics import fmean, pstdev
import math
from aster_universe import normalize_top_n
from aster_strategy2_focus import DEFAULT_FOCUS_DCA, MAX_FOCUS_DCA

Side = Literal["LONG", "SHORT"]
Role = Literal["HARVEST", "HARVEST_PROTECTION", "PROTECTION"]
RiskMode = Literal["NORMAL", "CAUTION", "DEFENSIVE", "EMERGENCY"]


@dataclass(frozen=True)
class Strategy2Config:
    strategy_id: str = "aster-strategy-2"
    name: str = "Dual Profit Harvest DCA"
    version: int = 1
    mode: Literal["paper", "live"] = "paper"
    trading_mode: Literal["multi_pair", "focus"] = "multi_pair"
    base_notional: float = 10.0
    take_profit: float = .015
    auto_restart: bool = True
    dca_enabled: bool = True
    trend_bollinger_entry_enabled: bool = False
    dca_mode: Literal["fixed", "progressive", "custom"] = "fixed"
    long_dca_distance: float = .02
    short_dca_distance: float = .02
    long_max_dca: int = 3
    short_max_dca: int = 3
    dca_multiplier: float = 1.0
    long_custom_levels: tuple[float, ...] = ()
    short_custom_levels: tuple[float, ...] = ()
    maximum_pairs: int = 5
    maximum_long_positions: int | None = None
    maximum_short_positions: int | None = None
    minimum_quote_volume_24h_usdt: float = 10_000_000.0
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
    money_grabber_enabled: bool = False
    money_grabber_round_target: float = .05
    money_grabber_auto_close: bool = True
    money_grabber_first_threshold: float = .02
    money_grabber_first_ratio: float = .50
    money_grabber_full_threshold: float = .04
    money_grabber_full_ratio: float = 1.00
    money_grabber_pair_close_enabled: bool = True

    # Focus / Coin van het moment. Defaults are deliberately off/conservative.
    focus_shadow_enabled: bool = False
    focus_selection_mode: Literal["automatic", "manual"] = "automatic"
    focus_manual_pair: str = ""
    focus_sizing_mode: Literal["fixed_usd", "equity_pct"] = "fixed_usd"
    focus_start_order_notional: float = 100.0
    focus_equity_pct: float = .50
    focus_auto_compound: bool = False
    focus_max_start_order_usd: float = 1000.0
    focus_dca_enabled: bool = True
    focus_dca_mode: Literal["fixed", "progressive"] = "fixed"
    focus_dca_distance: float = .02
    focus_dca_notional: float = 100.0
    focus_max_dca: int = DEFAULT_FOCUS_DCA
    focus_dca_multiplier: float = 1.0
    focus_max_budget_usd: float = 1000.0
    focus_trailing_activation_pct: float = .02
    focus_trailing_distance_pct: float = .025
    focus_minimum_profit_pct: float = .015
    focus_partial_tp_enabled: bool = False
    focus_first_partial_tp_pct: float = .05
    focus_first_partial_close_pct: float = .25
    focus_second_partial_tp_pct: float = .10
    focus_second_partial_close_pct: float = .25
    focus_wait_until_flat: bool = False
    focus_min_liquidity_score: float = 0.0

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "Strategy2Config":
        raw = raw or {}
        def f(key: str, default: float) -> float:
            try: value = float(raw.get(key, default))
            except (TypeError, ValueError): value = default
            return value if math.isfinite(value) else default
        def i(key: str, default: int) -> int: return int(f(key, default))
        def money_number(key: str, default: float) -> float:
            if key not in raw: return default
            try: value = float(raw[key])
            except (TypeError, ValueError) as exc: raise ValueError(f"{key} moet een geldig getal zijn") from exc
            if not math.isfinite(value): raise ValueError(f"{key} moet een eindig getal zijn")
            return value
        def levels(key: str) -> tuple[float, ...]:
            values = raw.get(key, ())
            return tuple(float(x) for x in values) if isinstance(values, (list, tuple)) else ()
        value = cls(
            strategy_id=str(raw.get("strategyId", cls.strategy_id)), name=str(raw.get("name", cls.name)),
            version=i("version", 1), mode="live" if raw.get("mode") == "live" else "paper",
            trading_mode="focus" if str(raw.get("tradingMode", "multi_pair")).lower() == "focus" else "multi_pair",
            base_notional=f("baseNotional", 10), take_profit=f("takeProfit", .015),
            auto_restart=bool(raw.get("autoRestart", True)), dca_enabled=bool(raw.get("dcaEnabled", True)),
            trend_bollinger_entry_enabled=bool(raw.get("trendBollingerEntryEnabled", False)),
            dca_mode=str(raw.get("dcaMode", "fixed")).lower(),
            long_dca_distance=f("longDcaDistance", .02), short_dca_distance=f("shortDcaDistance", .02),
            long_max_dca=i("longMaxDca", 3), short_max_dca=i("shortMaxDca", 3),
            dca_multiplier=f("dcaMultiplier", 1), long_custom_levels=levels("longCustomLevels"),
            short_custom_levels=levels("shortCustomLevels"), maximum_pairs=i("maximumPairs", 5),
            maximum_long_positions=(i("maximumLongPositions", 0) if "maximumLongPositions" in raw else None),
            maximum_short_positions=(i("maximumShortPositions", 0) if "maximumShortPositions" in raw else None),
            minimum_quote_volume_24h_usdt=f("minimumQuoteVolume24hUsdt", 10_000_000),
            universe_top_n=normalize_top_n(raw.get("universeTopN", 50)), leverage=i("leverage", 10),
            margin_mode="isolated" if raw.get("marginMode") == "isolated" else "cross",
            strategy_budget=f("strategyBudget", .5), protection_enabled=bool(raw.get("protectionEnabled", True)),
            caution_drawdown=f("cautionDrawdown", .03), defensive_drawdown=f("defensiveDrawdown", .06),
            emergency_drawdown=f("emergencyDrawdown", .10), caution_margin_ratio=f("cautionMarginRatio", .35),
            defensive_margin_ratio=f("defensiveMarginRatio", .50), emergency_margin_ratio=f("emergencyMarginRatio", .70),
            max_protection_ratio=f("maxProtectionRatio", .50), max_net_exposure_ratio=f("maxNetExposureRatio", .30),
            max_gross_exposure_ratio=f("maxGrossExposureRatio", 1.0),
            money_grabber_enabled=bool(raw.get("moneyGrabberEnabled", False)),
            money_grabber_round_target=money_number("moneyGrabberRoundTarget", .05),
            money_grabber_auto_close=bool(raw.get("moneyGrabberAutoClose", True)),
            money_grabber_first_threshold=money_number("moneyGrabberFirstThreshold", .02),
            money_grabber_first_ratio=money_number("moneyGrabberFirstRatio", .50),
            money_grabber_full_threshold=money_number("moneyGrabberFullThreshold", .04),
            money_grabber_full_ratio=money_number("moneyGrabberFullRatio", 1.00),
            money_grabber_pair_close_enabled=bool(raw.get("moneyGrabberPairCloseEnabled", True)),
            focus_shadow_enabled=bool(raw.get("focusShadowEnabled", False)),
            focus_selection_mode="manual" if str(raw.get("focusSelectionMode", "automatic")).lower() == "manual" else "automatic",
            focus_manual_pair=str(raw.get("focusManualPair", "")).upper().strip(),
            focus_sizing_mode="equity_pct" if str(raw.get("focusSizingMode", "fixed_usd")).lower() == "equity_pct" else "fixed_usd",
            focus_start_order_notional=f("focusStartOrderNotional", 100),
            focus_equity_pct=f("focusEquityPct", .50),
            focus_auto_compound=bool(raw.get("focusAutoCompound", False)),
            focus_max_start_order_usd=f("focusMaxStartOrderUsd", 1000),
            focus_dca_enabled=bool(raw.get("focusDcaEnabled", True)),
            focus_dca_mode="progressive" if str(raw.get("focusDcaMode", "fixed")).lower() == "progressive" else "fixed",
            focus_dca_distance=f("focusDcaDistance", .02),
            focus_dca_notional=f("focusDcaNotional", 100),
            focus_max_dca=i("focusMaxDca", DEFAULT_FOCUS_DCA),
            focus_dca_multiplier=f("focusDcaMultiplier", 1.0),
            focus_max_budget_usd=f("focusMaxBudgetUsd", 1000),
            focus_trailing_activation_pct=f("focusTrailingActivationPct", .02),
            focus_trailing_distance_pct=f("focusTrailingDistancePct", .025),
            focus_minimum_profit_pct=f("focusMinimumProfitPct", .015),
            focus_partial_tp_enabled=bool(raw.get("focusPartialTpEnabled", False)),
            focus_first_partial_tp_pct=f("focusFirstPartialTpPct", .05),
            focus_first_partial_close_pct=f("focusFirstPartialClosePct", .25),
            focus_second_partial_tp_pct=f("focusSecondPartialTpPct", .10),
            focus_second_partial_close_pct=f("focusSecondPartialClosePct", .25),
            focus_wait_until_flat=bool(raw.get("focusWaitUntilFlat", False)),
            focus_min_liquidity_score=f("focusMinLiquidityScore", 0.0),
        )
        return value.validated()

    def validated(self) -> "Strategy2Config":
        if self.dca_mode not in {"fixed", "progressive", "custom"}: raise ValueError("Ongeldige DCA-modus")
        if not 1 <= self.base_notional <= 100_000: raise ValueError("Base Order moet tussen 1 en 100.000 USD liggen")
        if not .001 <= self.take_profit <= .20: raise ValueError("Take Profit moet tussen 0,1% en 20% liggen")
        if not 1 <= self.maximum_pairs <= 100: raise ValueError("Max Active Pairs moet tussen 1 en 100 liggen")
        if (self.maximum_long_positions is None) != (self.maximum_short_positions is None): raise ValueError("LONG- en SHORT-stoeldoelen moeten samen worden ingesteld")
        if self.maximum_long_positions is not None:
            if self.maximum_long_positions < 0 or self.maximum_short_positions < 0 or self.maximum_long_positions + self.maximum_short_positions != self.maximum_pairs:
                raise ValueError("LONG + SHORT stoelen moet exact gelijk zijn aan het totale aantal stoelen")
        if not math.isfinite(self.minimum_quote_volume_24h_usdt) or self.minimum_quote_volume_24h_usdt < 0: raise ValueError("Minimum 24h USDT-volume moet nul of hoger zijn")
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
        if not 0 < self.money_grabber_round_target <= .50: raise ValueError("Money Grabber-rondedoel moet tussen 0 en 50% liggen")
        if not 0 < self.money_grabber_first_threshold < self.money_grabber_full_threshold <= .80: raise ValueError("De volledige Money Grabber-beschermingsgrens moet groter zijn dan de eerste grens")
        if not 0 < self.money_grabber_first_ratio <= self.money_grabber_full_ratio <= 1: raise ValueError("De volledige Money Grabber-beschermingsratio mag niet kleiner zijn dan de eerste ratio")
        if self.trading_mode not in {"multi_pair", "focus"}: raise ValueError("Ongeldige Strategy-2 tradingMode")
        if self.focus_selection_mode not in {"automatic", "manual"}: raise ValueError("Ongeldige Focus-selectiemodus")
        if self.focus_selection_mode == "manual" and self.trading_mode == "focus" and not self.focus_manual_pair: raise ValueError("Handmatige Focus-selectie vereist een pair")
        if self.focus_sizing_mode not in {"fixed_usd", "equity_pct"}: raise ValueError("Ongeldige Focus sizing-mode")
        if not 0 < self.focus_start_order_notional <= 1_000_000: raise ValueError("Focus startorder moet positief zijn")
        if not 0 < self.focus_equity_pct <= .90: raise ValueError("Focus equity-percentage moet tussen 0 en 90% liggen")
        if not 0 < self.focus_max_start_order_usd <= 1_000_000: raise ValueError("Focus max startorder moet positief zijn")
        if not 0 <= self.focus_max_dca <= MAX_FOCUS_DCA: raise ValueError(f"Focus max DCA moet tussen 0 en {MAX_FOCUS_DCA} liggen")
        if not 0 < self.focus_dca_distance < 1: raise ValueError("Focus DCA-afstand moet tussen 0 en 100% liggen")
        if not 0 < self.focus_dca_notional <= 1_000_000: raise ValueError("Focus DCA-bedrag moet positief zijn")
        if not 0 < self.focus_dca_multiplier <= 10: raise ValueError("Focus DCA multiplier moet groter dan 0 en maximaal 10 zijn")
        if not 0 < self.focus_max_budget_usd <= 10_000_000: raise ValueError("Focus-budget moet positief zijn")
        if self.focus_start_order_notional > self.focus_max_budget_usd and self.focus_sizing_mode == "fixed_usd": raise ValueError("Focus startorder overschrijdt Focus-budget")
        if not 0 < self.focus_minimum_profit_pct <= .50: raise ValueError("Focus minimum profit moet tussen 0 en 50% liggen")
        if not self.focus_minimum_profit_pct <= self.focus_trailing_activation_pct <= 2.0: raise ValueError("Focus trailing activation moet minimaal minimum profit zijn")
        if not 0 < self.focus_trailing_distance_pct < 1: raise ValueError("Focus trailing distance moet tussen 0 en 100% liggen")
        if not 0 < self.focus_first_partial_tp_pct < self.focus_second_partial_tp_pct <= 2.0: raise ValueError("Focus partial TP-drempels moeten oplopen")
        if not 0 < self.focus_first_partial_close_pct < 1 or not 0 < self.focus_second_partial_close_pct < 1: raise ValueError("Focus partial sluitpercentages moeten tussen 0 en 100% liggen")
        if self.focus_first_partial_close_pct + self.focus_second_partial_close_pct >= 1: raise ValueError("Focus partials moeten ruimte overlaten voor trailing exit")
        if self.focus_min_liquidity_score < 0: raise ValueError("Focus liquidity-score kan niet negatief zijn")
        return self

    @property
    def entry_targets(self) -> tuple[int, int]:
        if self.maximum_long_positions is not None and self.maximum_short_positions is not None:
            return self.maximum_long_positions, self.maximum_short_positions
        return ((self.maximum_pairs + 1) // 2, self.maximum_pairs // 2)

    def public_dict(self) -> dict[str, Any]:
        long_target, short_target = self.entry_targets
        return ({"strategyId":self.strategy_id,"name":self.name,"version":self.version,"mode":self.mode,"tradingMode":self.trading_mode,
            "baseNotional":self.base_notional,"takeProfit":self.take_profit,"autoRestart":self.auto_restart,
            "dcaEnabled":self.dca_enabled,"trendBollingerEntryEnabled":self.trend_bollinger_entry_enabled,
            "dcaMode":self.dca_mode,"longDcaDistance":self.long_dca_distance,
            "shortDcaDistance":self.short_dca_distance,"longMaxDca":self.long_max_dca,"shortMaxDca":self.short_max_dca,
            "dcaMultiplier":self.dca_multiplier,"longCustomLevels":list(self.long_custom_levels),
            "shortCustomLevels":list(self.short_custom_levels),"maximumPairs":self.maximum_pairs,
            "maximumLongPositions":long_target,"maximumShortPositions":short_target,
            "minimumQuoteVolume24hUsdt":self.minimum_quote_volume_24h_usdt,
            "universeTopN":self.universe_top_n,"leverage":self.leverage,"marginMode":self.margin_mode,
            "strategyBudget":self.strategy_budget,"protectionEnabled":self.protection_enabled,
            "cautionDrawdown":self.caution_drawdown,"defensiveDrawdown":self.defensive_drawdown,
            "emergencyDrawdown":self.emergency_drawdown,"cautionMarginRatio":self.caution_margin_ratio,
            "defensiveMarginRatio":self.defensive_margin_ratio,"emergencyMarginRatio":self.emergency_margin_ratio,
            "maxProtectionRatio":self.max_protection_ratio,"maxNetExposureRatio":self.max_net_exposure_ratio,
            "maxGrossExposureRatio":self.max_gross_exposure_ratio,
            "moneyGrabberEnabled":self.money_grabber_enabled,"moneyGrabberRoundTarget":self.money_grabber_round_target,
            "moneyGrabberAutoClose":self.money_grabber_auto_close,"moneyGrabberFirstThreshold":self.money_grabber_first_threshold,
            "moneyGrabberFirstRatio":self.money_grabber_first_ratio,"moneyGrabberFullThreshold":self.money_grabber_full_threshold,
            "moneyGrabberFullRatio":self.money_grabber_full_ratio,"moneyGrabberPairCloseEnabled":self.money_grabber_pair_close_enabled,
            "focusShadowEnabled":self.focus_shadow_enabled,"focusSelectionMode":self.focus_selection_mode,"focusManualPair":self.focus_manual_pair,
            "focusSizingMode":self.focus_sizing_mode,"focusStartOrderNotional":self.focus_start_order_notional,"focusEquityPct":self.focus_equity_pct,
            "focusAutoCompound":self.focus_auto_compound,"focusMaxStartOrderUsd":self.focus_max_start_order_usd,"focusDcaEnabled":self.focus_dca_enabled,
            "focusDcaMode":self.focus_dca_mode,"focusDcaDistance":self.focus_dca_distance,"focusDcaNotional":self.focus_dca_notional,
            "focusMaxDca":self.focus_max_dca,"focusDcaMultiplier":self.focus_dca_multiplier,"focusMaxBudgetUsd":self.focus_max_budget_usd,
            "focusTrailingActivationPct":self.focus_trailing_activation_pct,"focusTrailingDistancePct":self.focus_trailing_distance_pct,
            "focusMinimumProfitPct":self.focus_minimum_profit_pct,"focusPartialTpEnabled":self.focus_partial_tp_enabled,
            "focusFirstPartialTpPct":self.focus_first_partial_tp_pct,"focusFirstPartialClosePct":self.focus_first_partial_close_pct,
            "focusSecondPartialTpPct":self.focus_second_partial_tp_pct,"focusSecondPartialClosePct":self.focus_second_partial_close_pct,
            "focusWaitUntilFlat":self.focus_wait_until_flat,"focusMinLiquidityScore":self.focus_min_liquidity_score})


def _ema(values: list[float], period: int) -> float:
    seed = fmean(values[:period])
    alpha = 2.0 / (period + 1.0)
    result = seed
    for value in values[period:]:
        result = value * alpha + result * (1.0 - alpha)
    return result

def trend_bollinger_entry_check(closes: list[float], price: float, side: Side) -> dict[str, Any] | None:
    values = [float(value) for value in closes if math.isfinite(float(value)) and float(value) > 0]
    if len(values) < 51 or not math.isfinite(price) or price <= 0 or side not in {"LONG", "SHORT"}:
        return None
    ema20, ema50 = _ema(values, 20), _ema(values, 50)
    previous_middle = fmean(values[-21:-1])
    window = values[-20:]
    middle = fmean(window)
    deviation = pstdev(window)
    upper, lower = middle + 2.0 * deviation, middle - 2.0 * deviation
    previous_close, latest_close = values[-2], values[-1]
    trend = "UP" if ema20 > ema50 else "DOWN" if ema20 < ema50 else "NEUTRAL"
    if side == "LONG":
        eligible = trend == "UP" and previous_close <= previous_middle and latest_close > middle
        reason = "uptrend+middle_cross_up"
    else:
        eligible = trend == "DOWN" and previous_close >= previous_middle and latest_close < middle
        reason = "downtrend+middle_cross_down"
    return {"eligible": eligible, "trend": trend, "price": price, "previousClose": previous_close, "latestClose": latest_close, "previousMiddle": previous_middle, "middle": middle, "upper": upper, "lower": lower, "reason": reason}


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
    strategy_margin: float = 0.0
    available_balance: float = 0.0

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
    if not config.protection_enabled or risk_mode(config, portfolio) == "NORMAL": return 0.0
    cap = portfolio.equity * config.max_net_exposure_ratio
    if winning_side == "LONG": return max(0.0, portfolio.short_exposure - cap)
    return max(0.0, portfolio.long_exposure - cap)


def decide_leg(config: Strategy2Config, leg: LegState, portfolio: PortfolioState, *, estimated_close_fee: float = 0.0) -> Decision:
    if not portfolio.exchange_reliable or not portfolio.ownership_reliable or portfolio.open_orders_unknown:
        return Decision("HOLD", leg.side, reason="Exchange-state, ownership of orderstatus is onzeker; geen nieuw risico", risk_reducing=True)
    if tp_due(config, leg, estimated_close_fee):
        return Decision("FULL_TP", leg.side, notional=leg.size, role="HARVEST",
            reason="Netto TP bereikt; winst oogsten heeft prioriteit op protection en risicomodus", risk_reducing=True)
    if dca_due(config, leg):
        proposed = config.base_notional * config.dca_multiplier
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
    initial_exposure=config.base_notional
    required_margin=initial_exposure/effective_leverage
    budget=equity*config.strategy_budget
    if required_margin > budget:
        errors.append(f"De eerstvolgende zelfstandige positie gebruikt ${initial_exposure:.2f} geleveragede exposure; geschatte margin bij {effective_leverage}x is ${required_margin:.2f} en is hoger dan het actuele Strategy Margin Budget ${budget:.2f}.")
    return errors
