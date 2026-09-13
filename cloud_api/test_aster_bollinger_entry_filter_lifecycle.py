from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
import time

import pytest

import aster_multi_bb_core as core
import aster_multi_bb as facade
from aster_execution import PairExecutionPlan


class Ref:
    def __init__(self):
        self.writes = []
    def set(self, payload, **kwargs):
        self.writes.append(payload)
    def collection(self, *args, **kwargs):
        return self
    def add(self, *args, **kwargs):
        pass


class Market:
    def __init__(self, symbols, prices):
        self.symbols = list(symbols)
        self.prices = dict(prices)
        self.kline_calls = []

    def public_exchange_info(self):
        return {"symbols": [{"symbol": symbol} for symbol in self.symbols]}

    def ticker_prices(self):
        return [{"symbol": symbol, "price": str(self.prices[symbol])} for symbol in self.symbols]

    def ticker_24h(self):
        return []

    def leverage_brackets(self, symbol):
        return []

    def klines(self, *, symbol, interval, limit):
        self.kline_calls.append((symbol, interval, limit))
        now_open = int(time.time() * 1000 // 900_000 * 900_000)
        closes = list(range(90, 110))
        return [[now_open - (19-i)*900_000, "0", "0", "0", str(close), "0"] for i, close in enumerate(closes)]


def _position(symbol, side, mark=100.0, qty=1.0, entry=100.0):
    return {
        "symbol": symbol,
        "positionSide": side,
        "positionAmt": str(qty),
        "entryPrice": str(entry),
        "markPrice": str(mark),
        "leverage": "10",
    }


def _state_for(positions):
    now = int(time.time() * 1000)
    return {
        f"{row['symbol']}|{row['positionSide']}": {
            "cycleId": f"cycle-{row['symbol']}-{row['positionSide']}",
            "dcaCount": 0,
            "lastBotFillPrice": float(row["entryPrice"]),
            "lastKnownQty": abs(float(row["positionAmt"])),
            "lastKnownEntry": float(row["entryPrice"]),
            "leverage": int(row["leverage"]),
            "cycleStartedAtMs": now - 60_000,
            "updatedAtMs": now - 1_000,
            "botManaged": True,
        }
        for row in positions
    }


def _cfg(*, maximum, longs, shorts, top_n=100, enabled=True, max_dca=0):
    return core.MultiBbConfig.from_mapping({
        "universeTopN": top_n,
        "maximumPositions": maximum,
        "longSlots": longs,
        "shortSlots": shorts,
        "minimumLeverage": 1,
        "entryMarginUsd": 1,
        "entryNotionalUsd": 10,
        "dcaDistance": 0.003,
        "dcaMarginUsd": 1,
        "maxDca": max_dca,
        "takeProfitEnabled": False,
        "bollingerEntryFilter15mEnabled": enabled,
    })


def _patch_planning(monkeypatch, candidates):
    monkeypatch.setattr(core, "rank_top_volume", lambda *_: [{"symbol": symbol} for symbol in candidates])
    monkeypatch.setattr(core, "max_contract_leverage", lambda *_: 100)

    def plan_new(_client, row, price, **kwargs):
        plan = PairExecutionPlan(row["symbol"], Decimal("1"), Decimal("10"), 10)
        return plan, {"exchangeMaxLeverage": 100, "forcedBelowConfiguredMinimum": False}

    monkeypatch.setattr(core, "_plan_new", plan_new)


def _run(market, cfg, *, positions=None, raw_state=None, dry_run=True, order_budget=200):
    positions = list(positions or [])
    raw_state = dict(raw_state or {})
    return core.run_multi_bb_step(
        client=market,
        ref=Ref(),
        raw_state=raw_state,
        settings=cfg,
        uid="bollinger-lifecycle-test",
        account={"availableBalance": 100_000, "totalMarginBalance": 100_000},
        positions=positions,
        open_orders=[],
        timestamp_ms=int(time.time() * 1000),
        dry_run=dry_run,
        order_budget=order_budget,
    )


def _candidate_symbols(prefix, count):
    return [f"{prefix}{i:03d}USDT" for i in range(count)]


def _existing_positions(long_count, short_count):
    positions = []
    for i in range(long_count):
        positions.append(_position(f"EL{i:03d}USDT", "LONG"))
    for i in range(short_count):
        positions.append(_position(f"ES{i:03d}USDT", "SHORT"))
    return positions


def test_runtime_total_slots_50_to_60_filters_every_new_seat(monkeypatch):
    existing = _existing_positions(25, 25)
    candidates = _candidate_symbols("C", 10)
    prices = {row["symbol"]: 100 for row in existing}
    prices.update({symbol: (80 if i % 2 == 0 else 120) for i, symbol in enumerate(candidates)})
    symbols = [row["symbol"] for row in existing] + candidates
    market = Market(symbols, prices)
    _patch_planning(monkeypatch, candidates)
    result = _run(market, _cfg(maximum=60, longs=30, shorts=30), positions=existing,
                  raw_state={"multiBbPositions": _state_for(existing)})
    entries = [a for a in result["actions"] if a.get("kind") == "ENTRY"]
    assert len(entries) == 10
    assert result["remainingLong"] == 0 and result["remainingShort"] == 0
    assert len(market.kline_calls) == 10


def test_runtime_long_slots_25_to_30_all_new_longs_are_filtered(monkeypatch):
    existing = _existing_positions(25, 0)
    candidates = _candidate_symbols("L", 5)
    prices = {row["symbol"]: 100 for row in existing} | {symbol: 80 for symbol in candidates}
    market = Market([row["symbol"] for row in existing] + candidates, prices)
    _patch_planning(monkeypatch, candidates)
    result = _run(market, _cfg(maximum=30, longs=30, shorts=0), positions=existing,
                  raw_state={"multiBbPositions": _state_for(existing)})
    entries = [a for a in result["actions"] if a.get("kind") == "ENTRY"]
    assert len(entries) == 5
    assert all(a["side"] == "LONG" for a in entries)
    assert len(market.kline_calls) == 5


def test_runtime_short_slots_25_to_30_all_new_shorts_are_filtered(monkeypatch):
    existing = _existing_positions(0, 25)
    candidates = _candidate_symbols("S", 5)
    prices = {row["symbol"]: 100 for row in existing} | {symbol: 120 for symbol in candidates}
    market = Market([row["symbol"] for row in existing] + candidates, prices)
    _patch_planning(monkeypatch, candidates)
    result = _run(market, _cfg(maximum=30, longs=0, shorts=30), positions=existing,
                  raw_state={"multiBbPositions": _state_for(existing)})
    entries = [a for a in result["actions"] if a.get("kind") == "ENTRY"]
    assert len(entries) == 5
    assert all(a["side"] == "SHORT" for a in entries)
    assert len(market.kline_calls) == 5


def test_slots_lowered_then_raised_revalidate_current_market_not_old_pass(monkeypatch):
    existing = _existing_positions(15, 15)
    candidates = _candidate_symbols("R", 20)
    prices = {row["symbol"]: 100 for row in existing} | {symbol: 100 for symbol in candidates}
    market = Market([row["symbol"] for row in existing] + candidates, prices)
    _patch_planning(monkeypatch, candidates)
    state = {"multiBbPositions": _state_for(existing)}

    lowered = _run(market, _cfg(maximum=30, longs=15, shorts=15), positions=existing, raw_state=state)
    assert not any(a.get("kind") == "ENTRY" for a in lowered["actions"])

    raised_blocked = _run(market, _cfg(maximum=50, longs=25, shorts=25), positions=existing, raw_state=state)
    assert raised_blocked["entryStatus"] == "WAITING_BOLLINGER_ENTRY"
    assert not any(a.get("kind") == "ENTRY" for a in raised_blocked["actions"])

    for i, symbol in enumerate(candidates):
        market.prices[symbol] = 80 if i % 2 == 0 else 120
    raised_allowed = _run(market, _cfg(maximum=50, longs=25, shorts=25), positions=existing, raw_state=state)
    entries = [a for a in raised_allowed["actions"] if a.get("kind") == "ENTRY"]
    assert len(entries) == 20


def test_closed_seat_reseat_is_freshly_filtered(monkeypatch):
    candidate = "NEWUSDT"
    closed = _position("OLDUSDT", "LONG")
    market = Market(["OLDUSDT", candidate], {"OLDUSDT": 100, candidate: 100})
    _patch_planning(monkeypatch, [candidate])
    raw_state = {"multiBbPositions": _state_for([closed])}

    blocked = _run(market, _cfg(maximum=1, longs=1, shorts=0), positions=[], raw_state=raw_state)
    assert any(a.get("kind") == "REENTRY_STATE_CLEARED" for a in blocked["actions"])
    assert blocked["entryStatus"] == "WAITING_BOLLINGER_ENTRY"

    market.prices[candidate] = 80
    allowed = _run(market, _cfg(maximum=1, longs=1, shorts=0), positions=[], raw_state=raw_state)
    assert any(a.get("kind") == "ENTRY" and a.get("symbol") == candidate for a in allowed["actions"])


def test_restart_recovery_keeps_existing_position_and_filters_only_empty_seat(monkeypatch):
    existing = [_position("KEEPUSDT", "LONG")]
    candidate = "EMPTYUSDT"
    market = Market(["KEEPUSDT", candidate], {"KEEPUSDT": 100, candidate: 100})
    _patch_planning(monkeypatch, [candidate])
    raw_state = {"multiBbPositions": _state_for(existing)}
    result = _run(market, _cfg(maximum=2, longs=2, shorts=0), positions=existing, raw_state=raw_state)
    assert result["activeLong"] == 1 and result["remainingLong"] == 1
    assert result["entryStatus"] == "WAITING_BOLLINGER_ENTRY"
    assert not any(a.get("kind") in {"TP", "DCA"} and a.get("symbol") == "KEEPUSDT" for a in result["actions"])


def test_runtime_toggle_off_on_off_changes_only_future_primary_entries(monkeypatch):
    candidate = "TOGGLEUSDT"
    market = Market([candidate], {candidate: 100})
    _patch_planning(monkeypatch, [candidate])

    off_first = _run(market, _cfg(maximum=1, longs=1, shorts=0, enabled=False))
    calls_after_off_first = len(market.kline_calls)
    assert any(a.get("kind") == "ENTRY" for a in off_first["actions"])
    assert calls_after_off_first == 0

    on = _run(market, _cfg(maximum=1, longs=1, shorts=0, enabled=True))
    assert on["entryStatus"] == "WAITING_BOLLINGER_ENTRY"
    assert len(market.kline_calls) > calls_after_off_first

    calls_before_off_again = len(market.kline_calls)
    off_again = _run(market, _cfg(maximum=1, longs=1, shorts=0, enabled=False))
    assert any(a.get("kind") == "ENTRY" for a in off_again["actions"])
    assert len(market.kline_calls) == calls_before_off_again


def test_dca_is_never_gated_by_bollinger_filter(monkeypatch):
    existing = [_position("DCAUSDT", "LONG", mark=99, entry=100)]
    market = Market(["DCAUSDT"], {"DCAUSDT": 99})
    _patch_planning(monkeypatch, [])

    def plan_add(_client, row, mark, margin, leverage, existing_notional, minimum_leverage):
        plan = PairExecutionPlan(row["symbol"], Decimal("1"), Decimal("10"), 10)
        tier = {
            "additionalMarginRequired": 1.0,
            "leverage": 10,
            "previousLeverage": 10,
            "tierReduction": False,
            "projectedNotional": existing_notional + 10,
        }
        return plan, tier

    monkeypatch.setattr(core, "_plan_add", plan_add)
    result = _run(market, _cfg(maximum=1, longs=1, shorts=0, enabled=True, max_dca=3),
                  positions=existing, raw_state={"multiBbPositions": _state_for(existing)})
    assert any(a.get("kind") == "DCA" and a.get("symbol") == "DCAUSDT" for a in result["actions"])
    assert market.kline_calls == []


def test_pre_order_recheck_rejects_candidate_that_moved_back_inside_band(monkeypatch):
    symbol = "FASTUSDT"
    market = Market([symbol], {symbol: 80})
    _patch_planning(monkeypatch, [symbol])
    submitted = []

    def fake_execute(client, plan, *, side, action, before_submit=None, **kwargs):
        market.prices[symbol] = 100
        assert before_submit is not None
        before_submit(SimpleNamespace(symbol=symbol, side=side, action=action))
        submitted.append(symbol)
        return {"result": {"avgPrice": "100", "executedQty": "1"}}

    monkeypatch.setattr(core, "execute_leg_once", fake_execute)
    result = _run(market, _cfg(maximum=1, longs=1, shorts=0, enabled=True), dry_run=False)
    assert submitted == []
    assert any(a.get("kind") == "ENTRY_SKIP" and a.get("stage") == "pre_order" for a in result["actions"])
    assert not any(a.get("kind") == "ENTRY" for a in result["actions"])


def test_load_50_to_100_filters_all_50_new_seats_without_overfill(monkeypatch):
    existing = _existing_positions(25, 25)
    candidates = _candidate_symbols("LOAD", 50)
    prices = {row["symbol"]: 100 for row in existing}
    prices.update({symbol: (80 if i % 2 == 0 else 120) for i, symbol in enumerate(candidates)})
    market = Market([row["symbol"] for row in existing] + candidates, prices)
    _patch_planning(monkeypatch, candidates)
    result = _run(market, _cfg(maximum=100, longs=50, shorts=50, top_n=100), positions=existing,
                  raw_state={"multiBbPositions": _state_for(existing)}, order_budget=100)
    # The report deliberately exposes only actions[-30:], so use final counters
    # plus market-data calls to prove all 50 newly created seats were filtered.
    entries_in_bounded_report = [a for a in result["actions"] if a.get("kind") == "ENTRY"]
    assert len(entries_in_bounded_report) == 30
    assert len({a["symbol"] for a in entries_in_bounded_report}) == 30
    assert len(market.kline_calls) == 50
    assert len({call[0] for call in market.kline_calls}) == 50
    assert result["activeLong"] == 50 and result["activeShort"] == 50
    assert result["remainingLong"] == 0 and result["remainingShort"] == 0


@pytest.mark.parametrize("profit_lock_enabled", [False, True])
def test_profit_lock_configuration_is_independent_of_bollinger_setting(profit_lock_enabled):
    cfg = facade.MultiBbConfig.from_mapping({
        "universeTopN": 10,
        "maximumPositions": 2,
        "longSlots": 2,
        "shortSlots": 0,
        "minimumLeverage": 1,
        "entryMarginUsd": 1,
        "entryNotionalUsd": 10,
        "dcaMarginUsd": 1,
        "bollingerEntryFilter15mEnabled": True,
        "profitLockLadderEnabled": profit_lock_enabled,
    })
    public = cfg.public_dict()
    assert public["bollingerEntryFilter15mEnabled"] is True
    assert public["profitLockLadderEnabled"] is profit_lock_enabled
