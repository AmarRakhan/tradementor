"""Read-only Aster data adapter for Strategy-2 Focus Shadow.

The adapter may perform signed GETs for account risk evidence and public GETs
for market data, but receives a client created with ``live_authorized=False``.
It never imports or calls Strategy-2 execution functions.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any
import math
import time

from aster_strategy2 import Strategy2Config
from aster_strategy2_focus import FocusMarket, FocusState, apply_focus_buy, reset_after_full_exit
from aster_strategy2_focus_shadow import FocusRiskSnapshot, FocusShadowInputs, plan_focus_shadow


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def focus_state_from_mapping(raw: Any) -> FocusState:
    value = raw if isinstance(raw, dict) else {}
    def g(camel: str, snake: str, default: Any = None) -> Any:
        if camel in value: return value[camel]
        if snake in value: return value[snake]
        return default
    partials = g("partialsTaken", "partials_taken", ())
    if not isinstance(partials, (list, tuple)): partials = ()
    return FocusState(
        active_pair=str(g("activePair", "active_pair", "") or "").upper(),
        cycle_id=str(g("cycleId", "cycle_id", "") or ""),
        cycle_status=str(g("cycleStatus", "cycle_status", "Pair selecteren") or "Pair selecteren"),
        opened_at_ms=int(_f(g("openedAt", "opened_at_ms", 0))),
        original_entry=_f(g("originalEntry", "original_entry", 0)),
        weighted_entry=_f(g("weightedEntry", "weighted_entry", 0)),
        total_quantity=_f(g("totalQuantity", "total_quantity", 0)),
        total_notional=_f(g("totalNotional", "total_notional", 0)),
        used_margin=_f(g("usedMargin", "used_margin", 0)),
        dca_count=int(_f(g("dcaCount", "dca_count", 0))),
        next_dca_trigger=_f(g("nextDcaTrigger", "next_dca_trigger", 0)),
        highest_price=_f(g("highestPrice", "highest_price", 0)),
        highest_profit_pct=_f(g("highestProfitPct", "highest_profit_pct", 0)),
        trailing_active=bool(g("trailingActive", "trailing_active", False)),
        trailing_floor=_f(g("trailingFloor", "trailing_floor", 0)),
        partials_taken=tuple(int(x) for x in partials if str(x).isdigit()),
        realized_pnl=_f(g("realizedPnl", "realized_pnl", 0)),
        theoretical_portfolio_value=_f(g("theoreticalPortfolioValue", "theoretical_portfolio_value", 0)),
        focus_budget_used=_f(g("focusBudgetUsed", "focus_budget_used", 0)),
        last_selection_reason=str(g("lastSelectionReason", "last_selection_reason", "") or ""),
        last_action=str(g("lastAction", "last_action", "") or ""),
        last_reason=str(g("lastReason", "last_reason", "") or ""),
    )


def focus_state_to_mapping(state: FocusState) -> dict[str, Any]:
    return {
        "activePair": state.active_pair, "cycleId": state.cycle_id,
        "cycleStatus": state.cycle_status, "openedAt": state.opened_at_ms,
        "originalEntry": state.original_entry, "weightedEntry": state.weighted_entry,
        "totalQuantity": state.total_quantity, "totalNotional": state.total_notional,
        "usedMargin": state.used_margin, "dcaCount": state.dca_count,
        "nextDcaTrigger": state.next_dca_trigger, "highestPrice": state.highest_price,
        "highestProfitPct": state.highest_profit_pct, "trailingActive": state.trailing_active,
        "trailingFloor": state.trailing_floor, "partialsTaken": list(state.partials_taken),
        "realizedPnl": state.realized_pnl,
        "theoreticalPortfolioValue": state.theoretical_portfolio_value,
        "focusBudgetUsed": state.focus_budget_used,
        "lastSelectionReason": state.last_selection_reason,
        "lastAction": state.last_action, "lastReason": state.last_reason,
    }


def _tradable_symbols(exchange_info: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for row in exchange_info.get("symbols", ()) if isinstance(exchange_info, dict) else ():
        if not isinstance(row, dict): continue
        symbol = str(row.get("symbol", "")).upper()
        quote = str(row.get("quoteAsset", "")).upper()
        status = str(row.get("status", "TRADING")).upper()
        contract = str(row.get("contractType", "PERPETUAL")).upper()
        if symbol and quote == "USDT" and status == "TRADING" and contract in {"PERPETUAL", ""}:
            result.add(symbol)
    return result


def current_focus_markets(client: Any, config: Strategy2Config, *, candidate_limit: int = 12) -> tuple[FocusMarket, ...]:
    """Use only data available at call time; historical closes end at current candle input."""
    exchange_info = client.public_exchange_info()
    allowed = _tradable_symbols(exchange_info)
    tickers = client.ticker_24h()
    prices = {str(x.get("symbol", "")).upper(): _f(x.get("price")) for x in client.ticker_prices() if isinstance(x, dict)}
    ticker_by_symbol = {str(row.get("symbol", "")).upper(): row for row in tickers if isinstance(row, dict)}
    raw: list[tuple[str, float, float]] = []
    for symbol in allowed:
        row = ticker_by_symbol.get(symbol, {})
        change = _f(row.get("priceChangePercent")) / 100.0
        quote_volume = max(0.0, _f(row.get("quoteVolume")))
        raw.append((symbol, change, quote_volume))
    # Focus candidate pool is exactly the current Top 20 tradable USDT perpetuals by quote volume.
    # Volume defines the liquid pool only; technical Focus scoring ranks inside that pool.
    raw.sort(key=lambda x: x[2], reverse=True)
    raw=raw[:20]
    technical_symbols={symbol for symbol,_,_ in raw}
    result: list[FocusMarket] = []
    for symbol, change, volume in raw:
        price = prices.get(symbol, 0.0)
        if price <= 0: continue
        closes: list[float] = []
        if symbol in technical_symbols:
            try:
                for candle in client.klines(symbol, "15m", 60):
                    if len(candle) > 4:
                        close = _f(candle[4])
                        if close > 0: closes.append(close)
            except Exception:
                closes = []
        liquidity = min(1.0, volume / max(1.0, config.minimum_quote_volume_24h_usdt))
        result.append(FocusMarket(symbol, price, change, volume, liquidity, tuple(closes)))
    return tuple(result)


def _open_position_count(positions: list[dict[str, Any]]) -> int:
    return sum(1 for row in positions if isinstance(row, dict) and abs(_f(row.get("positionAmt"))) > 0)


def build_focus_shadow_report(*, client: Any, raw_state: dict[str, Any], timestamp_ms: int | None = None) -> dict[str, Any]:
    config = Strategy2Config.from_mapping(raw_state.get("settings"))
    state = focus_state_from_mapping(raw_state.get("focusShadowState"))
    now_ms = int(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
    account = client.account_information()
    positions = client.position_risk()
    markets = current_focus_markets(client, config)
    equity = _f(account.get("totalMarginBalance"), _f(account.get("totalWalletBalance")))
    available = _f(account.get("availableBalance"))
    strategy_margin_used = _f((raw_state.get("accountSnapshot") or {}).get("strategyMargin")) if isinstance(raw_state.get("accountSnapshot"), dict) else 0.0
    exchange_remaining = 0.0
    selected_symbol = state.active_pair or (markets[0].symbol if markets else "")
    if selected_symbol:
        try:
            exchange_remaining = _f(client.remaining_openable_notional_value(selected_symbol, config.leverage))
        except Exception:
            exchange_remaining = 0.0
    risk = FocusRiskSnapshot(
        portfolio_equity=equity,
        available_margin=available,
        strategy_margin_used=max(0.0, strategy_margin_used),
        strategy_budget_margin=max(0.0, equity * config.strategy_budget),
        exchange_max_notional_remaining=max(0.0, exchange_remaining),
        liquidation_distance_pct=1.0,
        minimum_liquidation_distance_pct=.05,
        maintenance_margin_ratio=_f(account.get("totalMaintMargin")) / equity if equity > 0 else 1.0,
        maximum_maintenance_margin_ratio=config.emergency_margin_ratio,
    )
    report = plan_focus_shadow(FocusShadowInputs(
        config=config, markets=markets, state=state, risk=risk, timestamp_ms=now_ms,
        legacy_open_positions=_open_position_count(positions),
        current_strategy2_metrics={
            "portfolioEquity": equity,
            "strategyMarginUsed": strategy_margin_used,
            "activePositionLegs": _open_position_count(positions),
        },
    ))
    report["capturedAtMs"] = now_ms
    report["readOnly"] = True
    report["marketCount"] = len(markets)
    return report


def advance_focus_shadow_state(report: dict[str, Any], previous: FocusState, *, leverage: int,
                               timestamp_ms: int) -> FocusState:
    """Apply an immediate theoretical fill to shadow state only; never exchange state."""
    decision = report.get("decision") if isinstance(report.get("decision"), dict) else {}
    kind = str(decision.get("kind", "HOLD"))
    symbol = str(decision.get("symbol", previous.active_pair)).upper()
    ranking = report.get("ranking") if isinstance(report.get("ranking"), list) else []
    row = next((x for x in ranking if isinstance(x, dict) and str(x.get("symbol", "")).upper() == symbol), None)
    price = _f(row.get("price")) if row else 0.0
    state_raw = report.get("state") if isinstance(report.get("state"), dict) else {}
    planned = focus_state_from_mapping(state_raw) if state_raw else previous
    performance = report.get("performance") if isinstance(report.get("performance"), dict) else {}
    portfolio_base = previous.theoretical_portfolio_value or _f(performance.get("portfolioEquity"))
    if kind in {"OPEN", "DCA"} and price > 0:
        base = replace(planned, active_pair=symbol, theoretical_portfolio_value=portfolio_base)
        return apply_focus_buy(base, price=price, notional=_f(decision.get("notional")), leverage=leverage,
            timestamp_ms=timestamp_ms, is_dca=(kind == "DCA"), reason=str(decision.get("reason", "")))
    if kind == "PARTIAL_TP" and price > 0 and previous.total_quantity > 0:
        fraction=max(0.0,min(1.0,_f(decision.get("close_fraction"))))
        close_qty=previous.total_quantity*fraction
        realized=(price-previous.weighted_entry)*close_qty if previous.weighted_entry>0 else 0.0
        remaining=max(0.0,1.0-fraction)
        return replace(planned,total_quantity=previous.total_quantity*remaining,
            total_notional=previous.total_notional*remaining,used_margin=previous.used_margin*remaining,
            focus_budget_used=previous.focus_budget_used*remaining,realized_pnl=previous.realized_pnl+realized,
            theoretical_portfolio_value=portfolio_base+realized,last_action="PARTIAL_TP",
            last_reason=str(decision.get("reason", "partial winst theoretisch genomen")))
    if kind == "CLOSE":
        pnl = (price - previous.weighted_entry) * previous.total_quantity if price > 0 and previous.weighted_entry > 0 else 0.0
        return reset_after_full_exit(planned, realized_pnl=pnl, theoretical_portfolio_value=portfolio_base+pnl)
    return planned
