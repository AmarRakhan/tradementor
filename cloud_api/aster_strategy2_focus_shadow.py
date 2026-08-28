"""Read-only Strategy-2 Focus shadow planner.

The planner consumes already-fetched market/account data and the persisted Focus
state. It has no order-capable dependency. Every result explicitly reports
``ordersSent: 0`` and theoretical actions only.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Any
import math

from aster_strategy2 import Strategy2Config
from aster_strategy2_focus import (
    FocusDecision, FocusMarket, FocusState, apply_focus_buy, can_add_focus_order,
    dca_notional_sequence, exit_decision, focus_order_notional,
    focus_shadow_report, next_dca_trigger, reset_after_full_exit, select_focus_pair,
)


class FocusShadowMutationBlocked(RuntimeError):
    pass


class FocusShadowBoundary:
    """No order-capable client exists inside the pure shadow planner."""
    def submit_order(self, *_args, **_kwargs):
        raise FocusShadowMutationBlocked("Focus Shadow mag absoluut geen orders versturen")
    def persist_exchange_change(self, *_args, **_kwargs):
        raise FocusShadowMutationBlocked("Focus Shadow mag exchange-state niet wijzigen")


@dataclass(frozen=True)
class FocusRiskSnapshot:
    portfolio_equity: float
    available_margin: float
    strategy_margin_used: float
    strategy_budget_margin: float
    exchange_max_notional_remaining: float
    liquidation_distance_pct: float = 1.0
    minimum_liquidation_distance_pct: float = .05
    maintenance_margin_ratio: float = 0.0
    maximum_maintenance_margin_ratio: float = .70


@dataclass(frozen=True)
class FocusShadowInputs:
    config: Strategy2Config
    markets: tuple[FocusMarket, ...]
    state: FocusState
    risk: FocusRiskSnapshot
    timestamp_ms: int
    legacy_open_positions: int = 0
    current_strategy2_metrics: dict[str, Any] | None = None
    theoretical_fees: float = 0.0
    theoretical_unrealized_pnl: float = 0.0
    theoretical_realized_pnl: float = 0.0
    theoretical_max_drawdown: float = 0.0
    theoretical_trades: int = 0


def _current_market(value: FocusShadowInputs) -> FocusMarket | None:
    pair = value.state.active_pair.upper()
    return next((m for m in value.markets if m.symbol.upper() == pair), None)


def _next_focus_dca_notional(config: Strategy2Config, dca_count: int) -> float:
    index=max(0,int(dca_count))
    if config.focus_dca_amount_mode=="linear":
        return config.focus_dca_notional+config.focus_dca_increment*index
    try:value=config.focus_dca_notional*(config.focus_dca_multiplier**index)
    except OverflowError:return float("inf")
    return value if math.isfinite(value) else float("inf")


def plan_focus_shadow(value: FocusShadowInputs) -> dict[str, Any]:
    config = value.config
    state = value.state
    ranking = []
    selection_reason = state.last_selection_reason

    if config.trading_mode != "focus" or not config.focus_shadow_enabled:
        decision = FocusDecision("HOLD", state.active_pair, reason="Focus Shadow staat uit", status="Focus uit")
        report = focus_shadow_report(state=state, decision=decision, ranking=[],
            portfolio_equity=value.risk.portfolio_equity,
            realized_pnl=value.theoretical_realized_pnl,
            unrealized_pnl=value.theoretical_unrealized_pnl,
            max_drawdown=value.theoretical_max_drawdown, fees=value.theoretical_fees,
            capital_used_margin=state.used_margin, trades=value.theoretical_trades)
        report["currentStrategy2"] = value.current_strategy2_metrics or {}
        report["theoreticalActions"] = []
        return report

    cycle_open = bool(state.active_pair and state.total_quantity > 0 and state.weighted_entry > 0)
    selected, ranking, selection_reason = select_focus_pair(list(value.markets),
        selection_mode=config.focus_selection_mode, manual_pair=config.focus_manual_pair,
        active_pair=state.active_pair, cycle_open=cycle_open,
        minimum_quote_volume=config.minimum_quote_volume_24h_usdt,
        minimum_liquidity_score=config.focus_min_liquidity_score)

    # Existing legacy Strategy-2 positions stay managed elsewhere. This flag only
    # decides whether a *new Focus cycle* may start; no position is auto-closed.
    if not cycle_open and config.focus_wait_until_flat and value.legacy_open_positions > 0:
        state = replace(state, cycle_status="Wacht op bestaande posities",
                        last_selection_reason=selection_reason)
        decision = FocusDecision("HOLD", reason="wacht tot bestaande Strategy-2-posities gesloten zijn",
                                 status=state.cycle_status)
    elif not cycle_open:
        if selected is None:
            state = replace(state, cycle_status="Pair selecteren", last_selection_reason=selection_reason)
            decision = FocusDecision("HOLD", reason=selection_reason, status="Pair selecteren")
        else:
            start_notional = focus_order_notional(
                sizing_mode=("equity_pct" if config.focus_auto_compound else config.focus_sizing_mode),
                fixed_usd=config.focus_start_order_notional,
                equity_pct=config.focus_equity_pct,
                equity=value.risk.portfolio_equity,
                max_start_order_usd=config.focus_max_start_order_usd,
            )
            allowed, reason = can_add_focus_order(proposed_notional=start_notional,
                leverage=config.leverage, focus_budget_used=0.0,
                focus_budget=config.focus_max_budget_usd,
                strategy_margin_used=value.risk.strategy_margin_used,
                strategy_budget=value.risk.strategy_budget_margin,
                available_margin=value.risk.available_margin,
                exchange_max_notional_remaining=value.risk.exchange_max_notional_remaining,
                liquidation_distance_pct=value.risk.liquidation_distance_pct,
                minimum_liquidation_distance_pct=value.risk.minimum_liquidation_distance_pct,
                maintenance_margin_ratio=value.risk.maintenance_margin_ratio,
                maximum_maintenance_margin_ratio=value.risk.maximum_maintenance_margin_ratio)
            if allowed:
                state = replace(state, active_pair=selected.symbol,
                    last_selection_reason=selection_reason,
                    next_dca_trigger=next_dca_trigger(original_entry=selected.price,
                        dca_count=0, max_dca=config.focus_max_dca,
                        distance_pct=config.focus_dca_distance, mode=config.focus_dca_mode, custom_levels=config.focus_dca_custom_levels,
                        unlimited=config.focus_dca_unlimited))
                decision = FocusDecision("OPEN", selected.symbol, notional=start_notional,
                    reason=selection_reason, status="Instap")
            else:
                state = replace(state, active_pair=selected.symbol, cycle_status="DCA-budget bereikt",
                                last_selection_reason=selection_reason, last_reason=reason)
                decision = FocusDecision("HOLD", selected.symbol, reason=reason, status="Budget/risk blokkeert instap")
    else:
        market = _current_market(value)
        if market is None:
            decision = FocusDecision("HOLD", state.active_pair,
                reason="actieve Focus-pair ontbreekt in betrouwbare marktinput", status="Herstel")
            state = replace(state, cycle_status="Herstel", last_reason=decision.reason)
        else:
            state, exit_action = exit_decision(state, price=market.price,
                minimum_profit_pct=config.focus_minimum_profit_pct,
                trailing_activation_pct=config.focus_trailing_activation_pct,
                trailing_distance_pct=config.focus_trailing_distance_pct,
                partial_tp_enabled=config.focus_partial_tp_enabled,
                first_partial_tp_pct=config.focus_first_partial_tp_pct,
                first_partial_close_pct=config.focus_first_partial_close_pct,
                second_partial_tp_pct=config.focus_second_partial_tp_pct,
                second_partial_close_pct=config.focus_second_partial_close_pct,
                momentum_healthy=(selected.momentum_pct >= 0 if selected else True),
                bollinger_overextended_reversal=(selected.overextended if selected else False))
            if exit_action.kind != "HOLD":
                decision = exit_action
            else:
                trigger = next_dca_trigger(original_entry=state.original_entry,
                    dca_count=state.dca_count, max_dca=config.focus_max_dca,
                    distance_pct=config.focus_dca_distance, mode=config.focus_dca_mode, custom_levels=config.focus_dca_custom_levels,
                    unlimited=config.focus_dca_unlimited)
                if (config.focus_dca_enabled and trigger > 0 and market.price <= trigger
                        and (config.focus_dca_unlimited or state.dca_count < config.focus_max_dca)):
                    proposed = _next_focus_dca_notional(config, state.dca_count)
                    allowed, reason = can_add_focus_order(proposed_notional=proposed,
                        leverage=config.leverage, focus_budget_used=state.focus_budget_used,
                        focus_budget=config.focus_max_budget_usd,
                        strategy_margin_used=value.risk.strategy_margin_used,
                        strategy_budget=value.risk.strategy_budget_margin,
                        available_margin=value.risk.available_margin,
                        exchange_max_notional_remaining=value.risk.exchange_max_notional_remaining,
                        liquidation_distance_pct=value.risk.liquidation_distance_pct,
                        minimum_liquidation_distance_pct=value.risk.minimum_liquidation_distance_pct,
                        maintenance_margin_ratio=value.risk.maintenance_margin_ratio,
                        maximum_maintenance_margin_ratio=value.risk.maximum_maintenance_margin_ratio)
                    if allowed:
                        decision = FocusDecision("DCA", state.active_pair, notional=proposed,
                            reason=f"DCA {state.dca_count+1} trigger {trigger:.8g} bereikt", status="Dip kopen")
                    else:
                        state = replace(state, cycle_status="DCA-budget bereikt", last_reason=reason,
                            next_dca_trigger=trigger)
                        decision = FocusDecision("HOLD", state.active_pair,
                            reason=f"DCA overgeslagen · {reason}", status="DCA-budget bereikt")
                else:
                    state = replace(state, next_dca_trigger=trigger)
                    decision = exit_action

    report = focus_shadow_report(state=state, decision=decision, ranking=ranking,
        portfolio_equity=value.risk.portfolio_equity,
        realized_pnl=value.theoretical_realized_pnl,
        unrealized_pnl=value.theoretical_unrealized_pnl,
        max_drawdown=value.theoretical_max_drawdown, fees=value.theoretical_fees,
        capital_used_margin=state.used_margin, trades=value.theoretical_trades)
    report["currentStrategy2"] = value.current_strategy2_metrics or {}
    report["selectionReason"] = selection_reason
    report["theoreticalActions"] = ([] if decision.kind == "HOLD" else [decision.public_dict()])
    report["legacyPositionsManagedByMultiPair"] = value.legacy_open_positions
    report["newFocusPairLimit"] = 1
    report["side"] = "LONG"
    report["orderQueueLimit"] = 15
    report["ordersSent"] = 0
    return report
