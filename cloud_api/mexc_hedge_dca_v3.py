"""Pure Test-3 Hedge DCA decision engine.

The module deliberately contains no HTTP, Firestore or exchange side effects.
It models LONG and SHORT as independent logical cycles and emits at most one
idempotent action per tick.  Production may consume the actions only after the
paper scenarios in ``test_mexc_hedge_dca_v3.py`` pass.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal
import math


StrategyMode = Literal["paper", "live"]
CycleState = Literal[
    "NORMAL", "DCA_ACTIVE", "TP_RESET", "EMERGENCY_TRIGGERED",
    "HEDGE_EXECUTING", "FROZEN_HEDGE", "RESCUE_ACTIVE", "RESCUE_WAIT",
    "SAFE_WAIT", "API_ERROR", "USER_PAUSED",
]


@dataclass(frozen=True)
class V3Settings:
    strategy_version: str = "hedge_dca_v3"
    mode: StrategyMode = "paper"
    symbol: str = "BTC_USDT"
    leverage: int = 200
    margin_mode: str = "cross"
    initial_order_notional: float = 70.0
    take_profit: float = .005
    maximum_dca_orders: int = 40
    dca_timeframe: str = "3m"
    dca_spacing: float = .005
    hedge_enabled: bool = True
    emergency_hedge_enabled: bool = True
    emergency_equity_trigger: float = 95.0
    emergency_hedge_ratio: float = 1.0
    rescue_enabled: bool = True
    rescue_order_notional: float = 10.0
    rescue_take_profit: float = .005
    max_frozen_cycles: int = 1
    classic_stop_loss: bool = False
    minimum_available_buffer: float = 10.0
    maximum_margin_ratio: float = .60
    minimum_liquidation_distance: float = .08
    slippage_tolerance: float = .001
    assumed_taker_fee: float = .0004
    api_retry_limit: int = 2
    rescue_requires_independent_account: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "V3Settings":
        raw = value or {}
        aliases = {
            "strategyVersion": "strategy_version", "initialOrderNotional": "initial_order_notional",
            "takeProfit": "take_profit", "maximumDcaOrders": "maximum_dca_orders",
            "dcaTimeframe": "dca_timeframe", "dcaSpacing": "dca_spacing",
            "hedgeEnabled": "hedge_enabled", "emergencyHedgeEnabled": "emergency_hedge_enabled",
            "emergencyEquityTrigger": "emergency_equity_trigger",
            "emergencyHedgeRatio": "emergency_hedge_ratio", "rescueEnabled": "rescue_enabled",
            "rescueOrderNotional": "rescue_order_notional", "rescueTakeProfit": "rescue_take_profit",
            "maxFrozenCycles": "max_frozen_cycles", "classicStopLoss": "classic_stop_loss",
            "minimumAvailableBuffer": "minimum_available_buffer",
            "maximumMarginRatio": "maximum_margin_ratio",
            "minimumLiquidationDistance": "minimum_liquidation_distance",
            "slippageTolerance": "slippage_tolerance", "assumedTakerFee": "assumed_taker_fee",
            "apiRetryLimit": "api_retry_limit",
            "rescueRequiresIndependentAccount": "rescue_requires_independent_account",
            "marginMode": "margin_mode", "tradingPair": "symbol",
        }
        translated = {aliases.get(key, key): item for key, item in raw.items()}
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: item for key, item in translated.items() if key in allowed})

    def validate(self) -> list[str]:
        errors: list[str] = []
        numeric = (
            self.initial_order_notional, self.take_profit, self.dca_spacing,
            self.emergency_equity_trigger, self.emergency_hedge_ratio,
            self.rescue_order_notional, self.rescue_take_profit,
            self.minimum_available_buffer, self.maximum_margin_ratio,
            self.minimum_liquidation_distance, self.slippage_tolerance,
            self.assumed_taker_fee,
        )
        if any(not math.isfinite(float(item)) for item in numeric):
            errors.append("Instellingen bevatten een ongeldig getal")
        if self.mode not in {"paper", "live"}:
            errors.append("Kies paper of live")
        if self.symbol != "BTC_USDT":
            errors.append("Test-3 ondersteunt momenteel uitsluitend BTC_USDT")
        if not 1 <= self.leverage <= 200:
            errors.append("Hefboom moet tussen 1x en 200x liggen")
        if self.margin_mode.lower() != "cross":
            errors.append("Test-3 vereist Cross Margin")
        if self.initial_order_notional <= 0:
            errors.append("Eerste orderwaarde moet positief zijn")
        if not .0001 <= self.take_profit <= .10:
            errors.append("Take-profit is ongeldig")
        if not 0 <= self.maximum_dca_orders <= 100:
            errors.append("Maximaal aantal DCA-orders is ongeldig")
        if self.dca_timeframe not in {"1m", "3m", "5m", "15m", "30m", "1h"}:
            errors.append("DCA-timeframe wordt niet ondersteund")
        if not .0001 <= self.dca_spacing <= .25:
            errors.append("DCA-afstand is ongeldig")
        if self.emergency_hedge_enabled and self.emergency_equity_trigger <= 0:
            errors.append("Equity-noodrem moet positief zijn")
        if not 0 < self.emergency_hedge_ratio <= 1:
            errors.append("Noodhedge-ratio moet tussen 0 en 100% liggen")
        if self.rescue_order_notional <= 0 or not .0001 <= self.rescue_take_profit <= .10:
            errors.append("Rescue-instellingen zijn ongeldig")
        if not 0 <= self.max_frozen_cycles <= 1:
            errors.append("Veilige standaard staat maximaal één frozen cycle toe")
        if not 0 <= self.maximum_margin_ratio < 1:
            errors.append("Maximale margin ratio is ongeldig")
        if not 0 < self.minimum_liquidation_distance <= 1:
            errors.append("Minimale liquidatieafstand is ongeldig")
        if self.classic_stop_loss:
            errors.append("Test-3 gebruikt geen klassieke prijs-stop-loss")
        return errors

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SideCycle:
    side: Literal["long", "short"]
    quantity: float = 0.0
    average_entry: float = 0.0
    total_notional: float = 0.0
    dca_level: int = 0
    next_dca_price: float = 0.0
    take_profit_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    fees: float = 0.0
    state: str = "NORMAL"


@dataclass(frozen=True)
class FrozenCycle:
    original_long_quantity: float
    original_long_average: float
    original_short_quantity: float
    original_short_average: float
    emergency_hedge_quantity: float
    emergency_hedge_entry: float
    frozen_equity: float
    timestamp: int
    realized_pnl_before_freeze: float
    total_fees: float
    current_combined_pnl: float = 0.0


@dataclass(frozen=True)
class V3State:
    state: CycleState = "NORMAL"
    cycle_id: int = 1
    long: SideCycle = field(default_factory=lambda: SideCycle("long"))
    short: SideCycle = field(default_factory=lambda: SideCycle("short"))
    frozen: FrozenCycle | None = None
    rescue_long: SideCycle = field(default_factory=lambda: SideCycle("long"))
    rescue_short: SideCycle = field(default_factory=lambda: SideCycle("short"))
    pending_normal_order_ids: tuple[str, ...] = ()
    last_action_time: int = 0
    reason: str = "Wacht op eerste simulatie"


@dataclass(frozen=True)
class V3Account:
    wallet_balance: float
    equity: float
    available_margin: float
    used_margin: float
    maintenance_margin: float
    margin_ratio: float
    liquidation_distance: float
    long_quantity: float = 0.0
    long_average: float = 0.0
    long_notional: float = 0.0
    long_unrealized: float = 0.0
    short_quantity: float = 0.0
    short_average: float = 0.0
    short_notional: float = 0.0
    short_unrealized: float = 0.0
    realized_pnl: float = 0.0
    fees: float = 0.0
    open_order_ids: tuple[str, ...] = ()
    independent_rescue_account: bool = False

    @property
    def net_quantity(self) -> float:
        return self.long_quantity - self.short_quantity


@dataclass(frozen=True)
class V3Market:
    timestamp: int
    price: float


@dataclass(frozen=True)
class V3Action:
    kind: str
    side: str = ""
    target_notional: float = 0.0
    target_quantity: float = 0.0
    reason: str = ""
    safety: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


RISK_INCREASING_ACTIONS = frozenset({
    "OPEN_SIDE",
    "ADD_DCA",
    "EMERGENCY_HEDGE",
    "OPEN_RESCUE",
})


def enforce_protective_only(action: V3Action, protective_only: bool) -> V3Action:
    """Block every action that can add exposure after an explicit user stop.

    Protective monitoring may still close or reduce existing exposure, cancel
    pending orders and reconcile exchange state.  It must never reconstruct a
    missing LONG/SHORT side or start DCA, rescue or hedge exposure.
    """
    if protective_only and action.kind in RISK_INCREASING_ACTIONS:
        return V3Action(
            "HOLD",
            reason="Handelsstop actief; nieuwe exposure is geblokkeerd",
            safety=True,
        )
    return action


def protective_monitor_is_complete(
    *,
    protective_only: bool,
    enabled: bool,
    account: V3Account,
) -> bool:
    """Return true only when a stopped strategy is exchange-confirmed flat."""
    return (
        (protective_only or not enabled)
        and account.long_quantity <= 0
        and account.short_quantity <= 0
        and not account.open_order_ids
    )


def _side_from_dict(side: str, value: dict[str, Any] | None) -> SideCycle:
    raw = value or {}
    return SideCycle(
        side=side,
        quantity=float(raw.get("quantity", 0) or 0),
        average_entry=float(raw.get("average_entry", raw.get("averageEntry", 0)) or 0),
        total_notional=float(raw.get("total_notional", raw.get("totalNotional", 0)) or 0),
        dca_level=max(0, int(raw.get("dca_level", raw.get("dcaLevel", 0)) or 0)),
        next_dca_price=float(raw.get("next_dca_price", raw.get("nextDcaPrice", 0)) or 0),
        take_profit_price=float(raw.get("take_profit_price", raw.get("takeProfitPrice", 0)) or 0),
        unrealized_pnl=float(raw.get("unrealized_pnl", raw.get("unrealizedPnl", 0)) or 0),
        realized_pnl=float(raw.get("realized_pnl", raw.get("realizedPnl", 0)) or 0),
        fees=float(raw.get("fees", 0) or 0),
        state=str(raw.get("state", "NORMAL")),
    )


def state_from_dict(value: dict[str, Any] | None) -> V3State:
    raw = value or {}
    frozen_raw = raw.get("frozen") if isinstance(raw.get("frozen"), dict) else None
    frozen = FrozenCycle(**frozen_raw) if frozen_raw else None
    pending = raw.get("pending_normal_order_ids", raw.get("pendingNormalOrderIds", ())) or ()
    return V3State(
        state=str(raw.get("state", "NORMAL")),
        cycle_id=max(1, int(raw.get("cycle_id", raw.get("cycleId", 1)) or 1)),
        long=_side_from_dict("long", raw.get("long")),
        short=_side_from_dict("short", raw.get("short")),
        frozen=frozen,
        rescue_long=_side_from_dict("long", raw.get("rescue_long", raw.get("rescueLong"))),
        rescue_short=_side_from_dict("short", raw.get("rescue_short", raw.get("rescueShort"))),
        pending_normal_order_ids=tuple(str(item) for item in pending),
        last_action_time=max(0, int(raw.get("last_action_time", raw.get("lastActionTime", 0)) or 0)),
        reason=str(raw.get("reason", "Wacht op eerste simulatie")),
    )


def state_to_dict(state: V3State) -> dict[str, Any]:
    return asdict(state)


def side_from_exchange(side: str, quantity: float, average: float, notional: float,
                       unrealized: float, previous: SideCycle, settings: V3Settings) -> SideCycle:
    if quantity <= 0:
        return SideCycle(side, realized_pnl=previous.realized_pnl, fees=previous.fees)
    tp = average * (1 + settings.take_profit if side == "long" else 1 - settings.take_profit)
    anchor = previous.next_dca_price
    if anchor <= 0:
        anchor = average * (1 - settings.dca_spacing if side == "long" else 1 + settings.dca_spacing)
    return replace(previous, quantity=quantity, average_entry=average, total_notional=notional,
                   take_profit_price=tp, next_dca_price=anchor, unrealized_pnl=unrealized)


def reconcile_state(settings: V3Settings, state: V3State, account: V3Account) -> V3State:
    """Adopt exchange truth after a restart without combining logical cycles."""
    long = side_from_exchange("long", account.long_quantity, account.long_average,
                              account.long_notional, account.long_unrealized, state.long, settings)
    short = side_from_exchange("short", account.short_quantity, account.short_average,
                               account.short_notional, account.short_unrealized, state.short, settings)
    return replace(state, long=long, short=short, pending_normal_order_ids=account.open_order_ids)


def _risk_allows_new_exposure(settings: V3Settings, account: V3Account, notional: float) -> bool:
    projected_margin = notional / max(1, settings.leverage)
    return (
        account.available_margin - projected_margin - settings.minimum_available_buffer >= 0
        and account.margin_ratio < settings.maximum_margin_ratio
        and account.liquidation_distance >= settings.minimum_liquidation_distance
    )


def decide_v3(settings: V3Settings, state: V3State, account: V3Account, market: V3Market) -> V3Action:
    if errors := settings.validate():
        return V3Action("API_ERROR", reason="; ".join(errors), safety=True)
    if market.price <= 0 or account.equity <= 0:
        return V3Action("API_ERROR", reason="Account- of marktdata ontbreekt", safety=True)
    if state.state == "USER_PAUSED":
        return V3Action("HOLD", reason="Gebruiker heeft strategie gepauzeerd")

    emergency = settings.emergency_hedge_enabled and account.equity <= settings.emergency_equity_trigger
    if emergency or state.state in {"EMERGENCY_TRIGGERED", "HEDGE_EXECUTING", "FROZEN_HEDGE", "RESCUE_WAIT"}:
        if account.open_order_ids:
            return V3Action("CANCEL_PENDING", reason="Noodrem: normale pending DCA annuleren", safety=True)
        difference = account.long_quantity - account.short_quantity
        tolerance = max(1e-12, max(account.long_quantity, account.short_quantity) * .002)
        if abs(difference) > tolerance and state.frozen is None:
            side = "short" if difference > 0 else "long"
            required = abs(difference) * settings.emergency_hedge_ratio
            notional = required * market.price
            if not _risk_allows_new_exposure(settings, account, notional):
                return V3Action("SAFE_WAIT", reason="Noodhedge past niet binnen actuele MEXC-buffer", safety=True)
            return V3Action("EMERGENCY_HEDGE", side=side, target_quantity=required,
                            target_notional=notional, reason="Equity-noodrem: delta neutraliseren", safety=True)
        if state.frozen is None:
            return V3Action("FREEZE", reason="Noodhedge voltooid; cycle delta-neutraal bevriezen", safety=True)
        if not settings.rescue_enabled:
            return V3Action("HOLD", reason="Frozen cycle; rescue staat uit")
        if settings.max_frozen_cycles <= 0:
            return V3Action("SAFE_WAIT", reason="Maximaal aantal frozen cycles bereikt", safety=True)
        if settings.rescue_requires_independent_account and not account.independent_rescue_account:
            return V3Action("RESCUE_WAIT", reason="Rescue wacht op onafhankelijke MEXC-positieomgeving", safety=True)
        rescue_total = settings.rescue_order_notional * 2
        if not _risk_allows_new_exposure(settings, account, rescue_total):
            return V3Action("RESCUE_WAIT", reason="Onvoldoende veilige marginbuffer voor rescue", safety=True)
        if state.rescue_long.quantity <= 0:
            return V3Action("OPEN_RESCUE", side="long", target_notional=settings.rescue_order_notional,
                            reason="Onafhankelijke rescue Long starten")
        if state.rescue_short.quantity <= 0:
            return V3Action("OPEN_RESCUE", side="short", target_notional=settings.rescue_order_notional,
                            reason="Onafhankelijke rescue Short starten")
        return V3Action("HOLD", reason="Frozen cycle en rescue worden afzonderlijk bewaakt")

    # Independent take-profit: never close or reset the opposite side.
    if account.long_quantity > 0 and market.price >= account.long_average * (1 + settings.take_profit):
        return V3Action("CLOSE_SIDE", side="long", target_quantity=account.long_quantity,
                        reason="Long weighted TP bereikt")
    if account.short_quantity > 0 and market.price <= account.short_average * (1 - settings.take_profit):
        return V3Action("CLOSE_SIDE", side="short", target_quantity=account.short_quantity,
                        reason="Short weighted TP bereikt")

    # Start each side separately; the missing side has priority over DCA.
    if account.long_quantity <= 0:
        if not _risk_allows_new_exposure(settings, account, settings.initial_order_notional):
            return V3Action("SAFE_WAIT", reason="Onvoldoende veilige buffer voor eerste Long", safety=True)
        return V3Action("OPEN_SIDE", side="long", target_notional=settings.initial_order_notional,
                        reason="Nieuwe onafhankelijke Long-cycle")
    if account.short_quantity <= 0:
        if not _risk_allows_new_exposure(settings, account, settings.initial_order_notional):
            return V3Action("SAFE_WAIT", reason="Onvoldoende veilige buffer voor eerste Short", safety=True)
        return V3Action("OPEN_SIDE", side="short", target_notional=settings.initial_order_notional,
                        reason="Nieuwe onafhankelijke Short-cycle")

    # DCA is fixed-notional per side and never mutates the opposite cycle.
    if state.long.dca_level < settings.maximum_dca_orders:
        long_anchor = state.long.next_dca_price or account.long_average * (1 - settings.dca_spacing)
        if market.price <= long_anchor:
            if not _risk_allows_new_exposure(settings, account, settings.initial_order_notional):
                return V3Action("SAFE_WAIT", reason="Long DCA geblokkeerd door marginbuffer", safety=True)
            return V3Action("ADD_DCA", side="long", target_notional=settings.initial_order_notional,
                            reason=f"Long DCA {state.long.dca_level + 1}")
    if state.short.dca_level < settings.maximum_dca_orders:
        short_anchor = state.short.next_dca_price or account.short_average * (1 + settings.dca_spacing)
        if market.price >= short_anchor:
            if not _risk_allows_new_exposure(settings, account, settings.initial_order_notional):
                return V3Action("SAFE_WAIT", reason="Short DCA geblokkeerd door marginbuffer", safety=True)
            return V3Action("ADD_DCA", side="short", target_notional=settings.initial_order_notional,
                            reason=f"Short DCA {state.short.dca_level + 1}")
    return V3Action("HOLD", reason="Beide cycles actief; wacht op TP, DCA of equity-noodrem")


def apply_paper_action(settings: V3Settings, state: V3State, account: V3Account,
                       market: V3Market, action: V3Action) -> V3State:
    """Advance only the strategy ledger; a test harness owns account balances."""
    if action.kind == "ADD_DCA":
        side = state.long if action.side == "long" else state.short
        next_price = market.price * (1 - settings.dca_spacing if action.side == "long" else 1 + settings.dca_spacing)
        updated = replace(side, dca_level=side.dca_level + 1, next_dca_price=next_price,
                          state="DCA_ACTIVE")
        return replace(state, state="DCA_ACTIVE", long=updated if action.side == "long" else state.long,
                       short=updated if action.side == "short" else state.short,
                       last_action_time=market.timestamp, reason=action.reason)
    if action.kind == "CLOSE_SIDE":
        cleared = SideCycle(action.side)
        return replace(state, state="TP_RESET", long=cleared if action.side == "long" else state.long,
                       short=cleared if action.side == "short" else state.short,
                       last_action_time=market.timestamp, reason=action.reason)
    if action.kind == "EMERGENCY_HEDGE":
        return replace(state, state="HEDGE_EXECUTING", last_action_time=market.timestamp, reason=action.reason)
    if action.kind == "FREEZE":
        frozen = FrozenCycle(
            original_long_quantity=account.long_quantity,
            original_long_average=account.long_average,
            original_short_quantity=account.short_quantity,
            original_short_average=account.short_average,
            emergency_hedge_quantity=abs(account.long_quantity - account.short_quantity),
            emergency_hedge_entry=market.price,
            frozen_equity=account.equity,
            timestamp=market.timestamp,
            realized_pnl_before_freeze=account.realized_pnl,
            total_fees=account.fees,
            current_combined_pnl=account.long_unrealized + account.short_unrealized,
        )
        return replace(state, state="FROZEN_HEDGE", frozen=frozen, reason=action.reason)
    mapped = action.kind if action.kind in {"SAFE_WAIT", "RESCUE_WAIT", "API_ERROR"} else state.state
    return replace(state, state=mapped, last_action_time=market.timestamp, reason=action.reason)
