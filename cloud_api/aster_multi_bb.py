from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_UP
from datetime import datetime, timezone
from typing import Any
import hashlib, math, time

from aster_close_guard import CloseEvidence
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
    manual_symbol_selection_enabled: bool = False
    manual_symbols: tuple[tuple[str, str], ...] = ()
    standard_long: dict[str, Any] = field(default_factory=dict)
    standard_short: dict[str, Any] = field(default_factory=dict)
    pair_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "MultiBbConfig":
        raw = raw or {}
        minimum_leverage=_i(raw.get("minimumLeverage", raw.get("leverage")), 50)
        entry_margin_usd=_f(raw.get("entryMarginUsd", raw.get("baseMarginUsd")), 5.0)
        entry_notional_usd=_f(raw.get("entryNotionalUsd", raw.get("baseNotional")), entry_margin_usd * max(1, minimum_leverage))
        manual_enabled=bool(raw.get("manualSymbolSelectionEnabled", False))
        entry_sizing_mode=str(raw.get("entrySizingMode", "margin" if manual_enabled else "notional")).lower().strip()
        manual_rows=raw.get("manualSymbols") if isinstance(raw.get("manualSymbols"), list) else []
        manual_symbols=[]
        seen=set()
        for item in manual_rows:
            if not isinstance(item, dict): continue
            symbol=str(item.get("symbol", "")).upper().strip(); side=str(item.get("side", "")).upper().strip()
            if not symbol or side not in {"LONG", "SHORT"} or symbol in seen: continue
            seen.add(symbol); manual_symbols.append((symbol, side))
        def normalized_profile(value: Any) -> dict[str, Any]:
            if not isinstance(value, dict):
                return {}
            allowed = {"entryMarginUsd", "entryNotionalUsd", "entrySizingMode", "minimumLeverage", "dcaDistance", "dcaMarginUsd", "maxDca", "unlimitedDca", "takeProfit", "autoRestart"}
            return {str(k): v for k, v in value.items() if str(k) in allowed}
        standard_long = normalized_profile(raw.get("standardLong"))
        standard_short = normalized_profile(raw.get("standardShort"))
        override_rows = raw.get("pairOverrides") if isinstance(raw.get("pairOverrides"), dict) else {}
        pair_overrides: dict[str, dict[str, Any]] = {}
        for raw_symbol, raw_override in override_rows.items():
            symbol = str(raw_symbol).upper().strip()
            if symbol and symbol.endswith("USDT"):
                normalized = normalized_profile(raw_override)
                if normalized:
                    pair_overrides[symbol] = normalized
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
            manual_symbol_selection_enabled=manual_enabled,
            manual_symbols=tuple(manual_symbols),
            standard_long=standard_long,
            standard_short=standard_short,
            pair_overrides=pair_overrides,
        )
        return cfg.validated()

    def validated(self) -> "MultiBbConfig":
        if self.engine != ENGINE: raise ValueError("Alleen de nieuwe Multi BB-strategie is toegestaan")
        if not 1 <= self.universe_top_n <= 200: raise ValueError("Top-N moet tussen 1 en 200 liggen")
        if not 1 <= self.maximum_positions <= (200 if self.manual_symbol_selection_enabled else self.universe_top_n): raise ValueError("Max posities moet tussen 1 en 200 liggen" if self.manual_symbol_selection_enabled else "Max posities moet tussen 1 en Top-N liggen")
        if self.long_slots < 0 or self.short_slots < 0 or self.long_slots + self.short_slots != self.maximum_positions:
            raise ValueError("LONG + SHORT slots moet exact gelijk zijn aan max posities")
        if not 1 <= self.minimum_leverage <= 300: raise ValueError("Minimum leverage moet tussen 1x en 300x liggen")
        if self.entry_margin_usd <= 0 or self.entry_notional_usd <= 0 or self.dca_margin_usd <= 0: raise ValueError("Entry-bedrag en DCA-margin moeten positief zijn")
        if self.entry_sizing_mode not in {"notional", "margin"}: raise ValueError("Entry sizing mode is ongeldig")
        if not .0001 <= self.dca_distance <= .50: raise ValueError("DCA-afstand is ongeldig")
        if self.max_dca < 0: raise ValueError("Max DCA mag niet negatief zijn")
        if not .001 <= self.take_profit <= .20: raise ValueError("Take Profit moet tussen 0,1% en 20% liggen")
        if self.manual_symbol_selection_enabled and not self.manual_symbols:
            raise ValueError("Selecteer minimaal één munt wanneer Zelf munten kiezen aan staat")
        if len(self.manual_symbols) > 200: raise ValueError("Maximaal 200 handmatig gekozen munten")
        for label, profile in (("STANDARD LONG", self.standard_long), ("STANDARD SHORT", self.standard_short)):
            if "minimumLeverage" in profile and not 1 <= _i(profile.get("minimumLeverage")) <= 300: raise ValueError(f"{label}: leverage moet tussen 1x en 300x liggen")
            if "maxDca" in profile and _i(profile.get("maxDca")) < 0: raise ValueError(f"{label}: Max DCA mag niet negatief zijn")
            if "dcaDistance" in profile and not .0001 <= _f(profile.get("dcaDistance")) <= .50: raise ValueError(f"{label}: DCA-afstand is ongeldig")
            if "takeProfit" in profile and not .001 <= _f(profile.get("takeProfit")) <= .20: raise ValueError(f"{label}: Take Profit moet tussen 0,1% en 20% liggen")
        if len(self.pair_overrides) > 200: raise ValueError("Maximaal 200 pair-overrides")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {
            "engine": ENGINE, "strategyKind": ENGINE, "name": self.name, "version": self.version, "mode": self.mode,
            "universeTopN": self.universe_top_n, "maximumPositions": self.maximum_positions,
            "longSlots": self.long_slots, "shortSlots": self.short_slots, "minimumLeverage": self.minimum_leverage,
            "entryMarginUsd": self.entry_margin_usd, "entryNotionalUsd": self.entry_notional_usd, "entrySizingMode": self.entry_sizing_mode, "dcaDistance": self.dca_distance,
            "dcaMarginUsd": self.dca_margin_usd, "maxDca": self.max_dca, "unlimitedDca": self.unlimited_dca, "takeProfit": self.take_profit,
            "entryMode": "immediate_fill", "marginMode": "cross", "autoRestart": True,
            "manualSymbolSelectionEnabled": self.manual_symbol_selection_enabled,
            "manualSymbols": [{"symbol": symbol, "side": side} for symbol, side in self.manual_symbols],
            "standardLong": dict(self.standard_long),
            "standardShort": dict(self.standard_short),
            "pairOverrides": {symbol: dict(value) for symbol, value in self.pair_overrides.items()},
        }

    def effective_profile(self, symbol: str, side: str) -> dict[str, Any]:
        profile = dict(self.standard_long if str(side).upper() == "LONG" else self.standard_short)
        profile.update(self.pair_overrides.get(str(symbol).upper().strip(), {}))
        return {
            "minimumLeverage": _i(profile.get("minimumLeverage"), self.minimum_leverage),
            "entryMarginUsd": _f(profile.get("entryMarginUsd"), self.entry_margin_usd),
            "entryNotionalUsd": _f(profile.get("entryNotionalUsd"), self.entry_notional_usd),
            "entrySizingMode": str(profile.get("entrySizingMode", self.entry_sizing_mode)).lower().strip(),
            "dcaDistance": _f(profile.get("dcaDistance"), self.dca_distance),
            "dcaMarginUsd": _f(profile.get("dcaMarginUsd"), self.dca_margin_usd),
            "maxDca": _i(profile.get("maxDca"), self.max_dca),
            "unlimitedDca": bool(profile.get("unlimitedDca", self.unlimited_dca)),
            "takeProfit": _f(profile.get("takeProfit"), self.take_profit),
            "autoRestart": bool(profile.get("autoRestart", True)),
        }



def position_action_preview(*, row: dict[str, Any], state: dict[str, Any], settings: MultiBbConfig, account_equity: float = 0.0) -> dict[str, Any]:
    """Expose the exact next Strategy 2 DCA/TP levels used by the execution engine."""
    side = str(row.get("positionSide", "")).upper()
    entry = _f(row.get("entryPrice"))
    mark = _f(row.get("markPrice"), entry)
    qty = abs(_f(row.get("positionAmt")))
    if side not in {"LONG", "SHORT"} or entry <= 0 or mark <= 0 or qty <= 0:
        return {}
    effective = settings.effective_profile(str(row.get("symbol", "")), side)
    take_profit = _f(effective.get("takeProfit"), settings.take_profit)
    tp_price = entry * (1 + take_profit if side == "LONG" else 1 - take_profit)
    tp_distance_usd = abs(tp_price - mark)
    tp_distance_pct = tp_distance_usd / mark * 100
    expected_pnl_at_tp = ((tp_price - entry) if side == "LONG" else (entry - tp_price)) * qty
    current_pnl = ((mark - entry) if side == "LONG" else (entry - mark)) * qty
    portfolio_value_at_tp = account_equity + (expected_pnl_at_tp - current_pnl) if account_equity > 0 else None
    dca_count = _i(state.get("dcaCount"))
    anchor = _f(state.get("lastBotFillPrice"), entry)
    effective_max_dca = _i(effective.get("maxDca"), settings.max_dca)
    effective_unlimited = bool(effective.get("unlimitedDca", settings.unlimited_dca))
    effective_distance = _f(effective.get("dcaDistance"), settings.dca_distance)
    dca_allowed = effective_unlimited or dca_count < effective_max_dca
    next_dca_price = anchor * (1 - effective_distance if side == "LONG" else 1 + effective_distance) if dca_allowed and anchor > 0 else None
    next_dca_distance_usd = abs(next_dca_price - mark) if next_dca_price else None
    next_dca_distance_pct = next_dca_distance_usd / mark * 100 if next_dca_distance_usd is not None else None
    return {
        "takeProfitPct": take_profit * 100,
        "tpPrice": tp_price,
        "tpDistanceUsd": tp_distance_usd,
        "tpDistancePct": tp_distance_pct,
        "expectedPnlAtTp": expected_pnl_at_tp,
        "portfolioValueAtTp": portfolio_value_at_tp,
        "nextDcaPrice": next_dca_price,
        "nextDcaDistanceUsd": next_dca_distance_usd,
        "nextDcaDistancePct": next_dca_distance_pct,
        "nextDcaNumber": dca_count + 1 if next_dca_price else None,
        "unlimitedDca": effective_unlimited,
        "maxDca": effective_max_dca,
        "customSettings": bool(settings.pair_overrides.get(str(row.get("symbol", "")).upper().strip())),
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



def quick_trade_once(*, client: Any, ref: Any, raw_state: dict[str, Any], settings: MultiBbConfig, uid: str,
                     account: dict[str, Any], positions: list[dict[str, Any]], open_orders: list[dict[str, Any]],
                     symbol: str, side: str, idempotency_key: str, timestamp_ms: int, dry_run: bool = False) -> dict[str, Any]:
    """Open exactly one user-requested Strategy-2 cycle without invoking the automatic scanner.

    Uses the same exchange metadata, tier resolver, order planner, executor and persisted
    multiBbPositions state as the automatic engine. The stable idempotency key is part of
    both the exchange client id and cycle id, so browser retries cannot create a second cycle.
    """
    symbol = str(symbol).upper().strip(); side = str(side).upper().strip()
    if not symbol.endswith("USDT") or side not in {"LONG", "SHORT"}:
        raise ValueError("Ongeldige Aster USDT perpetual of richting")
    pmap = _position_map(positions)
    same_symbol = [key for key in pmap if key.startswith(symbol + "|")]
    if same_symbol:
        existing_side = same_symbol[0].split("|", 1)[1]
        raise ValueError(f"{symbol} heeft al een actieve {existing_side}-positie")
    for order in open_orders:
        if str(order.get("symbol", "")).upper() == symbol and str(order.get("positionSide", "")).upper() == side:
            raise ValueError(f"{symbol} {side} heeft al een pending exchange-order")
    info = client.public_exchange_info()
    row = next((x for x in info.get("symbols", []) if str(x.get("symbol", "")).upper() == symbol
                and str(x.get("quoteAsset", "USDT")).upper() == "USDT"
                and str(x.get("status", "TRADING")).upper() == "TRADING"), None)
    if row is None:
        raise ValueError(f"{symbol} is niet actief/verhandelbaar op Aster")
    prices = {str(x.get("symbol", "")).upper(): _f(x.get("price")) for x in client.ticker_prices()}
    mark = prices.get(symbol, 0.0)
    if mark <= 0:
        raise ValueError(f"Geen actuele Aster-prijs beschikbaar voor {symbol}")
    effective = settings.effective_profile(symbol, side)
    plan, tier = _plan_new(client, row, mark,
        entry_margin_usd=_f(effective.get("entryMarginUsd"), settings.entry_margin_usd),
        entry_notional_usd=_f(effective.get("entryNotionalUsd"), settings.entry_notional_usd),
        entry_sizing_mode=str(effective.get("entrySizingMode", settings.entry_sizing_mode)),
        minimum_leverage=max(1, _i(effective.get("minimumLeverage"), settings.minimum_leverage)))
    required = float(plan.notional_per_leg) / max(1, plan.leverage)
    available = _f(account.get("availableBalance", account.get("availableMargin")))
    if available < required * 1.05:
        raise ValueError(f"Onvoldoende beschikbare margin voor {symbol} {side}; minimaal ongeveer ${required * 1.05:.2f} nodig")
    cycle_id = hashlib.sha256((uid + symbol + side + idempotency_key).encode()).hexdigest()[:16]
    planned = {"status": "PLANNED", "symbol": symbol, "side": side, "cycleId": cycle_id,
               "leverage": plan.leverage, "marginUsd": required, "notionalUsd": float(plan.notional_per_leg),
               "exchangeMaxLeverage": tier.get("exchangeMaxLeverage"), "effectiveSettings": effective}
    if dry_run:
        return planned
    stable = hashlib.sha256((uid + symbol + side + idempotency_key).encode()).hexdigest()[:12]
    result = execute_leg_once(client, plan, side=PositionSide(side), action="OPEN", id_prefix=f"mbb-quick-{stable}",
                              confirm=True, new_position_leverage=plan.leverage)
    fill = result.get("result") or {}
    fill_price = _f(fill.get("avgPrice"), mark); fill_qty = _f(fill.get("executedQty"), float(plan.quantity))
    if fill_qty <= 0:
        raise RuntimeError(f"{symbol} {side}: Aster bevestigde geen geldige fill")
    state = dict(raw_state.get("multiBbPositions") or {})
    key = f"{symbol}|{side}"
    state[key] = {"cycleId": cycle_id, "dcaCount": 0, "lastBotFillPrice": fill_price,
                  "lastKnownQty": fill_qty, "lastKnownEntry": fill_price, "leverage": plan.leverage,
                  "cycleStartedAtMs": timestamp_ms, "updatedAtMs": timestamp_ms, "botManaged": True,
                  "manualQuickTrade": True, "quickTradeIdempotencyKey": idempotency_key}
    ref.set({"multiBbPositions": state, "phase": "RUNNING", "lastTickAt": datetime.now(timezone.utc),
             "lastReason": f"Markets quick trade: {symbol} {side} actief"}, merge=True)
    ref.collection("audit").add({"event": "MARKETS_QUICK_TRADE", "symbol": symbol, "side": side,
        "cycleId": cycle_id, "idempotencyKey": idempotency_key, "leverage": plan.leverage,
        "marginUsd": required, "notionalUsd": float(plan.notional_per_leg), "timestamp": datetime.now(timezone.utc)})
    return {**planned, "status": "ACTIVE", "fillPrice": fill_price, "fillQty": fill_qty}

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

    # Exchange truth reconciles every already-managed leg; a manual add never resets/increments the automatic DCA counter.
    for key in list(state):
        row = pmap.get(key)
        if row is None:
            reconciled_closed.append(key); state.pop(key, None); continue
        st = dict(state[key]); qty = abs(_f(row.get("positionAmt"))); entry = _f(row.get("entryPrice")); leverage = max(1, _i(row.get("leverage"), st.get("leverage", 1)))
        changed = abs(qty - _f(st.get("lastKnownQty"))) > 1e-12 or abs(entry - _f(st.get("lastKnownEntry"))) > 1e-12
        boundary_check = settings.manual_symbol_selection_enabled and _i(st.get("dcaCount")) > 0 and (bool(raw_state.get("multiBbAdoptionPending")) or not st.get("cycleBoundaryCheckedAtMs") or changed)
        if boundary_check and _manual_reopen_boundary(client, str(row.get("symbol", "")).upper(), str(row.get("positionSide", "")).upper(), st):
            old_cycle = str(st.get("cycleId", ""))
            st = {"cycleId": hashlib.sha256((uid+key+str(timestamp_ms)).encode()).hexdigest()[:16], "dcaCount": 0,
                "lastBotFillPrice": entry, "lastKnownQty": qty, "lastKnownEntry": entry, "leverage": leverage,
                "cycleStartedAtMs": timestamp_ms, "updatedAtMs": timestamp_ms, "cycleBoundaryCheckedAtMs": timestamp_ms, "botManaged": True}
            actions.append({"kind": "REENTRY_CYCLE_RESET", "key": key, "oldCycleId": old_cycle, "reason": "Aster fills prove prior cycle went flat before this reopen"})
        else:
            if changed:
                st["manualOrExchangeReconciledAtMs"] = timestamp_ms
            if boundary_check:
                st["cycleBoundaryCheckedAtMs"] = timestamp_ms
            st.update({"lastKnownQty": qty, "lastKnownEntry": entry, "leverage": leverage, "updatedAtMs": timestamp_ms})
        account_equity = _f(account.get("totalMarginBalance", account.get("marginBalance", account.get("equity", account.get("totalWalletBalance")))))
        st.update(position_action_preview(row=row, state=st, settings=settings, account_equity=account_equity))
        state[key] = st

    for key in reconciled_closed:
        actions.append({"kind": "REENTRY_STATE_CLEARED", "key": key, "reason": "exchange position is flat"})

    # Management priority: full TP, then capped DCA.
    for key, st0 in list(state.items()):
        if sent >= budget: break
        row = pmap.get(key)
        if row is None: continue
        symbol, side = key.split("|", 1); mark = _f(row.get("markPrice"), prices.get(symbol, 0)); entry = _f(row.get("entryPrice")); qty = abs(_f(row.get("positionAmt")))
        if mark <= 0 or entry <= 0 or qty <= 0 or (symbol, side) in order_keys: continue
        effective = settings.effective_profile(symbol, side)
        take_profit = _f(effective.get("takeProfit"), settings.take_profit)
        tp_price = entry * (1 + take_profit if side == "LONG" else 1 - take_profit)
        tp_due = mark >= tp_price if side == "LONG" else mark <= tp_price
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
        dca_count = _i(st0.get("dcaCount")); anchor = _f(st0.get("lastBotFillPrice"), entry)
        effective_max_dca = _i(effective.get("maxDca"), settings.max_dca)
        effective_unlimited = bool(effective.get("unlimitedDca", settings.unlimited_dca))
        effective_distance = _f(effective.get("dcaDistance"), settings.dca_distance)
        if (not effective_unlimited and dca_count >= effective_max_dca) or anchor <= 0: continue
        trigger = anchor * (1 - effective_distance if side == "LONG" else 1 + effective_distance)
        due = mark <= trigger if side == "LONG" else mark >= trigger
        if not due: continue
        row_info = info_map.get(symbol); leverage = max(1, _i(row.get("leverage")))
        if row_info is None: continue
        try: plan, tier = _plan_add(client, row_info, mark, _f(effective.get("dcaMarginUsd"), settings.dca_margin_usd), leverage, qty * mark, _i(effective.get("minimumLeverage"), settings.minimum_leverage))
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
            fill = result.get("result") or {}; fill_price = _f(fill.get("avgPrice"), mark)
            st = dict(st0); st.update({"dcaCount": dca_count + 1, "lastBotFillPrice": fill_price, "updatedAtMs": timestamp_ms,
                "leverage": int(tier["leverage"]), "lastTierReductionAtMs": timestamp_ms if tier["tierReduction"] else st0.get("lastTierReductionAtMs")}); state[key] = st
            ref.set({"multiBbPositions": state, "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                     "lastReason": f"Multi DCA actief; DCA {dca_count + 1} bevestigd op {symbol} @ {int(tier['leverage'])}x"}, merge=True)
            ref.collection("audit").add({"event": "MULTI_BB_DCA", "symbol": symbol, "side": side, "dcaNumber": dca_count + 1,
                "previousLeverage": tier["previousLeverage"], "leverage": tier["leverage"], "tierReduction": tier["tierReduction"],
                "projectedNotional": tier["projectedNotional"], "timestamp": datetime.now(timezone.utc)})
        available -= required; sent += 1

    active = _position_map(client.position_risk()) if sent and not dry_run else pmap
    active_symbols = {k.split("|", 1)[0] for k in active}
    strategy_active_keys = {key for key in active if key in state or (settings.manual_symbol_selection_enabled and key in selected_keys)}
    long_count = sum(1 for k in strategy_active_keys if k.endswith("|LONG")); short_count = sum(1 for k in strategy_active_keys if k.endswith("|SHORT"))
    long_need = max(0, settings.long_slots - long_count); short_need = max(0, settings.short_slots - short_count)

    # New seats: fill immediately from Top-N volume after leverage/order/margin checks.
    for ranked_row in candidates:
        if sent >= budget or (long_need <= 0 and short_need <= 0): break
        symbol = ranked_row["symbol"]
        if symbol in active_symbols or symbol not in info_map or prices.get(symbol, 0) <= 0: continue
        try:
            bracket_payload = client.leverage_brackets(symbol); maximum = max_contract_leverage(bracket_payload, symbol)
        except Exception as exc:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": f"leverage-data: {exc}"}); continue
        if maximum <= 0:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": "SYMBOL_LEVERAGE_DATA_UNAVAILABLE"}); continue
        if settings.manual_symbol_selection_enabled:
            side = str(ranked_row.get("forcedSide", "")).upper()
            if side == "LONG" and long_need <= 0: continue
            if side == "SHORT" and short_need <= 0: continue
            if side not in {"LONG", "SHORT"}: continue
        else:
            side = _next_entry_side(long_count=long_count,short_count=short_count,long_slots=settings.long_slots,short_slots=settings.short_slots)
            if not side: break
        effective = settings.effective_profile(symbol, side)
        try: plan, tier = _plan_new(client, info_map[symbol], prices[symbol], entry_margin_usd=_f(effective.get("entryMarginUsd"), settings.entry_margin_usd), entry_notional_usd=_f(effective.get("entryNotionalUsd"), settings.entry_notional_usd), entry_sizing_mode=str(effective.get("entrySizingMode", settings.entry_sizing_mode)), minimum_leverage=_i(effective.get("minimumLeverage"), settings.minimum_leverage))
        except Exception as exc:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": str(exc)}); continue
        required = float(plan.notional_per_leg) / plan.leverage
        if available < required * 1.05:
            actions.append({"kind": "ENTRY_MARGIN_WAIT", "symbol": symbol, "side": side}); continue
        entry_action = {"kind": "ENTRY", "symbol": symbol, "side": side, "leverage": plan.leverage, "notionalUsd": float(plan.notional_per_leg), "marginUsd": required, "entryMode": "immediate_fill",
            "exchangeMaxLeverage": tier["exchangeMaxLeverage"], "forcedBelowConfiguredMinimum": tier["forcedBelowConfiguredMinimum"]}
        if dry_run:
            actions.append(entry_action)
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
            key = f"{symbol}|{side}"; state[key] = {"cycleId": hashlib.sha256((uid+key+str(timestamp_ms)).encode()).hexdigest()[:16], "dcaCount": 0,
                "lastBotFillPrice": fill_price, "lastKnownQty": fill_qty, "lastKnownEntry": fill_price, "leverage": plan.leverage,
                "cycleStartedAtMs": timestamp_ms, "updatedAtMs": timestamp_ms, "botManaged": True}
            ref.set({"multiBbPositions": state, "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                     "lastReason": f"Multi DCA actief; nieuwe {side} geopend op {symbol}"}, merge=True)
            ref.collection("audit").add({"event": "MULTI_BB_ENTRY", "symbol": symbol, "side": side, "leverage": plan.leverage, "timestamp": datetime.now(timezone.utc)})
            actions.append(entry_action)
        active_symbols.add(symbol)
        if side == "LONG": long_count += 1; long_need = max(0, settings.long_slots - long_count)
        else: short_count += 1; short_need = max(0, settings.short_slots - short_count)
        available -= required; sent += 1

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
    if entry_rows: entry_status = "ENTRY_PLANNED" if dry_run else "ENTRY_SUBMITTED"; entry_reason = "verse Strategy 2 entry verwerkt"
    elif selected_open: entry_status = "POSITION_ALREADY_OPEN"; entry_reason = "geselecteerde munt heeft al een open Aster-positie"
    elif long_need <= 0 and short_need <= 0: entry_status = "WAITING_CAPACITY"; entry_reason = "Strategy 2 slots zijn gevuld"
    elif any(a.get("kind") == "ENTRY_MARGIN_WAIT" for a in entry_wait): entry_status = "WAITING_BUDGET"; entry_reason = "onvoldoende beschikbare margin"
    elif any(str(a.get("reason", "")).startswith("leverage-data:") or a.get("reason") == "SYMBOL_LEVERAGE_DATA_UNAVAILABLE" for a in entry_wait): entry_status = "WAITING_EXCHANGE"; entry_reason = str(entry_wait[0].get("reason", "Aster leverage-data tijdelijk niet beschikbaar"))
    elif entry_wait: entry_status = "ORDER_REJECTED"; entry_reason = str(entry_wait[0].get("reason", "Aster ordercheck afgewezen"))
    else: entry_status = "READY_FOR_ENTRY"; entry_reason = "verse exchange snapshot; geselecteerde munt is opnieuw entry-kandidaat"
    report = {"engine": ENGINE, "ordersSent": 0 if dry_run else sent, "simulatedActions": len(actions) if dry_run else 0,
              "entryStatus": entry_status, "entryReason": entry_reason,
              "actions": actions[-30:], "rankedTopN": ranked, "candidateMode": "manual" if settings.manual_symbol_selection_enabled else "top_n",
              "manualSymbols": [{"symbol": symbol, "side": side} for symbol, side in settings.manual_symbols], "longSlots": settings.long_slots, "shortSlots": settings.short_slots,
              "activeLong": settings.long_slots - long_need, "activeShort": settings.short_slots - short_need,
              "managedLong": managed_long, "managedShort": managed_short, "manualLong": manual_long, "manualShort": manual_short,
              "nextEntrySide": _next_entry_side(long_count=long_count, short_count=short_count, long_slots=settings.long_slots, short_slots=settings.short_slots),
              "entrySkipReasons": skip_reasons, "updatedAtMs": timestamp_ms}
    if not dry_run:
        ref.set({"multiBbPositions": state, "multiBbReport": report, "multiBbAdoptionPending": False,
                 "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                 "lastReason": f"{entry_status}: {entry_reason}"}, merge=True)
    return {"status": "simulated" if dry_run else "running", "action": "MULTI_BB", **report}
