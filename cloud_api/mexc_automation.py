"""Pure decision engine for TradeMentor's MEXC BTC adaptive strategy.

This module has no network, Firestore or order side effects.  Production calls
it with exchange snapshots; tests can therefore cover every transition without
placing a real order.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
import math


FIXED_LEVERAGE = 200
FIXED_MARGIN_MODE = "cross"
ALLOWED_EXECUTION_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h"}
ALLOWED_RISK_TIMEFRAMES = {"5m", "15m", "30m", "1h", "4h"}


@dataclass(frozen=True)
class AutoSettings:
    execution_timeframe: str = "1m"
    risk_timeframe: str = "15m"
    initial_long_ratio: float = 0.0625
    max_long_ratio: float = 6.25
    dca_ratios: tuple[float, ...] = (.075, .10, .125, .1875, .25, .375, .50)
    minimum_spacing: float = .005
    atr_multiplier: float = .75
    cooldown_seconds: int = 180
    take_profit: float = .005
    minimum_net_profit: float = .002
    hedge_enabled: bool = True
    hedge_drawdown_trigger: float = .075
    risk_trigger: int = 80
    recovery_steps: tuple[int, ...] = (40, 55, 70, 85)
    initial_hedge_ratio: float = .50
    max_hedge_ratio: float = 1.0
    minimum_equity_reserve: float = .50
    maximum_session_drawdown: float = .20
    maximum_margin_usage: float = .35
    maximum_margin_ratio: float = .60
    minimum_liquidation_distance: float = .08
    pause_dca_while_hedged: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "AutoSettings":
        raw = value or {}
        aliases = {
            "executionTimeframe": "execution_timeframe", "riskTimeframe": "risk_timeframe",
            "initialLongRatio": "initial_long_ratio", "maxLongRatio": "max_long_ratio",
            "dcaRatios": "dca_ratios", "minimumSpacing": "minimum_spacing",
            "atrMultiplier": "atr_multiplier", "cooldownSeconds": "cooldown_seconds",
            "takeProfit": "take_profit", "minimumNetProfit": "minimum_net_profit",
            "hedgeEnabled": "hedge_enabled", "hedgeDrawdownTrigger": "hedge_drawdown_trigger",
            "riskTrigger": "risk_trigger", "initialHedgeRatio": "initial_hedge_ratio",
            "maxHedgeRatio": "max_hedge_ratio", "minimumEquityReserve": "minimum_equity_reserve",
            "maximumSessionDrawdown": "maximum_session_drawdown",
            "maximumMarginUsage": "maximum_margin_usage",
            "maximumMarginRatio": "maximum_margin_ratio",
            "minimumLiquidationDistance": "minimum_liquidation_distance",
            "pauseDcaWhileHedged": "pause_dca_while_hedged",
        }
        translated = {aliases.get(key, key): item for key, item in raw.items()}
        if "recovery_steps" not in translated:
            values = [translated.pop(f"recoveryStep{i}", None) for i in range(1, 5)]
            if all(item is not None for item in values):
                translated["recovery_steps"] = tuple(int(item) for item in values)
        if "dca_ratios" in translated:
            translated["dca_ratios"] = tuple(float(item) for item in translated["dca_ratios"])
        if "recovery_steps" in translated:
            translated["recovery_steps"] = tuple(int(item) for item in translated["recovery_steps"])
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: item for key, item in translated.items() if key in allowed})

    def validate(self) -> list[str]:
        errors: list[str] = []
        numeric_values = (
            self.initial_long_ratio, self.max_long_ratio, *self.dca_ratios,
            self.minimum_spacing, self.atr_multiplier, self.take_profit,
            self.minimum_net_profit, self.hedge_drawdown_trigger,
            self.initial_hedge_ratio, self.max_hedge_ratio,
            self.minimum_equity_reserve, self.maximum_session_drawdown,
            self.maximum_margin_usage, self.maximum_margin_ratio,
            self.minimum_liquidation_distance,
        )
        if any(not math.isfinite(float(item)) for item in numeric_values):
            errors.append("Instellingen bevatten een ongeldig getal")
        if self.execution_timeframe not in ALLOWED_EXECUTION_TIMEFRAMES:
            errors.append("Niet-ondersteund execution-timeframe")
        if self.risk_timeframe not in ALLOWED_RISK_TIMEFRAMES:
            errors.append("Niet-ondersteund risk-timeframe")
        if not .001 <= self.initial_long_ratio <= 1:
            errors.append("Eerste Long-ratio is ongeldig")
        if self.max_long_ratio < self.initial_long_ratio or self.max_long_ratio > 10:
            errors.append("Max Long-ratio is ongeldig")
        if not self.dca_ratios or any(item <= 0 or item > 2 for item in self.dca_ratios):
            errors.append("DCA-ladder is ongeldig")
        if not .0001 <= self.minimum_spacing <= .50:
            errors.append("Minimale DCA-afstand is ongeldig")
        if not 0 <= self.atr_multiplier <= 10:
            errors.append("ATR-multiplier is ongeldig")
        if not 0 <= self.cooldown_seconds <= 86_400:
            errors.append("Cooldown is ongeldig")
        if not .0001 <= self.take_profit <= .50:
            errors.append("Take-profit is ongeldig")
        if not 0 <= self.minimum_net_profit <= .50:
            errors.append("Minimaal nettoresultaat is ongeldig")
        if not .001 <= self.hedge_drawdown_trigger <= .50:
            errors.append("Hedge-drawdowntrigger is ongeldig")
        if not 1 <= self.risk_trigger <= 100:
            errors.append("Risk-scoretrigger is ongeldig")
        if not 0 <= self.initial_hedge_ratio <= self.max_hedge_ratio <= 1:
            errors.append("Hedge-ratio is ongeldig")
        if (tuple(sorted(self.recovery_steps)) != self.recovery_steps or len(self.recovery_steps) != 4
                or any(item < 0 or item > 100 for item in self.recovery_steps)):
            errors.append("Recovery-drempels moeten vier oplopende waarden bevatten")
        if not .10 <= self.minimum_equity_reserve <= .95:
            errors.append("Equityreserve is ongeldig")
        if not .01 <= self.maximum_session_drawdown <= .50:
            errors.append("Maximale sessiedrawdown is ongeldig")
        if not .01 <= self.maximum_margin_usage <= .80:
            errors.append("Maximale marginbelasting is ongeldig")
        if not .05 <= self.maximum_margin_ratio < 1:
            errors.append("Maximale margin ratio is ongeldig")
        if not .01 <= self.minimum_liquidation_distance <= .90:
            errors.append("Minimale liquidatieafstand is ongeldig")
        return errors

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.update({"leverage": FIXED_LEVERAGE, "marginMode": FIXED_MARGIN_MODE})
        return value


@dataclass(frozen=True)
class AutoState:
    session_start_equity: float
    dca_count: int = 0
    last_dca_price: float = 0.0
    last_order_time: int = 0
    phase: str = "WAIT"
    cycle: int = 1


@dataclass(frozen=True)
class MarketSignal:
    timestamp: int
    price: float
    atr_percent: float
    lower_low: bool
    risk_score: int
    recovery_score: int


@dataclass(frozen=True)
class AccountSnapshot:
    current_equity: float
    available_equity: float
    long_notional: float = 0.0
    short_notional: float = 0.0
    weighted_long_entry: float = 0.0
    weighted_short_entry: float = 0.0
    margin_used: float = 0.0
    margin_ratio: float = 0.0
    liquidation_distance: float = 1.0
    net_session_pnl: float = 0.0

    @property
    def gross_notional(self) -> float:
        return self.long_notional + self.short_notional

    @property
    def hedge_ratio(self) -> float:
        return self.short_notional / self.long_notional if self.long_notional > 0 else 0.0


@dataclass(frozen=True)
class AutoAction:
    kind: str
    target_notional: float = 0.0
    reason: str = ""
    safety: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderLeg:
    side_code: int
    volume: float
    position_id: int | None
    label: str


def _volume_for_notional(notional: float, price: float, contract: dict[str, Any]) -> float:
    size = float(contract.get("contractSize", 0) or 0)
    minimum = float(contract.get("minVol", 0) or 0)
    step = float(contract.get("volUnit", 0) or 1)
    if notional <= 0 or price <= 0 or size <= 0 or minimum <= 0 or step <= 0:
        raise ValueError("ORDER BELOW EXCHANGE MINIMUM")
    volume = math.floor((notional / (price * size)) / step) * step
    if volume + 1e-12 < minimum:
        raise ValueError("ORDER BELOW EXCHANGE MINIMUM")
    return volume


def plan_order_legs(action: AutoAction, positions: list[dict[str, Any]], contract: dict[str, Any], price: float) -> list[OrderLeg]:
    """Translate one decision into documented MEXC hedge-mode side codes."""
    long = next((item for item in positions if item.get("side") == "long"), None)
    short = next((item for item in positions if item.get("side") == "short"), None)
    legs: list[OrderLeg] = []
    if action.kind in {"OPEN_LONG", "ADD_LONG"}:
        legs.append(OrderLeg(1, _volume_for_notional(action.target_notional, price, contract), None, "long"))
    elif action.kind == "SET_HEDGE":
        current = float((short or {}).get("notionalUsd", 0) or 0)
        if action.target_notional > current:
            legs.append(OrderLeg(3, _volume_for_notional(action.target_notional - current, price, contract), None, "open-short"))
        elif short and action.target_notional < current:
            volume = float(short.get("volume", 0) or 0) if action.target_notional <= 0 else _volume_for_notional(current - action.target_notional, price, contract)
            legs.append(OrderLeg(2, volume, int(float(short.get("positionId", 0) or 0)) or None, "reduce-short"))
    elif action.kind == "CLOSE_SHORT" and short:
        legs.append(OrderLeg(2, float(short.get("volume", 0) or 0), int(float(short.get("positionId", 0) or 0)) or None, "close-short"))
    elif action.kind == "CLOSE_ALL":
        if short:
            legs.append(OrderLeg(2, float(short.get("volume", 0) or 0), int(float(short.get("positionId", 0) or 0)) or None, "close-short"))
        if long:
            legs.append(OrderLeg(4, float(long.get("volume", 0) or 0), int(float(long.get("positionId", 0) or 0)) or None, "close-long"))
    return [item for item in legs if item.volume > 0]


def initial_notional(settings: AutoSettings, start_equity: float) -> float:
    return start_equity * settings.initial_long_ratio


def maximum_long(settings: AutoSettings, start_equity: float) -> float:
    strategy_limit = start_equity * settings.max_long_ratio
    reserve_limit = start_equity * (1 - settings.minimum_equity_reserve) * FIXED_LEVERAGE
    return min(strategy_limit, reserve_limit)


def available_increase_limit(account: AccountSnapshot) -> float:
    """Leave a 10% exchange buffer when converting free Cross margin to notional."""
    return max(0.0, account.available_equity) * FIXED_LEVERAGE * .90


def decide(settings: AutoSettings, state: AutoState, account: AccountSnapshot, signal: MarketSignal) -> AutoAction:
    if errors := settings.validate():
        return AutoAction("PAUSE", reason="; ".join(errors), safety=True)
    if state.session_start_equity <= 0 or account.current_equity <= 0 or signal.price <= 0:
        return AutoAction("PAUSE", reason="Account- of marktdata ontbreekt", safety=True)

    drawdown = max(0.0, (state.session_start_equity - account.current_equity) / state.session_start_equity)
    margin_usage = account.margin_used / account.current_equity if account.current_equity > 0 else 1.0
    if account.margin_ratio >= settings.maximum_margin_ratio:
        return AutoAction("CLOSE_ALL", reason="Absolute safety: margin ratio", safety=True)
    if account.liquidation_distance < settings.minimum_liquidation_distance:
        return AutoAction("CLOSE_ALL", reason="Absolute safety: liquidatieafstand", safety=True)
    if drawdown >= settings.maximum_session_drawdown:
        return AutoAction("CLOSE_ALL", reason="Absolute safety: maximale sessiedrawdown", safety=True)
    if margin_usage >= settings.maximum_margin_usage:
        return AutoAction("CLOSE_ALL", reason="Absolute safety: maximale marginbelasting", safety=True)

    if account.long_notional <= 0:
        if account.short_notional > 0:
            return AutoAction("CLOSE_SHORT", target_notional=0.0, reason="Weeshedge zonder Long sluiten", safety=True)
        target = min(initial_notional(settings, state.session_start_equity), available_increase_limit(account))
        if target <= 0:
            return AutoAction("PAUSE", reason="Geen vrije Cross-marge voor eerste Long", safety=True)
        return AutoAction("OPEN_LONG", target, "Nieuwe sessie")

    target_price = account.weighted_long_entry * (1 + settings.take_profit)
    if signal.price >= target_price and account.net_session_pnl >= state.session_start_equity * settings.minimum_net_profit:
        return AutoAction("CLOSE_ALL", reason="Prijsdoel en netto sessiewinst bereikt")

    bearish = drawdown >= settings.hedge_drawdown_trigger or signal.risk_score >= settings.risk_trigger
    hedge_cooled_down = signal.timestamp - state.last_order_time >= settings.cooldown_seconds
    if settings.hedge_enabled and bearish:
        target = account.long_notional * min(settings.initial_hedge_ratio, settings.max_hedge_ratio)
        if hedge_cooled_down and abs(target - account.short_notional) / max(account.long_notional, 1.0) >= .01:
            if target > account.short_notional:
                maximum_target = account.short_notional + available_increase_limit(account)
                if maximum_target <= account.short_notional:
                    return AutoAction("CLOSE_ALL", reason="Absolute safety: hedge kan niet worden gefinancierd", safety=True)
                target = min(target, maximum_target)
            return AutoAction("SET_HEDGE", target, "Drawdown/riskbescherming", metadata={"riskScore": signal.risk_score})

    if account.short_notional > 0:
        r1, r2, r3, r4 = settings.recovery_steps
        ratio = 0.0 if signal.recovery_score >= r4 else .125 if signal.recovery_score >= r3 else .25 if signal.recovery_score >= r2 else .375 if signal.recovery_score >= r1 else settings.initial_hedge_ratio
        target = account.long_notional * min(ratio, settings.max_hedge_ratio)
        if hedge_cooled_down and abs(target - account.short_notional) / max(account.long_notional, 1.0) >= .01:
            return AutoAction("SET_HEDGE", target, "Gecontroleerde hedge-afbouw", metadata={"recoveryScore": signal.recovery_score})
        if settings.pause_dca_while_hedged:
            return AutoAction("HOLD", reason="Protection active; DCA gepauzeerd")

    if state.dca_count >= len(settings.dca_ratios):
        return AutoAction("HOLD", reason="DCA-ladder volledig gebruikt")
    spacing = max(settings.minimum_spacing, signal.atr_percent * settings.atr_multiplier)
    anchor = state.last_dca_price or account.weighted_long_entry
    cooled_down = signal.timestamp - state.last_order_time >= settings.cooldown_seconds
    if signal.lower_low and cooled_down and signal.price <= anchor * (1 - spacing):
        requested = min(
            state.session_start_equity * settings.dca_ratios[state.dca_count],
            available_increase_limit(account),
        )
        allowed = max(0.0, maximum_long(settings, state.session_start_equity) - account.long_notional)
        if allowed > 0 and requested > 0:
            return AutoAction("ADD_LONG", min(requested, allowed), f"DCA {state.dca_count + 1}", metadata={"spacing": spacing})
    return AutoAction("HOLD", reason="Geen bevestigde actie")


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2.0 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = value * k + result * (1 - k)
    return result


def rsi(values: list[float], period: int = 14) -> float:
    changes = list(zip(values, values[1:]))[-period:]
    if not changes:
        return 50.0
    gain = sum(max(0.0, b - a) for a, b in changes) / len(changes)
    loss = sum(max(0.0, a - b) for a, b in changes) / len(changes)
    return 100.0 if loss == 0 else 100.0 - 100.0 / (1 + gain / loss)


def signal_from_candles(execution: list[dict[str, float]], risk: list[dict[str, float]]) -> MarketSignal:
    if len(execution) < 2 or len(risk) < 14:
        raise ValueError("Onvoldoende afgeronde candles")
    current, previous_execution = execution[-1], execution[-2]
    recent = execution[-15:]
    ranges = [max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"])) for p, c in zip(recent, recent[1:])]
    atr_percent = (sum(ranges) / len(ranges) / current["close"]) if ranges and current["close"] else 0.0
    window = risk[-50:]
    closes = [item["close"] for item in window]
    last, previous = window[-1], window[-2]
    e9, e21, e50, strength = ema(closes, 9), ema(closes, 21), ema(closes, 50), rsi(closes)
    volumes = [item["volume"] for item in window[-21:-1]]
    average_volume = sum(volumes) / len(volumes) if volumes else last["volume"]
    momentum = last["close"] / closes[-4] - 1 if len(closes) >= 4 and closes[-4] else 0.0
    risk_score = (30 if e9 < e21 < e50 else 18 if e9 < e21 else 0) + (22 if strength < 35 else 12 if strength < 45 else 0)
    risk_score += 14 if momentum < 0 else 0
    risk_score += 8 if last["low"] < previous["low"] else 0
    risk_score += 6 if last["high"] < previous["high"] else 0
    risk_score += 8 if last["close"] < last["open"] else 0
    risk_score += 12 if last["volume"] > average_volume * 1.25 and last["close"] < last["open"] else 0
    recovery = (30 if e9 > e21 > e50 else 18 if e9 > e21 else 0) + (20 if strength > 60 else 12 if strength > 50 else 0)
    recovery += 16 if momentum > 0 else 0
    recovery += 10 if last["low"] > previous["low"] else 0
    recovery += 8 if last["high"] > previous["high"] else 0
    recovery += 8 if last["close"] > last["open"] else 0
    recovery += 8 if last["volume"] > average_volume * 1.25 and last["close"] > last["open"] else 0
    return MarketSignal(int(current["time"]), current["close"], atr_percent, current["low"] < previous_execution["low"], min(100, risk_score), min(100, recovery))
