from __future__ import annotations

from decimal import Decimal
import time

import aster_multi_bb_core as core
from aster_execution import PairExecutionPlan


SYMBOLS = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]


class Ref:
    def set(self, *args, **kwargs): pass
    def collection(self, *args, **kwargs): return self
    def add(self, *args, **kwargs): pass


class Market:
    def __init__(self, prices):
        self.prices = dict(prices)
        self.kline_calls = []

    def public_exchange_info(self):
        return {"symbols": [{"symbol": s} for s in SYMBOLS]}

    def ticker_prices(self):
        return [{"symbol": s, "price": str(self.prices[s])} for s in SYMBOLS]

    def ticker_24h(self): return []
    def leverage_brackets(self, symbol): return []

    def klines(self, *, symbol, interval, limit):
        self.kline_calls.append((symbol, interval, limit))
        now_open = int(time.time() * 1000 // 900_000 * 900_000)
        closes = list(range(81, 101))
        return [[now_open - (19-i)*900_000, "0", "0", "0", str(close), "0"] for i, close in enumerate(closes)]


def setup(monkeypatch, candidates=SYMBOLS):
    monkeypatch.setattr(core, "rank_top_volume", lambda *_: [{"symbol": s} for s in candidates])
    monkeypatch.setattr(core, "max_contract_leverage", lambda *_: 100)
    def plan(_client, row, price, **kwargs):
        p = PairExecutionPlan(row["symbol"], Decimal("1"), Decimal("10"), 10)
        return p, {"exchangeMaxLeverage": 100, "forcedBelowConfiguredMinimum": False}
    monkeypatch.setattr(core, "_plan_new", plan)


def settings(*, side="LONG", enabled=True, manual=False):
    return core.MultiBbConfig.from_mapping({
        "universeTopN": 3, "maximumPositions": 1,
        "longSlots": 1 if side == "LONG" else 0,
        "shortSlots": 1 if side == "SHORT" else 0,
        "minimumLeverage": 1, "entryMarginUsd": 1, "entryNotionalUsd": 10,
        "dcaMarginUsd": 1, "bollingerEntryFilter15mEnabled": enabled,
        "manualSymbolSelectionEnabled": manual,
        "manualSymbols": [{"symbol": "CCCUSDT", "side": side}] if manual else [],
    })


def run(market, cfg):
    return core.run_multi_bb_step(client=market, ref=Ref(), raw_state={}, settings=cfg, uid="u", account={"availableBalance": 1000},
                                  positions=[], open_orders=[], timestamp_ms=int(time.time()*1000), dry_run=True, order_budget=10)


def test_long_rejects_two_candidates_then_uses_next_pass(monkeypatch):
    setup(monkeypatch)
    result = run(Market({"AAAUSDT": 90, "BBBUSDT": 95, "CCCUSDT": 60}), settings(side="LONG"))
    entries = [a for a in result["actions"] if a["kind"] == "ENTRY"]
    rejects = [a for a in result["actions"] if a["kind"] == "ENTRY_SKIP" and a.get("bollingerEntryFilter15m")]
    assert [a["symbol"] for a in rejects] == ["AAAUSDT", "BBBUSDT"]
    assert [a["symbol"] for a in entries] == ["CCCUSDT"]


def test_short_rejects_two_candidates_then_uses_next_pass(monkeypatch):
    setup(monkeypatch)
    result = run(Market({"AAAUSDT": 90, "BBBUSDT": 95, "CCCUSDT": 120}), settings(side="SHORT"))
    entries = [a for a in result["actions"] if a["kind"] == "ENTRY"]
    rejects = [a for a in result["actions"] if a["kind"] == "ENTRY_SKIP" and a.get("bollingerEntryFilter15m")]
    assert [a["symbol"] for a in rejects] == ["AAAUSDT", "BBBUSDT"]
    assert [a["symbol"] for a in entries] == ["CCCUSDT"]


def test_no_valid_candidate_is_waiting_not_error(monkeypatch):
    setup(monkeypatch)
    result = run(Market({s: 90 for s in SYMBOLS}), settings(side="LONG"))
    assert not any(a["kind"] == "ENTRY" for a in result["actions"])
    assert result["entryStatus"] == "WAITING_BOLLINGER_ENTRY"
    assert result["remainingLong"] == 1


def test_manual_selection_cannot_bypass_filter(monkeypatch):
    setup(monkeypatch, ["AAAUSDT"])
    blocked = run(Market({"AAAUSDT": 90, "BBBUSDT": 90, "CCCUSDT": 90}), settings(side="LONG", manual=True))
    assert blocked["entryStatus"] == "WAITING_BOLLINGER_ENTRY"
    allowed = run(Market({"AAAUSDT": 90, "BBBUSDT": 90, "CCCUSDT": 60}), settings(side="LONG", manual=True))
    assert any(a["kind"] == "ENTRY" and a["symbol"] == "CCCUSDT" for a in allowed["actions"])


def test_filter_off_preserves_old_candidate_flow_and_skips_15m_calls(monkeypatch):
    setup(monkeypatch)
    market = Market({s: 90 for s in SYMBOLS})
    result = run(market, settings(side="LONG", enabled=False))
    assert any(a["kind"] == "ENTRY" and a["symbol"] == "AAAUSDT" for a in result["actions"])
    assert market.kline_calls == []


def test_two_free_sides_are_scanned_independently_when_short_signal_arrives_first(monkeypatch):
    setup(monkeypatch)
    cfg = core.MultiBbConfig.from_mapping({
        "universeTopN": 3, "maximumPositions": 2,
        "longSlots": 1, "shortSlots": 1,
        "minimumLeverage": 1, "entryMarginUsd": 1, "entryNotionalUsd": 10,
        "dcaMarginUsd": 1, "bollingerEntryFilter15mEnabled": True,
    })
    # AAA is far above the upper band: it must be allowed to fill the free SHORT
    # even though equal LONG/SHORT counts make LONG the allocator's preferred side.
    # BBB is below the lower band and then fills the remaining LONG seat.
    result = run(Market({"AAAUSDT": 120, "BBBUSDT": 60, "CCCUSDT": 90}), cfg)
    entries = [(a["symbol"], a["side"]) for a in result["actions"] if a["kind"] == "ENTRY"]
    assert entries == [("AAAUSDT", "SHORT"), ("BBBUSDT", "LONG")]
    assert result["remainingLong"] == 0
    assert result["remainingShort"] == 0


def test_filter_off_keeps_legacy_preferred_side_allocator_with_two_free_sides(monkeypatch):
    setup(monkeypatch)
    cfg = core.MultiBbConfig.from_mapping({
        "universeTopN": 3, "maximumPositions": 2,
        "longSlots": 1, "shortSlots": 1,
        "minimumLeverage": 1, "entryMarginUsd": 1, "entryNotionalUsd": 10,
        "dcaMarginUsd": 1, "bollingerEntryFilter15mEnabled": False,
    })
    market = Market({"AAAUSDT": 120, "BBBUSDT": 60, "CCCUSDT": 90})
    result = run(market, cfg)
    entries = [(a["symbol"], a["side"]) for a in result["actions"] if a["kind"] == "ENTRY"]
    assert entries == [("AAAUSDT", "LONG"), ("BBBUSDT", "SHORT")]
    assert market.kline_calls == []

def test_all_new_seat_entry_routes_share_one_core_gate_source_contract():
    source = (core.__file__ and open(core.__file__, encoding="utf8").read())
    assert source.count("stage=\"candidate\"") == 1
    assert source.count("stage=\"pre_order\"") == 1
    assert "if settings.bollinger_entry_filter_15m_enabled" in source
    assert 'before_submit=entry_before_submit' in source
    # DCA stays on the existing OPEN execution path with its own mbb-dca id and
    # the pre-existing before_order callback, so the Bollinger pre-order wrapper
    # cannot intercept a DCA.
    assert 'id_prefix=f"mbb-dca-' in source
    assert 'allow_existing_contract_leverage_change=True,before_submit=before_order' in source
    # Paired hedge/recovery legs likewise retain the existing callback rather
    # than the primary-entry Bollinger wrapper.
    assert 'mbb-asym-short-' in source and 'before_submit=before_order' in source
