from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_UP
from datetime import datetime, timezone
from typing import Any
import hashlib, math, time

from aster_close_guard import CloseEvidence, AsterCloseBlocked
from aster_execution import NewPositionLeverageBlocked, PairExecutionPlan, execute_leg_once, is_definite_contract_rejection, plan_pair
from aster_gateway import ContractRules, PositionSide
from aster_leverage_tiers import bracket_rows as tier_bracket_rows, resolve_entry, resolve_dca, tier_preview

ENGINE = "multi_bb_v1"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    return int(_f(value, default))


@dataclass(frozen=True)
class MultiBbConfig:
    engine: str = ENGINE
    name: str = "Aster Multi DCA"
    version: int = 1
    mode: str = "live"
    universe_top_n: int = 30
    maximum_positions: int = 30
    long_slots: int = 20
    short_slots: int = 10
    minimum_leverage: int = 50
    entry_margin_usd: float = 5.0
    entry_notional_usd: float = 250.0
    entry_sizing_mode: str = "notional"
    dca_distance: float = .003
    dca_margin_usd: float = 2.0
    max_dca: int = 3
    unlimited_dca: bool = False
    take_profit: float = .015
    take_profit_enabled: bool = True
    asymmetric_hedge_enabled: bool = False
    short_start_multiplier: float = 5.0
    manual_symbol_selection_enabled: bool = False
    manual_symbols: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "MultiBbConfig":
        raw = raw or {}
        minimum_leverage=_i(raw.get("minimumLeverage", raw.get("leverage")), 50)
        entry_margin_usd=_f(raw.get("entryMarginUsd", raw.get("baseMarginUsd")), 5.0)
        entry_notional_usd=_f(raw.get("entryNotionalUsd", raw.get("baseNotional")), entry_margin_usd * max(1, minimum_leverage))
        asymmetric_enabled=bool(raw.get("asymmetricHedgeModeEnabled", False))
        manual_enabled=bool(raw.get("manualSymbolSelectionEnabled", False)) and not asymmetric_enabled
        entry_sizing_mode=str(raw.get("entrySizingMode", "margin" if manual_enabled or asymmetric_enabled else "notional")).lower().strip()
        manual_rows=raw.get("manualSymbols") if isinstance(raw.get("manualSymbols"), list) else []
        manual_symbols=[]
        seen=set()
        for item in manual_rows:
            if not isinstance(item, dict): continue
            symbol=str(item.get("symbol", "")).upper().strip(); side=str(item.get("side", "")).upper().strip()
            if not symbol or side not in {"LONG", "SHORT"} or symbol in seen: continue
            seen.add(symbol); manual_symbols.append((symbol, side))
        cfg = cls(
            engine=str(raw.get("engine", raw.get("strategyKind", ENGINE))),
            name=str(raw.get("name", "Aster Multi DCA")),
            version=max(1, _i(raw.get("version"), 1)),
            mode="paper" if str(raw.get("mode", "live")).lower() == "paper" else "live",
            universe_top_n=_i(raw.get("universeTopN"), 30),
            maximum_positions=_i(raw.get("maximumPositions", raw.get("maximumPairs")), 30),
            long_slots=_i(raw.get("longSlots", raw.get("maximumLongPositions")), 20),
            short_slots=_i(raw.get("shortSlots", raw.get("maximumShortPositions")), 10),
            minimum_leverage=minimum_leverage,
            entry_margin_usd=entry_margin_usd,
            entry_notional_usd=entry_notional_usd,
            entry_sizing_mode=entry_sizing_mode,
            dca_distance=_f(raw.get("dcaDistance", raw.get("longDcaDistance")), .003),
            dca_margin_usd=_f(raw.get("dcaMarginUsd"), 2.0),
            max_dca=_i(raw.get("maxDca", raw.get("longMaxDca")), 3),
            unlimited_dca=bool(raw.get("unlimitedDca", False)),
            take_profit=_f(raw.get("takeProfit"), .015),
            take_profit_enabled=bool(raw.get("takeProfitEnabled", True)),
            asymmetric_hedge_enabled=asymmetric_enabled,
            short_start_multiplier=_f(raw.get("shortStartMultiplier"), 5.0),
            manual_symbol_selection_enabled=manual_enabled,
            manual_symbols=tuple(manual_symbols),
        )
        return cfg.validated()

    def validated(self) -> "MultiBbConfig":
        if self.engine != ENGINE: raise ValueError("Alleen de nieuwe Multi BB-strategie is toegestaan")
        if not 1 <= self.universe_top_n <= 200: raise ValueError("Top-N moet tussen 1 en 200 liggen")
        maximum_capacity = 200 if self.manual_symbol_selection_enabled else (self.universe_top_n * 2 if self.asymmetric_hedge_enabled else self.universe_top_n)
        if not 1 <= self.maximum_positions <= maximum_capacity: raise ValueError("Max posities overschrijdt de beschikbare marktcapaciteit")
        if self.long_slots < 0 or self.short_slots < 0 or self.long_slots + self.short_slots != self.maximum_positions:
            raise ValueError("LONG + SHORT slots moet exact gelijk zijn aan max posities")
        if not 1 <= self.minimum_leverage <= 300: raise ValueError("Minimum leverage moet tussen 1x en 300x liggen")
        if self.entry_margin_usd <= 0 or self.entry_notional_usd <= 0 or self.dca_margin_usd <= 0: raise ValueError("Entry-bedrag en DCA-margin moeten positief zijn")
        if self.entry_sizing_mode not in {"notional", "margin"}: raise ValueError("Entry sizing mode is ongeldig")
        if not .0001 <= self.dca_distance <= .50: raise ValueError("DCA-afstand is ongeldig")
        if self.max_dca < 0: raise ValueError("Max DCA mag niet negatief zijn")
        if not math.isfinite(self.take_profit) or self.take_profit <= 0: raise ValueError("Take Profit moet een positief eindig percentage zijn")
        if not math.isfinite(self.short_start_multiplier) or not 1 <= self.short_start_multiplier <= 10: raise ValueError("Short start-multiplier moet tussen 1x en 10x liggen")
        if self.asymmetric_hedge_enabled and (self.long_slots != self.short_slots or self.maximum_positions != self.long_slots * 2):
            raise ValueError("Asymmetrische modus gebruikt uitsluitend gelijke gekoppelde LONG+SHORT-paren")
        if self.manual_symbol_selection_enabled and not self.manual_symbols:
            raise ValueError("Selecteer minimaal één munt wanneer Zelf munten kiezen aan staat")
        if len(self.manual_symbols) > 200: raise ValueError("Maximaal 200 handmatig gekozen munten")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {
            "engine": ENGINE, "strategyKind": ENGINE, "name": self.name, "version": self.version, "mode": self.mode,
            "universeTopN": self.universe_top_n, "maximumPositions": self.maximum_positions,
            "longSlots": self.long_slots, "shortSlots": self.short_slots, "minimumLeverage": self.minimum_leverage,
            "entryMarginUsd": self.entry_margin_usd, "entryNotionalUsd": self.entry_notional_usd, "entrySizingMode": self.entry_sizing_mode, "dcaDistance": self.dca_distance,
            "dcaMarginUsd": self.dca_margin_usd, "maxDca": self.max_dca, "unlimitedDca": self.unlimited_dca, "takeProfit": self.take_profit, "takeProfitEnabled": self.take_profit_enabled,
            "asymmetricHedgeModeEnabled": self.asymmetric_hedge_enabled, "shortStartMultiplier": self.short_start_multiplier,
            "entryMode": "immediate_fill", "marginMode": "cross", "autoRestart": True,
            "manualSymbolSelectionEnabled": self.manual_symbol_selection_enabled,
            "manualSymbols": [{"symbol": symbol, "side": side} for symbol, side in self.manual_symbols],
        }



def position_action_preview(*, row: dict[str, Any], state: dict[str, Any], settings: MultiBbConfig, account_equity: float = 0.0) -> dict[str, Any]:
    """Expose the exact next Strategy 2 DCA/TP levels used by the execution engine."""
    side = str(row.get("positionSide", "")).upper()
    entry = _f(row.get("entryPrice"))
    mark = _f(row.get("markPrice"), entry)
    qty = abs(_f(row.get("positionAmt")))
    if side not in {"LONG", "SHORT"} or entry <= 0 or mark <= 0 or qty <= 0:
        return {}
    tp_price = entry * (1 + settings.take_profit if side == "LONG" else 1 - settings.take_profit) if settings.take_profit_enabled else None
    tp_distance_usd = abs(tp_price - mark) if tp_price is not None else None
    tp_distance_pct = tp_distance_usd / mark * 100 if tp_distance_usd is not None else None
    expected_pnl_at_tp = (((tp_price - entry) if side == "LONG" else (entry - tp_price)) * qty) if tp_price is not None else None
    current_pnl = ((mark - entry) if side == "LONG" else (entry - mark)) * qty
    portfolio_value_at_tp = account_equity + (expected_pnl_at_tp - current_pnl) if account_equity > 0 and expected_pnl_at_tp is not None else None
    dca_count = _i(state.get("dcaCount"))
    anchor = _f(state.get("lastBotFillPrice"), entry)
    dca_allowed = settings.unlimited_dca or dca_count < settings.max_dca
    next_dca_price = anchor * (1 - settings.dca_distance if side == "LONG" else 1 + settings.dca_distance) if dca_allowed and anchor > 0 else None
    next_dca_distance_usd = abs(next_dca_price - mark) if next_dca_price else None
    next_dca_distance_pct = next_dca_distance_usd / mark * 100 if next_dca_distance_usd is not None else None
    return {
        "takeProfitEnabled": settings.take_profit_enabled,
        "takeProfitPct": settings.take_profit * 100 if settings.take_profit_enabled else None,
        "tpPrice": tp_price,
        "tpDistanceUsd": tp_distance_usd,
        "tpDistancePct": tp_distance_pct,
        "expectedPnlAtTp": expected_pnl_at_tp,
        "portfolioValueAtTp": portfolio_value_at_tp,
        "nextDcaPrice": next_dca_price,
        "nextDcaDistanceUsd": next_dca_distance_usd,
        "nextDcaDistancePct": next_dca_distance_pct,
        "nextDcaNumber": dca_count + 1 if next_dca_price else None,
        "unlimitedDca": settings.unlimited_dca,
    }


def _brackets(payload: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    for row in payload or []:
        if str(row.get("symbol", "")).upper() == symbol.upper(): return list(row.get("brackets") or [])
    if payload and all("initialLeverage" in row for row in payload): return list(payload)
    return []


def max_contract_leverage(payload: list[dict[str, Any]], symbol: str) -> int:
    rows = _brackets(payload, symbol)
    return max((_i(row.get("initialLeverage")) for row in rows), default=0)


def rank_top_volume(tickers: list[dict[str, Any]], exchange_info: dict[str, Any], top_n: int) -> list[dict[str, Any]]:
    allowed = {str(row.get("symbol", "")).upper() for row in exchange_info.get("symbols", [])
               if str(row.get("quoteAsset", "USDT")).upper() == "USDT" and str(row.get("status", "TRADING")).upper() == "TRADING"}
    ranked = []
    for row in tickers:
        symbol = str(row.get("symbol", "")).upper()
        if symbol not in allowed or not symbol.endswith("USDT"): continue
        volume = _f(row.get("quoteVolume", row.get("quoteVolume24h")))
        if volume > 0: ranked.append({"symbol": symbol, "quoteVolume": volume})
    ranked.sort(key=lambda x: (-x["quoteVolume"], x["symbol"]))
    return ranked[:top_n]


def _plan_new(client: Any, row: dict[str, Any], price: float, *, entry_margin_usd: float, entry_notional_usd: float, entry_sizing_mode: str, minimum_leverage: int) -> tuple[PairExecutionPlan, dict[str, Any]]:
    symbol = str(row.get("symbol", "")).upper(); payload = client.leverage_brackets(symbol); rows = tier_bracket_rows(payload, symbol)
    resolved = resolve_entry(payload, symbol, configured_minimum=minimum_leverage,
        entry_margin_usd=entry_margin_usd, entry_notional_usd=entry_notional_usd, entry_sizing_mode=entry_sizing_mode)
    plan = plan_pair(row, rows, price, resolved["orderNotional"], accepted_leverage=int(resolved["leverage"]))
    return plan, resolved


def _plan_asymmetric_entries(client: Any, row: dict[str, Any], price: float, settings: MultiBbConfig) -> tuple[PairExecutionPlan, PairExecutionPlan, dict[str, Any], dict[str, Any]]:
    """Plan one same-symbol LONG+SHORT pair at one common leverage.

    In margin sizing the SHORT uses exactly ``short_start_multiplier`` times the
    LONG start margin. Brand-new pairs never fall below the configured minimum.
    """
    symbol = str(row.get("symbol", "")).upper(); payload = client.leverage_brackets(symbol); rows = tier_bracket_rows(payload, symbol)
    levels = sorted({_i(x.get("initialLeverage")) for x in rows if _i(x.get("initialLeverage")) >= settings.minimum_leverage}, reverse=True)
    if not levels:
        maximum=max((_i(x.get("initialLeverage")) for x in rows),default=0)
        raise ValueError(f"{symbol}: max {maximum}x < minimum {settings.minimum_leverage}x")
    last_error: Exception | None = None
    for leverage in levels:
        if settings.entry_sizing_mode == "margin":
            long_notional=settings.entry_margin_usd * leverage
            short_notional=settings.entry_margin_usd * settings.short_start_multiplier * leverage
        else:
            long_notional=settings.entry_notional_usd
            short_notional=settings.entry_notional_usd * settings.short_start_multiplier
        try:
            long_plan = plan_pair(row, rows, price, long_notional, accepted_leverage=leverage)
            short_plan = plan_pair(row, rows, price, short_notional, accepted_leverage=leverage, existing_contract_notional=long_plan.notional_per_leg)
            long_resolved={"leverage":leverage,"orderNotional":float(long_plan.notional_per_leg),"projectedNotional":float(long_plan.notional_per_leg),
                "exchangeMaxLeverage":leverage,"configuredMinimum":settings.minimum_leverage,"forcedBelowConfiguredMinimum":False}
            short_resolved={"leverage":leverage,"orderNotional":float(short_plan.notional_per_leg),"projectedNotional":float(long_plan.notional_per_leg+short_plan.notional_per_leg),
                "exchangeMaxLeverage":leverage,"configuredMinimum":settings.minimum_leverage,"forcedBelowConfiguredMinimum":False}
            return long_plan, short_plan, long_resolved, short_resolved
        except Exception as exc:
            last_error = exc
    raise ValueError(f"{symbol}: geen gezamenlijke leverage/capaciteit voor asymmetrische LONG+SHORT boven minimum {settings.minimum_leverage}x") from last_error


def _asymmetric_flags(settings: MultiBbConfig, *, side: str, state_row: dict[str, Any], state: dict[str, Any], pmap: dict[str, Any]) -> dict[str, bool]:
    active = settings.asymmetric_hedge_enabled and bool(state_row.get("asymmetricHedge"))
    paired_short = str(state_row.get("pairedShortKey") or "")
    paired_long = str(state_row.get("pairedLongKey") or "")
    short_open = bool(paired_short and paired_short in pmap)
    pending_short = bool(state_row.get("pairedShortPending"))
    long_state = state.get(paired_long) if paired_long else None
    long_maxed = bool(active and side == "SHORT" and isinstance(long_state, dict) and not settings.unlimited_dca and _i(long_state.get("dcaCount")) >= settings.max_dca)
    return {
        "active": active,
        "blockLongTp": bool(active and side == "LONG" and (short_open or pending_short)),
        "disableShortTp": bool(active and side == "SHORT"),
        "closeShort": long_maxed,
        "allowShortDca": bool(not long_maxed),
    }


def _plan_add(client: Any, row: dict[str, Any], price: float, margin: float, leverage: int, existing_notional: float, minimum_leverage: int) -> tuple[PairExecutionPlan, dict[str, Any]]:
    symbol = str(row.get("symbol", "")).upper(); payload = client.leverage_brackets(symbol); rows = tier_bracket_rows(payload, symbol)
    resolved = resolve_dca(payload, symbol, current_notional=existing_notional, current_leverage=leverage,
        dca_margin_usd=margin, configured_minimum=minimum_leverage)
    plan = plan_pair(row, rows, price, resolved["orderNotional"], accepted_leverage=int(resolved["leverage"]), existing_contract_notional=existing_notional)
    return plan, resolved


def leverage_tier_preview(*, client: Any, symbol: str, settings: MultiBbConfig) -> dict[str, Any]:
    symbol = str(symbol).upper().strip(); payload = client.leverage_brackets(symbol)
    positions = _position_map(client.position_risk(symbol)); current = next((row for key, row in positions.items() if key.startswith(symbol + "|")), None)
    mark = _f((current or {}).get("markPrice"), _f((current or {}).get("entryPrice")))
    qty = abs(_f((current or {}).get("positionAmt"))); current_notional = qty * mark if qty > 0 and mark > 0 else 0.0
    current_leverage = max(0, _i((current or {}).get("leverage")))
    preview = tier_preview(payload, symbol, configured_minimum=settings.minimum_leverage,
        entry_margin_usd=settings.entry_margin_usd, entry_notional_usd=settings.entry_notional_usd,
        entry_sizing_mode=settings.entry_sizing_mode, dca_margin_usd=settings.dca_margin_usd,
        current_notional=current_notional, current_leverage=current_leverage)
    if current is None and preview.get("entryPlan"):
        info = client.public_exchange_info(); row = next((x for x in info.get("symbols", []) if str(x.get("symbol", "")).upper() == symbol), None)
        prices = {str(x.get("symbol", "")).upper(): _f(x.get("price")) for x in client.ticker_prices()}
        price = prices.get(symbol, 0.0)
        if row is not None and price > 0:
            rules = ContractRules.from_exchange_info(row); step = rules.market_quantity_step
            minimum_qty = max(rules.market_min_quantity, rules.min_quantity)
            if step > 0:
                minimum_qty = (minimum_qty / step).to_integral_value(rounding=ROUND_UP) * step
                if rules.min_notional > 0:
                    by_notional = (rules.min_notional / Decimal(str(price)) / step).to_integral_value(rounding=ROUND_UP) * step
                    minimum_qty = max(minimum_qty, by_notional)
            minimum_notional = minimum_qty * Decimal(str(price))
            leverage = max(1, _i(preview["entryPlan"].get("leverage")))
            minimum_margin = minimum_notional / Decimal(leverage)
            configured_margin = Decimal(str(settings.entry_margin_usd))
            suggested_margin = (minimum_margin * Decimal("100")).to_integral_value(rounding=ROUND_UP) / Decimal("100")
            preview.update({
                "minimumExecutableNotionalUsd": float(minimum_notional),
                "minimumEntryMarginUsd": float(minimum_margin),
                "suggestedEntryMarginUsd": float(suggested_margin),
                "configuredEntryMarginUsd": float(configured_margin),
                "entryOrderValid": settings.entry_sizing_mode != "margin" or configured_margin >= minimum_margin,
            })
    return preview


def _minimum_entry_margin(row: dict[str, Any], price: float, leverage: int) -> float | None:
    """Return the exchange-rule minimum margin for a market order."""
    try:
        rules = ContractRules.from_exchange_info(row)
        step = rules.market_quantity_step
        minimum_qty = max(rules.market_min_quantity, rules.min_quantity)
        if step > 0:
            minimum_qty = (minimum_qty / step).to_integral_value(rounding=ROUND_UP) * step
            if rules.min_notional > 0:
                by_notional = (rules.min_notional / Decimal(str(price)) / step).to_integral_value(rounding=ROUND_UP) * step
                minimum_qty = max(minimum_qty, by_notional)
        if minimum_qty <= 0 or price <= 0 or leverage <= 0:
            return None
        return float(minimum_qty * Decimal(str(price)) / Decimal(leverage))
    except Exception:
        return None


def _manual_reopen_boundary(client: Any, symbol: str, side: str, state: dict[str, Any]) -> bool:
    """Return True only when Aster fills prove the old cycle went flat and reopened."""
    start = _i(state.get("cycleStartedAtMs"))
    if start <= 0:
        return False
    try:
        fills = sorted(client.user_trades(symbol, start_time=max(0, start - 1000), limit=1000), key=lambda x: _i(x.get("time", x.get("timestamp", x.get("timestampMs")))))
    except Exception:
        return False
    running = 0.0
    was_open = False
    went_flat = False
    for fill in fills:
        position_side = str(fill.get("positionSide", side)).upper()
        if position_side not in {side, "BOTH"}:
            continue
        trade_side = str(fill.get("side", "")).upper()
        qty = abs(_f(fill.get("qty", fill.get("quantity", fill.get("executedQty")))))
        if qty <= 0 or trade_side not in {"BUY", "SELL"}:
            continue
        delta = qty if (side == "LONG" and trade_side == "BUY") or (side == "SHORT" and trade_side == "SELL") else -qty
        running = max(0.0, running + delta)
        if running > 1e-12:
            if went_flat:
                return True
            was_open = True
        elif was_open:
            went_flat = True
    return False


def _infer_external_add_fill_price(*, previous_qty: float, previous_entry: float, new_qty: float, new_entry: float, fallback: float) -> float:
    """Infer the effective fill price of an external same-side position increase.

    Aster positionRisk exposes the new weighted entry immediately.  Using the
    weighted-entry identity gives the exact effective price for the added qty
    even when the fill endpoint is temporarily unavailable.
    """
    delta = new_qty - previous_qty
    if delta > 1e-12 and previous_qty > 0 and previous_entry > 0 and new_entry > 0:
        inferred = (new_entry * new_qty - previous_entry * previous_qty) / delta
        if math.isfinite(inferred) and inferred > 0:
            return inferred
    if new_entry > 0:
        return new_entry
    return fallback if fallback > 0 else previous_entry


def _recovery_anchor(state: dict[str, Any], *, entry: float) -> float:
    """Deterministic DCA anchor priority used by reconciliation."""
    for field in ("lastDcaFillPrice", "lastManualFillPrice", "lastBotFillPrice", "strategyAnchorPrice"):
        value = _f(state.get(field))
        if value > 0:
            return value
    return entry if _i(state.get("dcaCount")) == 0 and entry > 0 else 0.0


def _position_map(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {}
    for row in positions:
        qty = abs(_f(row.get("positionAmt")))
        side = str(row.get("positionSide", "")).upper(); symbol = str(row.get("symbol", "")).upper()
        if qty > 0 and side in {"LONG", "SHORT"}: out[f"{symbol}|{side}"] = row
    return out


def _next_entry_side(*, long_count: int, short_count: int, long_slots: int, short_slots: int) -> str:
    """Keep new entries proportionally balanced across configured LONG/SHORT seats.

    Comparing fill ratios prevents the old LONG-first behavior from consuming
    all high-ranked eligible symbols before SHORT gets a chance to open.
    """
    long_need=max(0,long_slots-long_count);short_need=max(0,short_slots-short_count)
    if long_need<=0:return "SHORT" if short_need>0 else ""
    if short_need<=0:return "LONG"
    long_fill=long_count/max(1,long_slots);short_fill=short_count/max(1,short_slots)
    return "LONG" if long_fill<=short_fill else "SHORT"


def _close_evidence(client: Any, uid: str, state: dict[str, Any], row: dict[str, Any], side: str, mark: float) -> CloseEvidence:
    symbol = str(row.get("symbol", "")).upper(); qty = abs(_f(row.get("positionAmt"))); entry = _f(row.get("entryPrice"))
    start = _i(state.get("cycleStartedAtMs"), int(time.time() * 1000) - 7 * 86400_000)
    fills = client.user_trades(symbol, start_time=start, limit=1000)
    income = client.income_history(symbol=symbol, start_time=start, limit=1000)
    entry_fees = sum(abs(_f(x.get("commission"))) for x in fills)
    funding = sum(_f(x.get("income")) for x in income if str(x.get("incomeType", "")).upper() == "FUNDING_FEE")
    gross = (mark - entry) * qty if side == "LONG" else (entry - mark) * qty
    notional = mark * qty
    return CloseEvidence(uid, symbol, side, "multi_bb_v1", "POSITION_TP", qty, entry, mark, gross,
                         entry_fees, notional * .0005, funding, notional * .0005,
                         ownership_reliable=True, fills_reliable=True, prices_reliable=True, costs_reliable=True)


def run_multi_bb_step(*, client: Any, ref: Any, raw_state: dict[str, Any], settings: MultiBbConfig, uid: str,
                      account: dict[str, Any], positions: list[dict[str, Any]], open_orders: list[dict[str, Any]],
                      timestamp_ms: int, dry_run: bool = False, order_budget: int | None = None,
                      before_order: Any = None) -> dict[str, Any]:
    budget = max(0, 15 if order_budget is None else int(order_budget)); sent = 0
    state = dict(raw_state.get("multiBbPositions") or {}); pmap = _position_map(positions)
    selected_keys = {f"{symbol}|{side}" for symbol, side in settings.manual_symbols} if settings.manual_symbol_selection_enabled else set()
    reconciled_closed: list[str] = []
    # Explicit user start may adopt already-open exchange positions once. Deployment/config save alone never does this.
    if bool(raw_state.get("multiBbAdoptionPending")):
        symbol_sides: dict[str, set[str]] = {}
        for key in pmap:
            symbol, side = key.split("|", 1); symbol_sides.setdefault(symbol, set()).add(side)
        conflicts = sorted(symbol for symbol, sides in symbol_sides.items() if len(sides) > 1)
        # A pre-existing/manual hedge may legitimately have LONG and SHORT on the
        # same symbol. It must never be auto-adopted because the Multi DCA engine
        # promises one managed side per symbol, but it also must not shut down the
        # whole bot. Keep both legs exchange-truth only, count them toward account
        # capacity below, and fill the remaining slots with other symbols.
        conflict_keys = {f"{symbol}|{side}" for symbol in conflicts for side in ("LONG", "SHORT")}
        if conflicts and not dry_run:
            ref.set({"phase": "START_PENDING",
                     "lastReason": "Bestaande LONG/SHORT-hedge blijft handmatig geïsoleerd; Multi DCA start op overige slots",
                     "multiBbIsolatedSymbols": conflicts, "updatedAt": datetime.now(timezone.utc)}, merge=True)
        for key, row in pmap.items():
            if settings.manual_symbol_selection_enabled and key not in selected_keys: continue
            if key in state or key in conflict_keys: continue
            qty = abs(_f(row.get("positionAmt"))); entry = _f(row.get("entryPrice")); mark = _f(row.get("markPrice"), entry)
            if qty <= 0 or entry <= 0: continue
            state[key] = {"cycleId": hashlib.sha256((uid+key+str(timestamp_ms)).encode()).hexdigest()[:16], "dcaCount": 0,
                "lastBotFillPrice": mark if mark > 0 else entry, "lastKnownQty": qty, "lastKnownEntry": entry,
                "leverage": max(1, _i(row.get("leverage"))), "cycleStartedAtMs": timestamp_ms, "updatedAtMs": timestamp_ms,
                "botManaged": True, "adoptedExisting": True}
    order_keys = {(str(x.get("symbol", "")).upper(), str(x.get("positionSide", "")).upper()) for x in open_orders}
    info = client.public_exchange_info(); info_map = {str(x.get("symbol", "")).upper(): x for x in info.get("symbols", [])}
    prices = {str(x.get("symbol", "")).upper(): _f(x.get("price")) for x in client.ticker_prices()}
    ranked = rank_top_volume(client.ticker_24h(), info, settings.universe_top_n)
    if settings.manual_symbol_selection_enabled:
        candidates = [{"symbol": symbol, "forcedSide": side} for symbol, side in settings.manual_symbols]
    else:
        candidates = ranked
    available = _f(account.get("availableBalance", account.get("availableMargin")))
    actions: list[dict[str, Any]] = []

    # Exchange truth reconciles every already-managed leg.  Same-side external
    # increases are adopted as one manual DCA; decreases remain reconciliation
    # only.  This keeps the strategy/game state aligned with Aster truth.
    for key in list(state):
        row = pmap.get(key)
        if row is None:
            reconciled_closed.append(key); state.pop(key, None); continue
        st = dict(state[key]); qty = abs(_f(row.get("positionAmt"))); entry = _f(row.get("entryPrice")); leverage = max(1, _i(row.get("leverage"), st.get("leverage", 1)))
        symbol = str(row.get("symbol", "")).upper(); side = str(row.get("positionSide", "")).upper()
        previous_qty = abs(_f(st.get("lastKnownQty"))); previous_entry = _f(st.get("lastKnownEntry"))
        qty_delta = qty - previous_qty
        changed = abs(qty_delta) > 1e-12 or abs(entry - previous_entry) > 1e-12
        boundary_check = settings.manual_symbol_selection_enabled and _i(st.get("dcaCount")) > 0 and (bool(raw_state.get("multiBbAdoptionPending")) or not st.get("cycleBoundaryCheckedAtMs") or changed)
        if boundary_check and _manual_reopen_boundary(client, symbol, side, st):
            old_cycle = str(st.get("cycleId", ""))
            st = {"cycleId": hashlib.sha256((uid+key+str(timestamp_ms)).encode()).hexdigest()[:16], "dcaCount": 0,
                "lastBotFillPrice": entry, "lastKnownQty": qty, "lastKnownEntry": entry, "leverage": leverage,
                "cycleStartedAtMs": timestamp_ms, "updatedAtMs": timestamp_ms, "cycleBoundaryCheckedAtMs": timestamp_ms, "botManaged": True}
            actions.append({"kind": "REENTRY_CYCLE_RESET", "key": key, "oldCycleId": old_cycle, "reason": "Aster fills prove prior cycle went flat before this reopen"})
        else:
            # A completed exchange-side increase with no currently open bot order
            # is an explicit external/manual add.  Auto-DCA writes lastKnownQty
            # immediately on confirmation below, so it is idempotently excluded.
            external_add = previous_qty > 0 and qty_delta > 1e-12 and (symbol, side) not in order_keys
            if external_add:
                manual_price = _infer_external_add_fill_price(previous_qty=previous_qty, previous_entry=previous_entry, new_qty=qty, new_entry=entry, fallback=_f(row.get("markPrice"), entry))
                old_count = _i(st.get("dcaCount")); old_next = st.get("nextDcaPrice")
                st.update({
                    "dcaCount": old_count + 1, "lastManualFillPrice": manual_price, "lastDcaFillPrice": manual_price,
                    "lastBotFillPrice": manual_price, "lastManualDcaQty": qty_delta, "lastManualDcaAtMs": timestamp_ms,
                    "manualDcaAdoptedAtMs": timestamp_ms, "manualOrExchangeReconciledAtMs": timestamp_ms,
                })
                action = {"kind": "MANUAL_DCA_DETECTED", "symbol": symbol, "side": side, "cycleId": st.get("cycleId"),
                    "qtyDelta": qty_delta, "fillPrice": manual_price, "oldDcaCount": old_count, "newDcaCount": old_count + 1,
                    "oldNextDcaPrice": old_next, "timestampMs": timestamp_ms}
                actions.append(action)
                if not dry_run:
                    ref.collection("audit").add({"event": "MANUAL_DCA_DETECTED", "user": uid, **{k: v for k, v in action.items() if k != "kind"}, "timestamp": datetime.now(timezone.utc)})
            elif qty_delta < -1e-12:
                actions.append({"kind": "MANUAL_POSITION_DECREASE_RECONCILED", "symbol": symbol, "side": side, "qtyDelta": qty_delta})
                if not dry_run:
                    ref.collection("audit").add({"event": "MANUAL_POSITION_DECREASE_RECONCILED", "user": uid, "symbol": symbol, "side": side, "qtyDelta": qty_delta, "timestamp": datetime.now(timezone.utc)})
            elif changed:
                st["manualOrExchangeReconciledAtMs"] = timestamp_ms
            if boundary_check:
                st["cycleBoundaryCheckedAtMs"] = timestamp_ms

            # Self-heal any managed open position that still has DCA capacity but
            # lost its persisted anchor during restart/deploy/config migration.
            dca_allowed = settings.unlimited_dca or _i(st.get("dcaCount")) < settings.max_dca
            old_anchor = _f(st.get("lastBotFillPrice"))
            recovered_anchor = _recovery_anchor(st, entry=entry) if dca_allowed else old_anchor
            if dca_allowed and old_anchor <= 0 and recovered_anchor > 0:
                st["lastBotFillPrice"] = recovered_anchor
                st["dcaStateRecoveredAtMs"] = timestamp_ms
                actions.append({"kind": "DCA_STATE_RECOVERED", "symbol": symbol, "side": side, "cycleId": st.get("cycleId"), "anchor": recovered_anchor, "reason": "MISSING_DCA_ANCHOR"})
                if not dry_run:
                    ref.collection("audit").add({"event": "DCA_STATE_RECOVERED", "user": uid, "cycleId": st.get("cycleId"), "symbol": symbol, "side": side, "reason": "MISSING_DCA_ANCHOR", "newAnchor": recovered_anchor, "timestamp": datetime.now(timezone.utc)})

            st.update({"lastKnownQty": qty, "lastKnownEntry": entry, "leverage": leverage, "updatedAtMs": timestamp_ms})
        account_equity = _f(account.get("totalMarginBalance", account.get("marginBalance", account.get("equity", account.get("totalWalletBalance")))))
        old_next = _f(st.get("nextDcaPrice"))
        preview = position_action_preview(row=row, state=st, settings=settings, account_equity=account_equity)
        st.update(preview)
        if old_next <= 0 and _f(preview.get("nextDcaPrice")) > 0 and not any(a.get("kind") == "DCA_STATE_RECOVERED" and a.get("symbol") == symbol and a.get("side") == side for a in actions):
            st["dcaStateRecoveredAtMs"] = timestamp_ms
            actions.append({"kind": "DCA_STATE_RECOVERED", "symbol": symbol, "side": side, "cycleId": st.get("cycleId"), "anchor": _f(st.get("lastBotFillPrice"), entry), "reason": "NEXT_DCA_REARMED"})
            if not dry_run:
                ref.collection("audit").add({"event": "DCA_STATE_RECOVERED", "user": uid, "cycleId": st.get("cycleId"), "symbol": symbol, "side": side, "reason": "NEXT_DCA_REARMED", "newNextDcaPrice": preview.get("nextDcaPrice"), "timestamp": datetime.now(timezone.utc)})
        state[key] = st

    for key in reconciled_closed:
        actions.append({"kind": "REENTRY_STATE_CLEARED", "key": key, "reason": "exchange position is flat"})

    # Recover an initial paired SHORT idempotently before either side is allowed to manage DCA/TP.
    if settings.asymmetric_hedge_enabled:
        for key, st0 in list(state.items()):
            if sent >= budget: break
            if not key.endswith("|LONG") or not st0.get("asymmetricHedge") or not st0.get("pairedShortPending"): continue
            long_row = pmap.get(key); symbol = key.split("|", 1)[0]; short_key = f"{symbol}|SHORT"
            if short_key in pmap:
                sr = pmap[short_key]; state[short_key] = {"cycleId": st0.get("cycleId"), "dcaCount": 0, "lastBotFillPrice": _f(sr.get("entryPrice")), "lastKnownQty": abs(_f(sr.get("positionAmt"))), "lastKnownEntry": _f(sr.get("entryPrice")), "leverage": max(1, _i(sr.get("leverage"))), "cycleStartedAtMs": st0.get("cycleStartedAtMs", timestamp_ms), "updatedAtMs": timestamp_ms, "botManaged": True, "asymmetricHedge": True, "pairedLongKey": key, "initialShortMultiplier": settings.short_start_multiplier}
                linked = dict(st0); linked.update({"pairedShortPending": False, "pairedShortOpened": True, "updatedAtMs": timestamp_ms}); state[key] = linked
                actions.append({"kind": "ASYM_SHORT_RECOVERED_FROM_EXCHANGE", "symbol": symbol}); continue
            if long_row is None or symbol not in info_map or prices.get(symbol, 0) <= 0 or len(pmap) >= settings.maximum_positions: continue
            try:
                _, short_plan, _, _ = _plan_asymmetric_entries(client, info_map[symbol], prices[symbol], settings)
                current_lev = max(1, _i(long_row.get("leverage"), short_plan.leverage))
                payload = client.leverage_brackets(symbol); rows = tier_bracket_rows(payload, symbol)
                short_plan = plan_pair(info_map[symbol], rows, prices[symbol], float(short_plan.notional_per_leg), accepted_leverage=current_lev, existing_contract_notional=abs(_f(long_row.get("positionAmt"))) * prices[symbol])
                required_short = float(short_plan.notional_per_leg) / short_plan.leverage
                if available < required_short * 1.05:
                    actions.append({"kind": "ASYM_SHORT_RECOVERY_WAIT", "symbol": symbol, "reason": "INSUFFICIENT_AVAILABLE_MARGIN"}); continue
                actions.append({"kind": "ASYM_SHORT_RECOVERY", "symbol": symbol, "multiplier": settings.short_start_multiplier})
                if not dry_run:
                    recovered = execute_leg_once(client, short_plan, side=PositionSide.SHORT, action="OPEN", id_prefix=f"mbb-asym-short-{st0.get('cycleId')}", confirm=True, new_position_leverage=current_lev, before_submit=before_order)
                    sf = recovered.get("result") or {}; sp = _f(sf.get("avgPrice"), prices[symbol]); sq = _f(sf.get("executedQty"), float(short_plan.quantity))
                    state[short_key] = {"cycleId": st0.get("cycleId"), "dcaCount": 0, "lastBotFillPrice": sp, "lastKnownQty": sq, "lastKnownEntry": sp, "leverage": current_lev, "cycleStartedAtMs": st0.get("cycleStartedAtMs", timestamp_ms), "updatedAtMs": timestamp_ms, "botManaged": True, "asymmetricHedge": True, "pairedLongKey": key, "initialShortMultiplier": settings.short_start_multiplier}
                    linked = dict(state[key]); linked.update({"pairedShortPending": False, "pairedShortOpened": True, "pairedShortOrderConfirmedAtMs": timestamp_ms, "updatedAtMs": timestamp_ms}); state[key] = linked
                    ref.set({"multiBbPositions": state, "lastReason": f"Asymmetrische hedge recovery bevestigd op {symbol}"}, merge=True)
                available -= required_short; sent += 1
            except Exception as exc:
                actions.append({"kind": "ASYM_SHORT_RECOVERY_WAIT", "symbol": symbol, "reason": str(exc)})

    # Management priority: max-LONG-DCA hedge release, then TP, then independent capped DCA.
    for key, st0 in list(state.items()):
        if sent >= budget: break
        row = pmap.get(key)
        if row is None: continue
        symbol, side = key.split("|", 1); mark = _f(row.get("markPrice"), prices.get(symbol, 0)); entry = _f(row.get("entryPrice")); qty = abs(_f(row.get("positionAmt")))
        if mark <= 0 or entry <= 0 or qty <= 0 or (symbol, side) in order_keys: continue
        asym = _asymmetric_flags(settings, side=side, state_row=st0, state=state, pmap=pmap)
        if asym["closeShort"]:
            actions.append({"kind": "ASYM_SHORT_CLOSE", "symbol": symbol, "side": side, "reason": "LONG_MAX_DCA_REACHED", "qty": qty})
            if not dry_run:
                plan = PairExecutionPlan(symbol, Decimal(str(qty)), Decimal(str(qty * mark)), max(1, _i(row.get("leverage"))))
                evidence = _close_evidence(client, uid, st0, row, side, mark)
                try:
                    execute_leg_once(client, plan, side=PositionSide.SHORT, action="CLOSE", id_prefix=f"mbb-asym-close-{hashlib.sha256((uid+key+str(timestamp_ms)).encode()).hexdigest()[:12]}", confirm=True,
                                     close_evidence=evidence, before_submit=before_order)
                except AsterCloseBlocked as exc:
                    actions.append({"kind": "ASYM_SHORT_CLOSE_BLOCKED", "symbol": symbol, "side": side, "reason": str(exc)})
                    continue
                fresh = _position_map(client.position_risk(symbol))
                if key in fresh: raise RuntimeError(f"{key}: asymmetrische SHORT-close niet flat bevestigd")
                state.pop(key, None); pmap.pop(key, None)
                paired_long_key = str(st0.get("pairedLongKey") or "")
                if paired_long_key in state:
                    linked = dict(state[paired_long_key]); linked.update({"pairedShortPending": False, "pairedShortClosedAtMs": timestamp_ms, "longTpBlocked": False, "updatedAtMs": timestamp_ms}); state[paired_long_key] = linked
                ref.set({"multiBbPositions": state, "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING", "lastReason": f"Asymmetrische hedge: SHORT {symbol} volledig gesloten bij LONG max DCA"}, merge=True)
                ref.collection("audit").add({"event": "MULTI_BB_ASYM_SHORT_CLOSE", "symbol": symbol, "reason": "LONG_MAX_DCA_REACHED", "timestamp": datetime.now(timezone.utc)})
            sent += 1; continue
        tp_price = entry * (1 + settings.take_profit if side == "LONG" else 1 - settings.take_profit)
        tp_due = settings.take_profit_enabled and not asym["blockLongTp"] and not asym["disableShortTp"] and (mark >= tp_price if side == "LONG" else mark <= tp_price)
        if tp_due:
            actions.append({"kind": "TP", "symbol": symbol, "side": side, "mark": mark, "entry": entry, "target": tp_price})
            if not dry_run:
                plan = PairExecutionPlan(symbol, Decimal(str(qty)), Decimal(str(qty * mark)), max(1, _i(row.get("leverage"))))
                evidence = _close_evidence(client, uid, st0, row, side, mark)
                execute_leg_once(client, plan, side=PositionSide(side), action="CLOSE", id_prefix=f"mbb-tp-{hashlib.sha256((uid+key+str(timestamp_ms)).encode()).hexdigest()[:12]}", confirm=True,
                                 close_evidence=evidence, before_submit=before_order)
                fresh = _position_map(client.position_risk(symbol))
                if key in fresh: raise RuntimeError(f"{key}: TP-close niet flat bevestigd")
                state.pop(key, None); pmap.pop(key, None)
                ref.set({"multiBbPositions": state, "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                         "lastReason": "Multi DCA actief; slot na TP vrijgegeven"}, merge=True)
                ref.collection("audit").add({"event": "MULTI_BB_TP", "symbol": symbol, "side": side, "target": tp_price, "timestamp": datetime.now(timezone.utc)})
            sent += 1; continue
        if asym["active"] and side == "LONG" and st0.get("pairedShortPending"):
            actions.append({"kind": "ASYM_HEDGE_PENDING", "symbol": symbol, "side": side, "reason": "INITIAL_SHORT_NOT_CONFIRMED"}); continue
        if asym["active"] and side == "SHORT" and not asym["allowShortDca"]: continue
        # Never stack an automatic DCA in the same reconciliation tick in which
        # an external/manual add was adopted.  The next tick evaluates normally.
        if _i(st0.get("manualDcaAdoptedAtMs")) == timestamp_ms:
            actions.append({"kind": "DCA_REARMED_AFTER_MANUAL", "symbol": symbol, "side": side, "nextDcaPrice": st0.get("nextDcaPrice")})
            continue
        dca_count = _i(st0.get("dcaCount")); anchor = _recovery_anchor(st0, entry=entry)
        if (not settings.unlimited_dca and dca_count >= settings.max_dca) or anchor <= 0: continue
        trigger = anchor * (1 - settings.dca_distance if side == "LONG" else 1 + settings.dca_distance)
        due = mark <= trigger if side == "LONG" else mark >= trigger
        if not due: continue
        row_info = info_map.get(symbol); leverage = max(1, _i(row.get("leverage")))
        if row_info is None: continue
        try: plan, tier = _plan_add(client, row_info, mark, settings.dca_margin_usd, leverage, qty * mark, settings.minimum_leverage)
        except Exception as exc:
            actions.append({"kind": "DCA_BLOCKED", "symbol": symbol, "side": side, "reason": str(exc)}); continue
        required = float(tier["additionalMarginRequired"])
        if available < required * 1.05:
            actions.append({"kind": "DCA_MARGIN_WAIT", "symbol": symbol, "side": side,
                "reason": "INSUFFICIENT_MARGIN_FOR_TIER_LEVERAGE_REDUCTION" if tier["tierReduction"] else "INSUFFICIENT_AVAILABLE_MARGIN",
                "requiredMargin": required, "targetLeverage": tier["leverage"]}); continue
        actions.append({"kind": "DCA", "symbol": symbol, "side": side, "number": dca_count + 1, "trigger": trigger,
            "leverage": tier["leverage"], "previousLeverage": tier["previousLeverage"], "tierReduction": tier["tierReduction"],
            "projectedNotional": tier["projectedNotional"]})
        if not dry_run:
            try:
                result = execute_leg_once(client, plan, side=PositionSide(side), action="OPEN", id_prefix=f"mbb-dca-{hashlib.sha256((uid+key+str(dca_count+1)+str(timestamp_ms)).encode()).hexdigest()[:12]}", confirm=True,
                                          new_position_leverage=int(tier["leverage"]), allow_existing_contract_leverage_change=True, before_submit=before_order)
            except Exception as exc:
                if not is_definite_contract_rejection(exc): raise
                actions.append({"kind": "DCA_BLOCKED", "symbol": symbol, "side": side, "reason": str(exc)})
                continue
            fill = result.get("result") or {}; fill_price = _f(fill.get("avgPrice"), mark); fill_qty = abs(_f(fill.get("executedQty"), float(plan.quantity)))
            new_qty = qty + fill_qty
            new_entry = ((entry * qty) + (fill_price * fill_qty)) / new_qty if new_qty > 0 else entry
            st = dict(st0); st.update({"dcaCount": dca_count + 1, "lastBotFillPrice": fill_price, "lastDcaFillPrice": fill_price,
                "lastKnownQty": new_qty, "lastKnownEntry": new_entry, "lastBotDcaAtMs": timestamp_ms, "updatedAtMs": timestamp_ms,
                "leverage": int(tier["leverage"]), "lastTierReductionAtMs": timestamp_ms if tier["tierReduction"] else st0.get("lastTierReductionAtMs")}); state[key] = st
            ref.set({"multiBbPositions": state, "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                     "lastReason": f"Multi DCA actief; DCA {dca_count + 1} bevestigd op {symbol} @ {int(tier['leverage'])}x"}, merge=True)
            ref.collection("audit").add({"event": "MULTI_BB_DCA", "symbol": symbol, "side": side, "dcaNumber": dca_count + 1,
                "previousLeverage": tier["previousLeverage"], "leverage": tier["leverage"], "tierReduction": tier["tierReduction"],
                "projectedNotional": tier["projectedNotional"], "timestamp": datetime.now(timezone.utc)})
        available -= required; sent += 1

    active = _position_map(client.position_risk()) if sent and not dry_run else pmap
    active_symbols = {k.split("|", 1)[0] for k in active}
    account_position_count = len(active)
    strategy_active_keys = {key for key in active if key in state or (settings.manual_symbol_selection_enabled and key in selected_keys)}
    long_count = sum(1 for k in strategy_active_keys if k.endswith("|LONG")); short_count = sum(1 for k in strategy_active_keys if k.endswith("|SHORT"))
    active_pair_count = sum(1 for key, row in state.items() if key.endswith("|LONG") and row.get("asymmetricHedge") and key in active and (row.get("pairedShortPending") or str(row.get("pairedShortKey") or "") in active))
    legacy_position_count = max(0, len(strategy_active_keys) - active_pair_count * 2) if settings.asymmetric_hedge_enabled else 0
    if settings.asymmetric_hedge_enabled:
        # Gekoppelde-parencapaciteit geldt uitsluitend voor NIEUWE asymmetrische cycli.
        # Bestaande Strategy-2 posities blijven intact en mogen de nieuwe pair allocator niet blokkeren.
        pair_need = max(0, settings.long_slots - active_pair_count)
        long_need = pair_need; short_need = pair_need
        account_remaining_capacity = max(0, 50 - account_position_count)
    else:
        pair_need = 0
        long_need = max(0, settings.long_slots - long_count); short_need = max(0, settings.short_slots - short_count)
        account_remaining_capacity = max(0, settings.maximum_positions - account_position_count)

    # New seats: fill immediately from Top-N volume after leverage/order/margin checks.
    scanned_candidates = 0
    executable_candidates = 0
    minimum_margin_rejections: list[float] = []
    for ranked_row in candidates:
        if sent >= budget or account_remaining_capacity <= 0 or (long_need <= 0 and short_need <= 0): break
        scanned_candidates += 1
        symbol = ranked_row["symbol"]
        if symbol in active_symbols or symbol not in info_map or prices.get(symbol, 0) <= 0: continue
        try:
            bracket_payload = client.leverage_brackets(symbol); maximum = max_contract_leverage(bracket_payload, symbol)
        except Exception as exc:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": f"leverage-data: {exc}"}); continue
        if maximum <= 0:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": "SYMBOL_LEVERAGE_DATA_UNAVAILABLE"}); continue
        if maximum < settings.minimum_leverage:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": f"MAX_LEVERAGE_BELOW_MINIMUM: {maximum}x < {settings.minimum_leverage}x"}); continue
        if settings.asymmetric_hedge_enabled:
            # Exclusive paired mode: the old independent LONG/SHORT allocator is disabled.
            # Every new scanner candidate is exactly one same-symbol LONG+SHORT pair.
            if long_need <= 0 or short_need <= 0:
                break
            side = "LONG"
        elif settings.manual_symbol_selection_enabled:
            side = str(ranked_row.get("forcedSide", "")).upper()
            if side == "LONG" and long_need <= 0: continue
            if side == "SHORT" and short_need <= 0: continue
            if side not in {"LONG", "SHORT"}: continue
        else:
            side = _next_entry_side(long_count=long_count,short_count=short_count,long_slots=settings.long_slots,short_slots=settings.short_slots)
            if not side: break
        paired = bool(settings.asymmetric_hedge_enabled)
        if paired and (short_need <= 0 or account_remaining_capacity < 2 or budget - sent < 2):
            actions.append({"kind": "ASYM_PAIR_WAIT", "symbol": symbol, "reason": "SHORT_SLOT_OR_ACCOUNT_CAPACITY_REQUIRED"}); continue
        try:
            if paired:
                plan, short_plan, tier, short_tier = _plan_asymmetric_entries(client, info_map[symbol], prices[symbol], settings)
            else:
                plan, tier = _plan_new(client, info_map[symbol], prices[symbol], entry_margin_usd=settings.entry_margin_usd, entry_notional_usd=settings.entry_notional_usd, entry_sizing_mode=settings.entry_sizing_mode, minimum_leverage=settings.minimum_leverage)
                short_plan = None; short_tier = None
        except Exception as exc:
            reason = str(exc)
            required_margin = _minimum_entry_margin(info_map[symbol], prices[symbol], maximum)
            action = {"kind": "ENTRY_SKIP", "symbol": symbol, "reason": reason}
            if "minimale exchangeorder" in reason and required_margin is not None:
                action["minimumEntryMarginUsd"] = required_margin
                minimum_margin_rejections.append(required_margin)
            actions.append(action); continue
        executable_candidates += 1
        required = float(plan.notional_per_leg) / plan.leverage
        short_required = float(short_plan.notional_per_leg) / short_plan.leverage if short_plan is not None else 0.0
        total_required = required + short_required
        if available < total_required * 1.05:
            actions.append({"kind": "ENTRY_MARGIN_WAIT", "symbol": symbol, "side": side, "requiredMargin": total_required}); continue
        entry_action = {"kind": "ENTRY", "symbol": symbol, "side": side, "leverage": plan.leverage, "notionalUsd": float(plan.notional_per_leg), "marginUsd": required, "entryMode": "immediate_fill",
            "exchangeMaxLeverage": tier["exchangeMaxLeverage"], "forcedBelowConfiguredMinimum": tier["forcedBelowConfiguredMinimum"]}
        short_action = ({"kind": "ASYM_SHORT_ENTRY", "symbol": symbol, "side": "SHORT", "leverage": short_plan.leverage, "notionalUsd": float(short_plan.notional_per_leg), "marginUsd": short_required, "multiplier": settings.short_start_multiplier} if paired and short_plan is not None else None)
        if dry_run:
            actions.append(entry_action)
            if short_action is not None: actions.append(short_action)
        else:
            try:
                result = execute_leg_once(client, plan, side=PositionSide(side), action="OPEN", id_prefix=f"mbb-open-{hashlib.sha256((uid+symbol+side+str(timestamp_ms)).encode()).hexdigest()[:12]}", confirm=True,
                                          new_position_leverage=plan.leverage, before_submit=before_order)
            except NewPositionLeverageBlocked as exc:
                actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": exc.reason_code})
                continue
            except Exception as exc:
                if not is_definite_contract_rejection(exc): raise
                actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": str(exc)})
                continue
            fill = result.get("result") or {}; fill_price = _f(fill.get("avgPrice"), prices[symbol]); fill_qty = _f(fill.get("executedQty"), float(plan.quantity))
            key = f"{symbol}|{side}"; cycle_id = hashlib.sha256((uid+key+str(timestamp_ms)).encode()).hexdigest()[:16]
            state[key] = {"cycleId": cycle_id, "dcaCount": 0, "lastBotFillPrice": fill_price, "lastKnownQty": fill_qty, "lastKnownEntry": fill_price, "leverage": plan.leverage,
                "cycleStartedAtMs": timestamp_ms, "updatedAtMs": timestamp_ms, "botManaged": True,
                "asymmetricHedge": paired, "pairedShortKey": f"{symbol}|SHORT" if paired else "", "pairedShortPending": paired, "pairedShortOpened": False, "longTpBlocked": paired}
            ref.set({"multiBbPositions": state, "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING", "lastReason": f"Multi DCA actief; nieuwe {side} geopend op {symbol}"}, merge=True)
            ref.collection("audit").add({"event": "MULTI_BB_ENTRY", "symbol": symbol, "side": side, "leverage": plan.leverage, "cycleId": cycle_id, "timestamp": datetime.now(timezone.utc)})
            actions.append(entry_action)
            if paired and short_plan is not None and short_action is not None:
                try:
                    short_result = execute_leg_once(client, short_plan, side=PositionSide.SHORT, action="OPEN", id_prefix=f"mbb-asym-short-{cycle_id}", confirm=True, new_position_leverage=short_plan.leverage, before_submit=before_order)
                except Exception as exc:
                    pending = dict(state[key]); pending.update({"pairedShortPending": True, "pairedShortLastError": str(exc), "updatedAtMs": timestamp_ms}); state[key] = pending
                    ref.set({"multiBbPositions": state, "phase": "RUNNING", "lastReason": f"Asymmetrische hedge: LONG {symbol} open; initiële SHORT wacht op veilige recovery"}, merge=True)
                    actions.append({"kind": "ASYM_SHORT_ENTRY_PENDING", "symbol": symbol, "reason": str(exc)})
                    if not is_definite_contract_rejection(exc): raise
                else:
                    sf = short_result.get("result") or {}; short_price = _f(sf.get("avgPrice"), prices[symbol]); short_qty = _f(sf.get("executedQty"), float(short_plan.quantity)); short_key = f"{symbol}|SHORT"
                    state[short_key] = {"cycleId": cycle_id, "dcaCount": 0, "lastBotFillPrice": short_price, "lastKnownQty": short_qty, "lastKnownEntry": short_price, "leverage": short_plan.leverage,
                        "cycleStartedAtMs": timestamp_ms, "updatedAtMs": timestamp_ms, "botManaged": True, "asymmetricHedge": True, "pairedLongKey": key, "initialShortMultiplier": settings.short_start_multiplier}
                    linked = dict(state[key]); linked.update({"pairedShortPending": False, "pairedShortOpened": True, "pairedShortOrderConfirmedAtMs": timestamp_ms}); state[key] = linked
                    ref.set({"multiBbPositions": state, "lastReason": f"Asymmetrische hedge actief op {symbol}: LONG + {settings.short_start_multiplier:g}x SHORT bevestigd"}, merge=True)
                    ref.collection("audit").add({"event": "MULTI_BB_ASYM_SHORT_ENTRY", "symbol": symbol, "cycleId": cycle_id, "multiplier": settings.short_start_multiplier, "leverage": short_plan.leverage, "timestamp": datetime.now(timezone.utc)})
                    actions.append(short_action)
        active_symbols.add(symbol)
        consumed = 2 if paired and (dry_run or f"{symbol}|SHORT" in state) else 1
        account_position_count += consumed
        if settings.asymmetric_hedge_enabled:
            account_remaining_capacity = max(0, 50 - account_position_count)
            active_pair_count += 1
            pair_need = max(0, settings.long_slots - active_pair_count)
            long_need = pair_need; short_need = pair_need
            long_count += 1
            if consumed == 2: short_count += 1
        else:
            account_remaining_capacity = max(0, settings.maximum_positions - account_position_count)
            if side == "LONG":
                long_count += 1; long_need = max(0, settings.long_slots - long_count)
            else:
                short_count += 1; short_need = max(0, settings.short_slots - short_count)
        available -= total_required if consumed == 2 else required; sent += consumed

    managed_long = sum(1 for key in state if key.endswith("|LONG") and key in active)
    managed_short = sum(1 for key in state if key.endswith("|SHORT") and key in active)
    manual_long = max(0, long_count - managed_long)
    manual_short = max(0, short_count - managed_short)
    skip_reasons: dict[str, int] = {}
    for action in actions:
        if action.get("kind") not in {"ENTRY_SKIP", "ENTRY_MARGIN_WAIT"}:
            continue
        reason = str(action.get("reason") or action.get("kind") or "unknown")
        if reason.startswith("max ") and "< minimum" in reason:
            reason = "MAX_LEVERAGE_BELOW_MINIMUM"
        elif "5018" in reason or "maximum notional" in reason.lower():
            reason = "MAX_NOTIONAL_LIMIT"
        elif action.get("kind") == "ENTRY_MARGIN_WAIT":
            reason = "INSUFFICIENT_AVAILABLE_MARGIN"
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    entry_rows = [a for a in actions if a.get("kind") == "ENTRY"]
    entry_wait = [a for a in actions if a.get("kind") in {"ENTRY_SKIP", "ENTRY_MARGIN_WAIT"}]
    selected_open = bool(settings.manual_symbol_selection_enabled and any(key in active for key in selected_keys))
    remaining_slots = pair_need if settings.asymmetric_hedge_enabled else long_need + short_need
    next_required_margin = min(minimum_margin_rejections, default=None)
    if entry_rows and remaining_slots > 0:
        entry_status = "PARTIAL_FILL_PLANNED" if dry_run else "PARTIAL_FILL_SUBMITTED"
        entry_reason = (f"{len(entry_rows)} nieuwe gekoppelde cycli verwerkt; nog {remaining_slots} paar/paaren vrij" if settings.asymmetric_hedge_enabled else f"{len(entry_rows)} nieuwe positie(s) verwerkt; nog {remaining_slots} botslots vrij")
        if next_required_margin is not None:
            entry_reason += f"; volgende minimumorder vraagt circa {next_required_margin:.2f} USDT startmargin"
    elif entry_rows: entry_status = "ENTRY_PLANNED" if dry_run else "ENTRY_SUBMITTED"; entry_reason = "verse Strategy 2 entry verwerkt"
    elif selected_open: entry_status = "POSITION_ALREADY_OPEN"; entry_reason = "geselecteerde munt heeft al een open Aster-positie"
    elif long_need <= 0 and short_need <= 0:
        entry_status = "WAITING_CAPACITY"; entry_reason = "Gekoppelde-parencapaciteit is gevuld" if settings.asymmetric_hedge_enabled else "Strategy 2 slots zijn gevuld"
    elif account_remaining_capacity < (2 if settings.asymmetric_hedge_enabled else 1):
        entry_status = "WAITING_ACCOUNT_CAP"
        entry_reason = (f"account heeft {account_position_count} actieve Aster-posities; er zijn twee vrije posities nodig voor één volledig LONG+SHORT-paar" if settings.asymmetric_hedge_enabled else f"account heeft {account_position_count} actieve Aster-posities; ingestelde limiet is {settings.maximum_positions}")
    elif any(a.get("kind") == "ENTRY_MARGIN_WAIT" for a in entry_wait): entry_status = "WAITING_BUDGET"; entry_reason = "onvoldoende beschikbare margin"
    elif any(str(a.get("reason", "")).startswith("leverage-data:") or a.get("reason") == "SYMBOL_LEVERAGE_DATA_UNAVAILABLE" for a in entry_wait): entry_status = "WAITING_EXCHANGE"; entry_reason = str(entry_wait[0].get("reason", "Aster leverage-data tijdelijk niet beschikbaar"))
    elif entry_wait: entry_status = "ORDER_REJECTED"; entry_reason = str(entry_wait[0].get("reason", "Aster ordercheck afgewezen"))
    else: entry_status = "READY_FOR_ENTRY"; entry_reason = "verse exchange snapshot; geselecteerde munt is opnieuw entry-kandidaat"
    report = {"engine": ENGINE, "configVersion": settings.version,
              "ordersSent": 0 if dry_run else sent, "simulatedActions": len(actions) if dry_run else 0,
              "entryStatus": entry_status, "entryReason": entry_reason,
              "actions": actions[-30:], "rankedTopN": ranked, "candidateMode": "manual" if settings.manual_symbol_selection_enabled else "top_n",
              "manualSymbols": [{"symbol": symbol, "side": side} for symbol, side in settings.manual_symbols], "longSlots": settings.long_slots, "shortSlots": settings.short_slots,
              "asymmetricHedgeModeEnabled": settings.asymmetric_hedge_enabled, "shortStartMultiplier": settings.short_start_multiplier,
              "asymmetricHedgeActivePairs": active_pair_count, "remainingPairs": pair_need if settings.asymmetric_hedge_enabled else None,
              "legacyPositionsDuringAsymmetric": legacy_position_count,
              "activeLong": long_count, "activeShort": short_count,
              "remainingLong": long_need, "remainingShort": short_need,
              "accountPositionCount": account_position_count, "accountRemainingCapacity": account_remaining_capacity,
              "untrackedAccountPositionCount": max(0, account_position_count - len(strategy_active_keys)),
              "managedLong": managed_long, "managedShort": managed_short, "manualLong": manual_long, "manualShort": manual_short,
              "nextEntrySide": _next_entry_side(long_count=long_count, short_count=short_count, long_slots=settings.long_slots, short_slots=settings.short_slots),
              "candidateCount": len(candidates), "scannedCandidateCount": scanned_candidates,
              "executableCandidateCount": executable_candidates,
              "minimumOrderRejectedCount": len(minimum_margin_rejections),
              "nextRequiredEntryMarginUsd": next_required_margin,
              "entrySkipReasons": skip_reasons, "updatedAtMs": timestamp_ms}
    if not dry_run:
        ref.set({"multiBbPositions": state, "multiBbReport": report, "multiBbAdoptionPending": False,
                 "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                 "lastReason": f"{entry_status}: {entry_reason}"}, merge=True)
    return {"status": "simulated" if dry_run else "running", "action": "MULTI_BB", **report}
