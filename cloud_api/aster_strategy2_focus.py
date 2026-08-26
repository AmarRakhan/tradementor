"""Pure Strategy-2 Focus / Coin van het moment domain engine.

This module has deliberately no exchange client and cannot send orders.  It is
used by shadow planning now and is designed to be reused unchanged by a future
live execution adapter.  All monetary order amounts are leveraged order
notional in USD, matching Strategy 2's existing ``baseNotional`` semantics.
Required margin is therefore ``notional / leverage``.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace, asdict
from statistics import fmean, pstdev
from typing import Any, Literal
import math
import uuid

FocusSelectionMode = Literal["automatic", "manual"]
FocusSizingMode = Literal["fixed_usd", "equity_pct"]
FocusDcaMode = Literal["fixed", "progressive"]
FocusActionKind = Literal["HOLD", "OPEN", "DCA", "PARTIAL_TP", "CLOSE"]

MAX_FOCUS_DCA = 30
DEFAULT_FOCUS_DCA = 5


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0.0
    seed = fmean(values[:period])
    alpha = 2.0 / (period + 1.0)
    result = seed
    for value in values[period:]:
        result = value * alpha + result * (1.0 - alpha)
    return result


@dataclass(frozen=True)
class FocusMarket:
    symbol: str
    price: float
    change_24h_pct: float
    quote_volume_24h: float
    liquidity_score: float = 1.0
    closes: tuple[float, ...] = ()


@dataclass(frozen=True)
class FocusRankingRow:
    symbol: str
    price: float
    change_24h_pct: float
    quote_volume_24h: float
    liquidity_score: float
    ema20: float
    ema50: float
    momentum_pct: float
    bollinger_middle: float
    bollinger_upper: float
    bollinger_lower: float
    distance_middle_pct: float
    distance_upper_pct: float
    pullback_pct: float
    overextended: bool
    eligible: bool
    score: float
    reason: str
    rejection_reason: str = ""

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FocusExposurePreview:
    first_order_notional: float
    dca_notionals: tuple[float, ...]
    total_max_order_notional: float
    required_margin: float
    max_leveraged_exposure: float
    portfolio_margin_pct: float
    remaining_free_equity: float
    worst_case_average_entry: float
    dca_trigger_prices: tuple[float, ...]
    dca_trigger_drops_pct: tuple[float, ...]
    total_drop_to_last_dca_pct: float
    focus_budget: float
    focus_budget_remaining: float
    available_margin: float
    safe: bool
    status: str

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["dca_notionals"] = list(self.dca_notionals)
        value["dca_trigger_prices"] = list(self.dca_trigger_prices)
        value["dca_trigger_drops_pct"] = list(self.dca_trigger_drops_pct)
        return value


@dataclass(frozen=True)
class FocusState:
    active_pair: str = ""
    cycle_id: str = ""
    cycle_status: str = "Pair selecteren"
    opened_at_ms: int = 0
    original_entry: float = 0.0
    weighted_entry: float = 0.0
    total_quantity: float = 0.0
    total_notional: float = 0.0
    used_margin: float = 0.0
    dca_count: int = 0
    next_dca_trigger: float = 0.0
    highest_price: float = 0.0
    highest_profit_pct: float = 0.0
    trailing_active: bool = False
    trailing_floor: float = 0.0
    partials_taken: tuple[int, ...] = ()
    realized_pnl: float = 0.0
    theoretical_portfolio_value: float = 0.0
    focus_budget_used: float = 0.0
    last_selection_reason: str = ""
    last_action: str = ""
    last_reason: str = ""

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["partials_taken"] = list(self.partials_taken)
        return result


@dataclass(frozen=True)
class FocusDecision:
    kind: FocusActionKind
    symbol: str = ""
    side: Literal["LONG"] = "LONG"
    notional: float = 0.0
    close_fraction: float = 0.0
    reason: str = ""
    status: str = ""
    risk_reducing: bool = False

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def focus_order_notional(*, sizing_mode: FocusSizingMode, fixed_usd: float,
                         equity_pct: float, equity: float, max_start_order_usd: float) -> float:
    """Return leveraged order notional using the same semantics as Strategy 2."""
    if sizing_mode == "equity_pct":
        value = max(0.0, equity) * max(0.0, equity_pct)
    else:
        value = max(0.0, fixed_usd)
    if max_start_order_usd > 0:
        value = min(value, max_start_order_usd)
    return value


def dca_notional_sequence(*, amount: float, multiplier: float, count: int) -> tuple[float, ...]:
    count = max(0, min(MAX_FOCUS_DCA, int(count)))
    amount = max(0.0, float(amount))
    multiplier = max(0.0, float(multiplier))
    return tuple(amount * (multiplier ** index) for index in range(count))


def dca_drop_sequence(*, distance_pct: float, count: int, mode: FocusDcaMode = "fixed") -> tuple[float, ...]:
    count = max(0, min(MAX_FOCUS_DCA, int(count)))
    distance = max(0.0, float(distance_pct))
    if mode == "progressive":
        return tuple(distance * index * (index + 1) / 2 for index in range(1, count + 1))
    return tuple(distance * index for index in range(1, count + 1))


def weighted_average_entry(start_price: float, start_notional: float,
                           trigger_prices: tuple[float, ...], dca_notionals: tuple[float, ...]) -> float:
    if start_price <= 0 or start_notional <= 0:
        return 0.0
    quantity = start_notional / start_price
    total_notional = start_notional
    for price, notional in zip(trigger_prices, dca_notionals):
        if price <= 0 or notional <= 0:
            continue
        quantity += notional / price
        total_notional += notional
    return total_notional / quantity if quantity > 0 else 0.0


def exposure_preview(*, entry_price: float, first_order_notional: float, dca_enabled: bool,
                     dca_amount: float, dca_multiplier: float, max_dca: int,
                     dca_distance_pct: float, dca_mode: FocusDcaMode, leverage: int,
                     equity: float, available_margin: float, focus_budget: float) -> FocusExposurePreview:
    """Calculate the exact maximum configured Focus path before any order is sent.

    ``focus_budget`` and ``available_margin`` are margin-denominated USD limits.
    Order amounts are leveraged notional.  This mirrors existing Strategy-2
    execution semantics and prevents UI/backend notional ambiguity.
    """
    leverage = max(1, int(leverage))
    count = max(0, min(MAX_FOCUS_DCA, int(max_dca))) if dca_enabled else 0
    notionals = dca_notional_sequence(amount=dca_amount, multiplier=dca_multiplier, count=count)
    drops = dca_drop_sequence(distance_pct=dca_distance_pct, count=count, mode=dca_mode)
    prices = tuple(max(0.00000001, entry_price * (1.0 - drop)) for drop in drops)
    total_notional = max(0.0, first_order_notional) + sum(notionals)
    required_margin = total_notional / leverage
    budget = max(0.0, focus_budget)
    available = max(0.0, available_margin)
    safe = required_margin <= budget + 1e-9 and required_margin <= available + 1e-9
    if required_margin > budget + 1e-9:
        status = "budget overschreden"
    elif required_margin > available + 1e-9:
        status = "onvoldoende beschikbare margin"
    else:
        status = "veilig"
    return FocusExposurePreview(
        first_order_notional=max(0.0, first_order_notional),
        dca_notionals=notionals,
        total_max_order_notional=total_notional,
        required_margin=required_margin,
        max_leveraged_exposure=total_notional,
        portfolio_margin_pct=(required_margin / equity if equity > 0 else 0.0),
        remaining_free_equity=max(0.0, available - required_margin),
        worst_case_average_entry=weighted_average_entry(entry_price, first_order_notional, prices, notionals),
        dca_trigger_prices=prices,
        dca_trigger_drops_pct=drops,
        total_drop_to_last_dca_pct=(drops[-1] if drops else 0.0),
        focus_budget=budget,
        focus_budget_remaining=max(0.0, budget - required_margin),
        available_margin=available,
        safe=safe,
        status=status,
    )


def _market_indicators(market: FocusMarket) -> FocusRankingRow:
    values = [x for x in (_finite(v) for v in market.closes) if x > 0]
    price = _finite(market.price)
    if len(values) >= 20:
        window = values[-20:]
        middle = fmean(window)
        deviation = pstdev(window)
        upper, lower = middle + 2 * deviation, middle - 2 * deviation
    else:
        middle = price
        upper = price
        lower = price
    ema20 = _ema(values, 20) if values else price
    ema50 = _ema(values, 50) if values else price
    momentum = ((values[-1] / values[-6]) - 1.0) if len(values) >= 6 and values[-6] > 0 else 0.0
    recent_high = max(values[-10:]) if values else price
    pullback = max(0.0, 1.0 - price / recent_high) if recent_high > 0 else 0.0
    distance_middle = (price / middle - 1.0) if middle > 0 else 0.0
    distance_upper = (price / upper - 1.0) if upper > 0 else 0.0
    overextended = upper > 0 and price > upper * 1.01
    liquid = market.quote_volume_24h > 0 and market.liquidity_score > 0
    uptrend = ema20 >= ema50
    # 24h percentage remains the primary signal. Technical terms are bounded
    # modifiers so #2/#3 can beat an extremely overextended #1, but a weak coin
    # cannot leapfrog the leaders purely on an indicator.
    technical = 0.0
    technical += 8.0 if uptrend else -8.0
    technical += max(-6.0, min(6.0, momentum * 100.0))
    technical += 6.0 if -0.03 <= distance_middle <= 0.01 else 2.0 if distance_middle < 0.04 else -3.0
    technical += 5.0 if 0.005 <= pullback <= 0.08 else 0.0
    technical -= 22.0 if overextended else 0.0
    technical += max(0.0, min(4.0, math.log10(max(1.0, market.quote_volume_24h)) - 5.0))
    technical += max(0.0, min(3.0, market.liquidity_score * 3.0))
    score = market.change_24h_pct * 100.0 + technical
    eligible = liquid and market.change_24h_pct > 0 and price > 0
    reason = "24h stijger"
    if uptrend: reason += " · EMA20 boven EMA50"
    if -0.03 <= distance_middle <= 0.01: reason += " · gunstige pullback rond BB-middle"
    if overextended: reason += " · boven upper band/overstrekt"
    reject = ""
    if not liquid: reject = "onvoldoende volume/liquiditeit"
    elif market.change_24h_pct <= 0: reject = "geen positieve 24h stijging"
    elif price <= 0: reject = "ongeldige prijs"
    return FocusRankingRow(market.symbol.upper(), price, market.change_24h_pct, market.quote_volume_24h,
        market.liquidity_score, ema20, ema50, momentum, middle, upper, lower, distance_middle,
        distance_upper, pullback, overextended, eligible, score, reason, reject)


def rank_focus_pairs(markets: list[FocusMarket], *, minimum_quote_volume: float = 0.0,
                     minimum_liquidity_score: float = 0.0) -> list[FocusRankingRow]:
    """Rank only with information supplied for the current decision timestamp."""
    rows = []
    for market in markets:
        row = _market_indicators(market)
        if row.quote_volume_24h < minimum_quote_volume:
            row = replace(row, eligible=False, rejection_reason="minimum 24h quote-volume niet gehaald")
        if row.liquidity_score < minimum_liquidity_score:
            row = replace(row, eligible=False, rejection_reason="minimum liquidity-score niet gehaald")
        rows.append(row)
    # First establish 24h-leader context; score is only allowed to reorder the
    # strongest candidate group, preventing a technically pretty laggard from
    # replacing genuine momentum leadership.
    rows.sort(key=lambda r: r.change_24h_pct, reverse=True)
    eligible = [r for r in rows if r.eligible]
    leaders = eligible[:10]
    leaders.sort(key=lambda r: (r.score, r.change_24h_pct), reverse=True)
    leader_symbols = {r.symbol for r in leaders}
    tail = [r for r in rows if r.symbol not in leader_symbols]
    return leaders + tail


def select_focus_pair(markets: list[FocusMarket], *, selection_mode: FocusSelectionMode = "automatic",
                      manual_pair: str = "", active_pair: str = "", cycle_open: bool = False,
                      minimum_quote_volume: float = 0.0,
                      minimum_liquidity_score: float = 0.0) -> tuple[FocusRankingRow | None, list[FocusRankingRow], str]:
    ranking = rank_focus_pairs(markets, minimum_quote_volume=minimum_quote_volume,
                               minimum_liquidity_score=minimum_liquidity_score)
    if cycle_open and active_pair:
        current = next((row for row in ranking if row.symbol == active_pair.upper()), None)
        return current, ranking, "actieve cyclus behouden; geen pair-hopping"
    if selection_mode == "manual":
        wanted = manual_pair.upper().strip()
        selected = next((row for row in ranking if row.symbol == wanted and row.eligible), None)
        return selected, ranking, "handmatige Focus-selectie" if selected else "handmatige pair niet beschikbaar/eligible"
    selected = next((row for row in ranking if row.eligible), None)
    return selected, ranking, selected.reason if selected else "geen geschikte LONG-kandidaat"


def next_dca_trigger(*, original_entry: float, dca_count: int, max_dca: int,
                     distance_pct: float, mode: FocusDcaMode) -> float:
    if original_entry <= 0 or dca_count >= max_dca:
        return 0.0
    drops = dca_drop_sequence(distance_pct=distance_pct, count=max_dca, mode=mode)
    if dca_count >= len(drops):
        return 0.0
    return max(0.0, original_entry * (1.0 - drops[dca_count]))


def can_add_focus_order(*, proposed_notional: float, leverage: int, focus_budget_used: float,
                        focus_budget: float, strategy_margin_used: float, strategy_budget: float,
                        available_margin: float, exchange_max_notional_remaining: float,
                        liquidation_distance_pct: float, minimum_liquidation_distance_pct: float,
                        maintenance_margin_ratio: float, maximum_maintenance_margin_ratio: float) -> tuple[bool, str]:
    margin = proposed_notional / max(1, leverage)
    if proposed_notional <= 0: return False, "ongeldige DCA-order"
    if focus_budget_used + margin > focus_budget + 1e-9: return False, "Focus-budget bereikt"
    if strategy_margin_used + margin > strategy_budget + 1e-9: return False, "Strategy-2-budget bereikt"
    if margin > available_margin + 1e-9: return False, "onvoldoende beschikbare margin"
    if proposed_notional > exchange_max_notional_remaining + 1e-9: return False, "exchange max-notional bereikt"
    if liquidation_distance_pct < minimum_liquidation_distance_pct: return False, "liquidation-distance te klein"
    if maintenance_margin_ratio > maximum_maintenance_margin_ratio: return False, "maintenance-margin grens bereikt"
    return True, "veilig"


def apply_focus_buy(state: FocusState, *, price: float, notional: float, leverage: int,
                    timestamp_ms: int, is_dca: bool, reason: str = "") -> FocusState:
    if price <= 0 or notional <= 0: raise ValueError("Focus-fill vereist positieve prijs en notional")
    quantity = notional / price
    total_quantity = state.total_quantity + quantity
    total_notional = state.total_notional + notional
    weighted = total_notional / total_quantity if total_quantity > 0 else 0.0
    original = state.original_entry or price
    highest = max(state.highest_price, price)
    return replace(state,
        cycle_id=state.cycle_id or f"focus-{uuid.uuid4().hex}",
        opened_at_ms=state.opened_at_ms or timestamp_ms,
        original_entry=original,
        weighted_entry=weighted,
        total_quantity=total_quantity,
        total_notional=total_notional,
        used_margin=state.used_margin + notional / max(1, leverage),
        focus_budget_used=state.focus_budget_used + notional / max(1, leverage),
        dca_count=state.dca_count + (1 if is_dca else 0),
        highest_price=highest,
        cycle_status="Dip kopen" if is_dca else "Instap",
        last_action="DCA" if is_dca else "OPEN",
        last_reason=reason)


def focus_pnl_pct(state: FocusState, price: float) -> float:
    return (price / state.weighted_entry - 1.0) if state.weighted_entry > 0 else 0.0


def update_trailing(state: FocusState, *, price: float, activation_pct: float,
                    trailing_distance_pct: float, minimum_profit_pct: float) -> FocusState:
    if state.weighted_entry <= 0 or price <= 0:
        return state
    highest = max(state.highest_price, price)
    highest_profit = max(state.highest_profit_pct, highest / state.weighted_entry - 1.0)
    activation = max(activation_pct, minimum_profit_pct)
    active = state.trailing_active or highest_profit >= activation
    candidate_floor = highest * (1.0 - trailing_distance_pct) if active else 0.0
    floor = max(state.trailing_floor, candidate_floor) if active else state.trailing_floor
    return replace(state, highest_price=highest, highest_profit_pct=highest_profit,
                   trailing_active=active, trailing_floor=floor,
                   cycle_status="Trailing actief" if active else "Trend volgen")


def exit_decision(state: FocusState, *, price: float, minimum_profit_pct: float,
                  trailing_activation_pct: float, trailing_distance_pct: float,
                  partial_tp_enabled: bool, first_partial_tp_pct: float,
                  first_partial_close_pct: float, second_partial_tp_pct: float,
                  second_partial_close_pct: float, momentum_healthy: bool = True,
                  bollinger_overextended_reversal: bool = False) -> tuple[FocusState, FocusDecision]:
    updated = update_trailing(state, price=price, activation_pct=trailing_activation_pct,
                              trailing_distance_pct=trailing_distance_pct,
                              minimum_profit_pct=minimum_profit_pct)
    pnl = focus_pnl_pct(updated, price)
    taken = set(updated.partials_taken)
    if partial_tp_enabled and pnl >= first_partial_tp_pct and 1 not in taken:
        taken.add(1)
        updated = replace(updated, partials_taken=tuple(sorted(taken)), cycle_status="Partial winst nemen")
        return updated, FocusDecision("PARTIAL_TP", updated.active_pair, notional=updated.total_notional * first_partial_close_pct,
                                     close_fraction=first_partial_close_pct, reason="eerste partial TP bereikt", status="Partial winst nemen", risk_reducing=True)
    if partial_tp_enabled and pnl >= second_partial_tp_pct and 2 not in taken:
        taken.add(2)
        updated = replace(updated, partials_taken=tuple(sorted(taken)), cycle_status="Partial winst nemen")
        return updated, FocusDecision("PARTIAL_TP", updated.active_pair, notional=updated.total_notional * second_partial_close_pct,
                                     close_fraction=second_partial_close_pct, reason="tweede partial TP bereikt", status="Partial winst nemen", risk_reducing=True)
    if updated.trailing_active and updated.trailing_floor > 0 and price <= updated.trailing_floor:
        return replace(updated, cycle_status="Winst nemen"), FocusDecision("CLOSE", updated.active_pair,
            notional=updated.total_notional, close_fraction=1.0, reason="trailing floor geraakt", status="Winst nemen", risk_reducing=True)
    if pnl >= minimum_profit_pct and bollinger_overextended_reversal and not momentum_healthy:
        return replace(updated, cycle_status="Winst nemen"), FocusDecision("CLOSE", updated.active_pair,
            notional=updated.total_notional, close_fraction=1.0, reason="momentum draait na Bollinger-overstretch", status="Winst nemen", risk_reducing=True)
    return updated, FocusDecision("HOLD", updated.active_pair, reason="runner blijft open", status=updated.cycle_status)


def reset_after_full_exit(state: FocusState, *, realized_pnl: float,
                          theoretical_portfolio_value: float) -> FocusState:
    return FocusState(realized_pnl=state.realized_pnl + realized_pnl,
                      theoretical_portfolio_value=theoretical_portfolio_value,
                      cycle_status="Nieuwe pair zoeken", last_action="CLOSE",
                      last_reason="volledige Focus-cyclus gesloten")


def focus_shadow_report(*, state: FocusState, decision: FocusDecision,
                        ranking: list[FocusRankingRow], portfolio_equity: float,
                        realized_pnl: float = 0.0, unrealized_pnl: float = 0.0,
                        max_drawdown: float = 0.0, fees: float = 0.0,
                        capital_used_margin: float = 0.0, trades: int = 0) -> dict[str, Any]:
    return {
        "mode": "focus-shadow",
        "ordersSent": 0,
        "state": state.public_dict(),
        "decision": decision.public_dict(),
        "ranking": [row.public_dict() for row in ranking],
        "performance": {
            "portfolioEquity": portfolio_equity,
            "realizedPnl": realized_pnl,
            "unrealizedPnl": unrealized_pnl,
            "maxDrawdown": max_drawdown,
            "trades": trades,
            "dcaCount": state.dca_count,
            "fees": fees,
            "capitalUsedMargin": capital_used_margin,
            "returnPerUsedMargin": ((realized_pnl + unrealized_pnl) / capital_used_margin if capital_used_margin > 0 else 0.0),
        },
    }
