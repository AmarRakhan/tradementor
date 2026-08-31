from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any
import hashlib, math, time

from aster_close_guard import CloseEvidence
from aster_execution import NewPositionLeverageBlocked, PairExecutionPlan, execute_leg_once, plan_pair
from aster_gateway import PositionSide

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
    dca_distance: float = .003
    dca_margin_usd: float = 2.0
    max_dca: int = 3
    take_profit: float = .015

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "MultiBbConfig":
        raw = raw or {}
        cfg = cls(
            engine=str(raw.get("engine", raw.get("strategyKind", ENGINE))),
            name=str(raw.get("name", "Aster Multi DCA")),
            version=max(1, _i(raw.get("version"), 1)),
            mode="paper" if str(raw.get("mode", "live")).lower() == "paper" else "live",
            universe_top_n=_i(raw.get("universeTopN"), 30),
            maximum_positions=_i(raw.get("maximumPositions", raw.get("maximumPairs")), 30),
            long_slots=_i(raw.get("longSlots", raw.get("maximumLongPositions")), 20),
            short_slots=_i(raw.get("shortSlots", raw.get("maximumShortPositions")), 10),
            minimum_leverage=_i(raw.get("minimumLeverage", raw.get("leverage")), 50),
            entry_margin_usd=_f(raw.get("entryMarginUsd", raw.get("baseMarginUsd")), 5.0),
            dca_distance=_f(raw.get("dcaDistance", raw.get("longDcaDistance")), .003),
            dca_margin_usd=_f(raw.get("dcaMarginUsd"), 2.0),
            max_dca=_i(raw.get("maxDca", raw.get("longMaxDca")), 3),
            take_profit=_f(raw.get("takeProfit"), .015),
        )
        return cfg.validated()

    def validated(self) -> "MultiBbConfig":
        if self.engine != ENGINE: raise ValueError("Alleen de nieuwe Multi BB-strategie is toegestaan")
        if not 1 <= self.universe_top_n <= 200: raise ValueError("Top-N moet tussen 1 en 200 liggen")
        if not 1 <= self.maximum_positions <= self.universe_top_n: raise ValueError("Max posities moet tussen 1 en Top-N liggen")
        if self.long_slots < 0 or self.short_slots < 0 or self.long_slots + self.short_slots != self.maximum_positions:
            raise ValueError("LONG + SHORT slots moet exact gelijk zijn aan max posities")
        if not 1 <= self.minimum_leverage <= 300: raise ValueError("Minimum leverage moet tussen 1x en 300x liggen")
        if self.entry_margin_usd <= 0 or self.dca_margin_usd <= 0: raise ValueError("Entry- en DCA-margin moeten positief zijn")
        if not .0001 <= self.dca_distance <= .50: raise ValueError("DCA-afstand is ongeldig")
        if not 0 <= self.max_dca <= 50: raise ValueError("Max DCA moet tussen 0 en 50 liggen")
        if not .001 <= self.take_profit <= .20: raise ValueError("Take Profit moet tussen 0,1% en 20% liggen")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {
            "engine": ENGINE, "strategyKind": ENGINE, "name": self.name, "version": self.version, "mode": self.mode,
            "universeTopN": self.universe_top_n, "maximumPositions": self.maximum_positions,
            "longSlots": self.long_slots, "shortSlots": self.short_slots, "minimumLeverage": self.minimum_leverage,
            "entryMarginUsd": self.entry_margin_usd, "dcaDistance": self.dca_distance,
            "dcaMarginUsd": self.dca_margin_usd, "maxDca": self.max_dca, "takeProfit": self.take_profit,
            "entryMode": "immediate_fill", "marginMode": "cross", "autoRestart": True,
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


def _plan_new(client: Any, row: dict[str, Any], price: float, margin: float, minimum_leverage: int) -> PairExecutionPlan:
    symbol = str(row.get("symbol", "")).upper(); bracket_rows = _brackets(client.leverage_brackets(symbol), symbol)
    candidates = sorted({_i(x.get("initialLeverage")) for x in bracket_rows if _i(x.get("initialLeverage")) >= minimum_leverage}, reverse=True)
    if not candidates: raise ValueError(f"{symbol}: max leverage lager dan minimum {minimum_leverage}x")
    last: Exception | None = None
    for leverage in candidates:
        try: return plan_pair(row, bracket_rows, price, margin * leverage, accepted_leverage=leverage)
        except Exception as exc: last = exc
    raise ValueError(f"{symbol}: geen uitvoerbare order op minimaal {minimum_leverage}x") from last


def _plan_add(client: Any, row: dict[str, Any], price: float, margin: float, leverage: int, existing_notional: float) -> PairExecutionPlan:
    symbol = str(row.get("symbol", "")).upper(); bracket_rows = _brackets(client.leverage_brackets(symbol), symbol)
    return plan_pair(row, bracket_rows, price, margin * leverage, accepted_leverage=leverage, existing_contract_notional=existing_notional)


def _position_map(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {}
    for row in positions:
        qty = abs(_f(row.get("positionAmt")))
        side = str(row.get("positionSide", "")).upper(); symbol = str(row.get("symbol", "")).upper()
        if qty > 0 and side in {"LONG", "SHORT"}: out[f"{symbol}|{side}"] = row
    return out


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
    available = _f(account.get("availableBalance", account.get("availableMargin")))
    actions: list[dict[str, Any]] = []

    # Exchange truth reconciles every already-managed leg; a manual add never resets/increments the automatic DCA counter.
    for key in list(state):
        row = pmap.get(key)
        if row is None:
            state.pop(key, None); continue
        st = dict(state[key]); qty = abs(_f(row.get("positionAmt"))); entry = _f(row.get("entryPrice")); leverage = max(1, _i(row.get("leverage"), st.get("leverage", 1)))
        if abs(qty - _f(st.get("lastKnownQty"))) > 1e-12 or abs(entry - _f(st.get("lastKnownEntry"))) > 1e-12:
            st["manualOrExchangeReconciledAtMs"] = timestamp_ms
        st.update({"lastKnownQty": qty, "lastKnownEntry": entry, "leverage": leverage, "updatedAtMs": timestamp_ms}); state[key] = st

    # Management priority: full TP, then capped DCA.
    for key, st0 in list(state.items()):
        if sent >= budget: break
        row = pmap.get(key)
        if row is None: continue
        symbol, side = key.split("|", 1); mark = _f(row.get("markPrice"), prices.get(symbol, 0)); entry = _f(row.get("entryPrice")); qty = abs(_f(row.get("positionAmt")))
        if mark <= 0 or entry <= 0 or qty <= 0 or (symbol, side) in order_keys: continue
        tp_price = entry * (1 + settings.take_profit if side == "LONG" else 1 - settings.take_profit)
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
        if dca_count >= settings.max_dca or anchor <= 0: continue
        trigger = anchor * (1 - settings.dca_distance if side == "LONG" else 1 + settings.dca_distance)
        due = mark <= trigger if side == "LONG" else mark >= trigger
        if not due: continue
        row_info = info_map.get(symbol); leverage = max(1, _i(row.get("leverage")))
        if row_info is None: continue
        try: plan = _plan_add(client, row_info, mark, settings.dca_margin_usd, leverage, qty * mark)
        except Exception as exc:
            actions.append({"kind": "DCA_BLOCKED", "symbol": symbol, "side": side, "reason": str(exc)}); continue
        required = float(plan.notional_per_leg) / leverage
        if available < required * 1.05:
            actions.append({"kind": "DCA_MARGIN_WAIT", "symbol": symbol, "side": side}); continue
        actions.append({"kind": "DCA", "symbol": symbol, "side": side, "number": dca_count + 1, "trigger": trigger})
        if not dry_run:
            result = execute_leg_once(client, plan, side=PositionSide(side), action="OPEN", id_prefix=f"mbb-dca-{hashlib.sha256((uid+key+str(dca_count+1)+str(timestamp_ms)).encode()).hexdigest()[:12]}", confirm=True,
                                      new_position_leverage=leverage, before_submit=before_order)
            fill = result.get("result") or {}; fill_price = _f(fill.get("avgPrice"), mark)
            st = dict(st0); st.update({"dcaCount": dca_count + 1, "lastBotFillPrice": fill_price, "updatedAtMs": timestamp_ms}); state[key] = st
            ref.set({"multiBbPositions": state, "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                     "lastReason": f"Multi DCA actief; DCA {dca_count + 1} bevestigd op {symbol}"}, merge=True)
            ref.collection("audit").add({"event": "MULTI_BB_DCA", "symbol": symbol, "side": side, "dcaNumber": dca_count + 1, "timestamp": datetime.now(timezone.utc)})
        available -= required; sent += 1

    active = _position_map(client.position_risk()) if sent and not dry_run else pmap
    active_symbols = {k.split("|", 1)[0] for k in active}
    long_count = sum(1 for k in active if k.endswith("|LONG")); short_count = sum(1 for k in active if k.endswith("|SHORT"))
    long_need = max(0, settings.long_slots - long_count); short_need = max(0, settings.short_slots - short_count)

    # New seats: fill immediately from Top-N volume after leverage/order/margin checks.
    for ranked_row in ranked:
        if sent >= budget or (long_need <= 0 and short_need <= 0): break
        symbol = ranked_row["symbol"]
        if symbol in active_symbols or symbol not in info_map or prices.get(symbol, 0) <= 0: continue
        try:
            bracket_payload = client.leverage_brackets(symbol); maximum = max_contract_leverage(bracket_payload, symbol)
        except Exception as exc:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": f"leverage-data: {exc}"}); continue
        if maximum < settings.minimum_leverage:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": f"max {maximum}x < minimum {settings.minimum_leverage}x"}); continue
        side = "LONG" if long_need > 0 else "SHORT" if short_need > 0 else ""
        if not side: break
        try: plan = _plan_new(client, info_map[symbol], prices[symbol], settings.entry_margin_usd, settings.minimum_leverage)
        except Exception as exc:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": str(exc)}); continue
        required = float(plan.notional_per_leg) / plan.leverage
        if available < required * 1.05:
            actions.append({"kind": "ENTRY_MARGIN_WAIT", "symbol": symbol, "side": side}); continue
        entry_action = {"kind": "ENTRY", "symbol": symbol, "side": side, "leverage": plan.leverage, "marginUsd": required, "entryMode": "immediate_fill"}
        if dry_run:
            actions.append(entry_action)
        else:
            try:
                result = execute_leg_once(client, plan, side=PositionSide(side), action="OPEN", id_prefix=f"mbb-open-{hashlib.sha256((uid+symbol+side+str(timestamp_ms)).encode()).hexdigest()[:12]}", confirm=True,
                                          new_position_leverage=plan.leverage, before_submit=before_order)
            except NewPositionLeverageBlocked as exc:
                actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": exc.reason_code})
                continue
            fill = result.get("result") or {}; fill_price = _f(fill.get("avgPrice"), prices[symbol]); fill_qty = _f(fill.get("executedQty"), float(plan.quantity))
            key = f"{symbol}|{side}"; state[key] = {"cycleId": hashlib.sha256((uid+key+str(timestamp_ms)).encode()).hexdigest()[:16], "dcaCount": 0,
                "lastBotFillPrice": fill_price, "lastKnownQty": fill_qty, "lastKnownEntry": fill_price, "leverage": plan.leverage,
                "cycleStartedAtMs": timestamp_ms, "updatedAtMs": timestamp_ms, "botManaged": True}
            ref.set({"multiBbPositions": state, "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                     "lastReason": f"Multi DCA actief; nieuwe {side} geopend op {symbol}"}, merge=True)
            ref.collection("audit").add({"event": "MULTI_BB_ENTRY", "symbol": symbol, "side": side, "leverage": plan.leverage, "timestamp": datetime.now(timezone.utc)})
            actions.append(entry_action)
        active_symbols.add(symbol); long_need -= 1 if side == "LONG" else 0; short_need -= 1 if side == "SHORT" else 0
        available -= required; sent += 1

    report = {"engine": ENGINE, "ordersSent": 0 if dry_run else sent, "simulatedActions": len(actions) if dry_run else 0,
              "actions": actions[-30:], "rankedTopN": ranked, "longSlots": settings.long_slots, "shortSlots": settings.short_slots,
              "activeLong": settings.long_slots - long_need, "activeShort": settings.short_slots - short_need,
              "updatedAtMs": timestamp_ms}
    if not dry_run:
        ref.set({"multiBbPositions": state, "multiBbReport": report, "multiBbAdoptionPending": False,
                 "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                 "lastReason": "Multi DCA actief; vrije slots worden direct gevuld"}, merge=True)
    return {"status": "simulated" if dry_run else "running", "action": "MULTI_BB", **report}
