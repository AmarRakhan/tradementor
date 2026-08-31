from __future__ import annotations

from datetime import datetime, timezone
import time
import pytest
import aster_multi_bb
from aster_execution import NewPositionLeverageBlocked

from aster_multi_bb import (
    ENGINE, MultiBbConfig, max_contract_leverage,
    rank_top_volume, run_multi_bb_step,
)


def symbol_row(symbol="AAAUSDT"):
    return {"symbol":symbol,"quoteAsset":"USDT","status":"TRADING","filters":[
        {"filterType":"PRICE_FILTER","minPrice":"0.001","maxPrice":"1000000","tickSize":"0.001"},
        {"filterType":"LOT_SIZE","minQty":"0.001","maxQty":"1000000","stepSize":"0.001"},
        {"filterType":"MARKET_LOT_SIZE","minQty":"0.001","maxQty":"1000000","stepSize":"0.001"},
        {"filterType":"MIN_NOTIONAL","notional":"5"},
    ]}


def kline_rows(closes, now_ms=None):
    now_ms=now_ms or int(time.time()*1000)
    start=now_ms-len(closes)*60_000
    return [[start+i*60_000,0,0,0,str(c),0,start+(i+1)*60_000-1] for i,c in enumerate(closes)]


class Collection:
    def add(self, row): pass


class Ref:
    def __init__(self): self.updates=[]
    def set(self, row, merge=True): self.updates.append(dict(row))
    def collection(self, name): return Collection()


class Client:
    def __init__(self, *, positions=None, tickers=None, prices=None, closes=None, leverage=100):
        self.positions=list(positions or [])
        self._tickers=list(tickers or [])
        self._prices=dict(prices or {})
        self._closes=dict(closes or {})
        self._leverage=leverage
        symbols={x.get("symbol") for x in self._tickers}|set(self._prices)|{x.get("symbol") for x in self.positions}
        self._info={"symbols":[symbol_row(x) for x in sorted(s for s in symbols if s)]}
    def public_exchange_info(self): return self._info
    def ticker_prices(self): return [{"symbol":s,"price":str(p)} for s,p in self._prices.items()]
    def ticker_24h(self): return self._tickers
    def leverage_brackets(self, symbol=None):
        s=symbol or "AAAUSDT"
        return [{"symbol":s,"brackets":[{"notionalFloor":"0","notionalCap":"1000000","initialLeverage":str(self._leverage),"maintMarginRatio":".004"}]}]
    def klines(self, symbol, interval, limit):
        assert interval=="1m"
        rows=kline_rows(self._closes.get(symbol,[100]*25))
        return rows[-limit:]
    def position_risk(self, symbol=None):
        return [x for x in self.positions if symbol is None or x.get("symbol")==symbol]


def cfg(**kw):
    base={"engine":ENGINE,"universeTopN":3,"maximumPositions":1,"longSlots":1,"shortSlots":0,
          "minimumLeverage":50,"entryMarginUsd":5,"dcaDistance":.003,"dcaMarginUsd":2,
          "maxDca":3,"takeProfit":.015}
    base.update(kw)
    return MultiBbConfig.from_mapping(base)


def test_config_requires_slot_sum_and_topn_capacity():
    with pytest.raises(ValueError): cfg(maximumPositions=2,longSlots=1,shortSlots=0)
    with pytest.raises(ValueError): cfg(universeTopN=1,maximumPositions=2,longSlots=1,shortSlots=1)


def test_top_volume_is_dynamic_and_usdt_only():
    info={"symbols":[symbol_row("AAAUSDT"),symbol_row("BBBUSDT"),symbol_row("CCCUSDT"),symbol_row("NOPEUSDC")|{"quoteAsset":"USDC"}]}
    rows=rank_top_volume([
        {"symbol":"BBBUSDT","quoteVolume":"20"},{"symbol":"AAAUSDT","quoteVolume":"30"},
        {"symbol":"CCCUSDT","quoteVolume":"10"},{"symbol":"NOPEUSDC","quoteVolume":"999"}],info,2)
    assert [x["symbol"] for x in rows]==["AAAUSDT","BBBUSDT"]


def test_entry_is_immediate_without_indicator_wait():
    class NoKlines(Client):
        def klines(self,*_a,**_k): raise AssertionError("entry mag geen Bollinger/candledata meer lezen")
    c=NoKlines(tickers=[{"symbol":"AAAUSDT","quoteVolume":"1000"}],prices={"AAAUSDT":100},leverage=100)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=cfg(),uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    entry=next(x for x in r["actions"] if x["kind"]=="ENTRY")
    assert entry["side"]=="LONG" and entry["entryMode"]=="immediate_fill"


def test_minimum_leverage_filter_and_maximum_leverage_selection():
    low=Client(leverage=25)
    high=Client(leverage=300)
    assert max_contract_leverage(low.leverage_brackets("AAAUSDT"),"AAAUSDT")==25
    assert max_contract_leverage(high.leverage_brackets("AAAUSDT"),"AAAUSDT")==300
    tick=[{"symbol":"AAAUSDT","quoteVolume":"1000"}]
    r=run_multi_bb_step(client=low,ref=Ref(),raw_state={},settings=cfg(),uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert not [x for x in r["actions"] if x["kind"]=="ENTRY"]
    high._tickers=tick; high._prices={"AAAUSDT":90}; high._info={"symbols":[symbol_row("AAAUSDT")]}
    r=run_multi_bb_step(client=high,ref=Ref(),raw_state={},settings=cfg(),uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    entry=next(x for x in r["actions"] if x["kind"]=="ENTRY")
    assert entry["leverage"]==300


def test_max_three_dcas_is_hard_cap():
    pos={"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"5","entryPrice":"100","markPrice":"90","leverage":"100"}
    state={"multiBbPositions":{"AAAUSDT|LONG":{"dcaCount":3,"lastBotFillPrice":100,"lastKnownQty":5,"lastKnownEntry":100,"cycleStartedAtMs":1}}}
    r=run_multi_bb_step(client=Client(positions=[pos],prices={"AAAUSDT":90},leverage=100),ref=Ref(),raw_state=state,settings=cfg(),uid="u",account={"availableBalance":"100"},positions=[pos],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert not [x for x in r["actions"] if x["kind"]=="DCA"]


def test_exchange_weighted_entry_drives_tp_after_manual_add():
    # Persisted entry was 100, but Aster says manual averaging changed the true weighted entry to 90.
    pos={"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"8","entryPrice":"90","markPrice":"91.35","leverage":"100"}
    state={"multiBbPositions":{"AAAUSDT|LONG":{"dcaCount":3,"lastBotFillPrice":95,"lastKnownQty":5,"lastKnownEntry":100,"cycleStartedAtMs":1}}}
    r=run_multi_bb_step(client=Client(positions=[pos],prices={"AAAUSDT":91.35},leverage=100),ref=Ref(),raw_state=state,settings=cfg(),uid="u",account={"availableBalance":"100"},positions=[pos],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    tp=next(x for x in r["actions"] if x["kind"]=="TP")
    assert tp["entry"]==90
    assert tp["target"]==pytest.approx(91.35)


def test_manual_add_reconciles_without_resetting_dca_counter():
    pos={"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"8","entryPrice":"95","markPrice":"95","leverage":"100"}
    raw={"multiBbPositions":{"AAAUSDT|LONG":{"dcaCount":3,"lastBotFillPrice":90,"lastKnownQty":5,"lastKnownEntry":100,"cycleStartedAtMs":1}}}
    ref=Ref()
    run_multi_bb_step(client=Client(positions=[pos],prices={"AAAUSDT":95},leverage=100),ref=ref,raw_state=raw,settings=cfg(),uid="u",account={"availableBalance":"100"},positions=[pos],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=False)
    persisted=ref.updates[-1]["multiBbPositions"]["AAAUSDT|LONG"]
    assert persisted["dcaCount"]==3
    assert persisted["lastKnownQty"]==8
    assert persisted["lastKnownEntry"]==95
    assert persisted.get("manualOrExchangeReconciledAtMs")



def test_candidate_leverage_set_failure_skips_only_that_symbol(monkeypatch):
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"2000"},{"symbol":"BBBUSDT","quoteVolume":"1000"}],
             prices={"AAAUSDT":100,"BBBUSDT":100},leverage=100)
    original=aster_multi_bb.execute_leg_once
    def fake_execute(client, plan, **kwargs):
        if plan.symbol=="AAAUSDT":
            raise NewPositionLeverageBlocked("SYMBOL_LEVERAGE_SET_FAILED", plan.symbol)
        return {"result":{"avgPrice":"100","executedQty":str(plan.quantity)},"leverage":plan.leverage}
    monkeypatch.setattr(aster_multi_bb,"execute_leg_once",fake_execute)
    ref=Ref()
    r=run_multi_bb_step(client=c,ref=ref,raw_state={},settings=cfg(universeTopN=2),uid="u",account={"availableBalance":"100"},
        positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=False,order_budget=5)
    assert any(x["kind"]=="ENTRY_SKIP" and x["symbol"]=="AAAUSDT" and x["reason"]=="SYMBOL_LEVERAGE_SET_FAILED" for x in r["actions"])
    assert "BBBUSDT|LONG" in ref.updates[-1]["multiBbPositions"]
    assert r["status"]=="running"


def test_confirmed_entry_is_persisted_before_later_unknown_failure(monkeypatch):
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"3000"},{"symbol":"BBBUSDT","quoteVolume":"2000"}],
             prices={"AAAUSDT":100,"BBBUSDT":100},leverage=100)
    def fake_execute(client, plan, **kwargs):
        if plan.symbol=="BBBUSDT":
            raise RuntimeError("unknown transport failure after first confirmed fill")
        return {"result":{"avgPrice":"100","executedQty":str(plan.quantity)},"leverage":plan.leverage}
    monkeypatch.setattr(aster_multi_bb,"execute_leg_once",fake_execute)
    ref=Ref()
    with pytest.raises(RuntimeError):
        run_multi_bb_step(client=c,ref=ref,raw_state={},settings=cfg(universeTopN=2,maximumPositions=2,longSlots=2),uid="u",
            account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=False,order_budget=5)
    persisted=[u for u in ref.updates if "multiBbPositions" in u]
    assert persisted and "AAAUSDT|LONG" in persisted[-1]["multiBbPositions"]


def test_existing_position_is_adopted_only_after_explicit_start_flag():
    pos={"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"5","entryPrice":"100","markPrice":"100","leverage":"75"}
    ref=Ref(); raw={"multiBbAdoptionPending":True,"multiBbPositions":{}}
    run_multi_bb_step(client=Client(positions=[pos],prices={"AAAUSDT":100},leverage=75),ref=ref,raw_state=raw,settings=cfg(),uid="u",account={"availableBalance":"100"},positions=[pos],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=False)
    persisted=ref.updates[-1]
    assert persisted["multiBbAdoptionPending"] is False
    adopted=persisted["multiBbPositions"]["AAAUSDT|LONG"]
    assert adopted["adoptedExisting"] is True and adopted["dcaCount"]==0

def test_existing_long_short_same_symbol_blocks_adoption_and_sends_no_orders():
    positions=[
        {"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"5","entryPrice":"100","markPrice":"100","leverage":"75"},
        {"symbol":"AAAUSDT","positionSide":"SHORT","positionAmt":"4","entryPrice":"101","markPrice":"100","leverage":"75"},
    ]
    ref=Ref(); raw={"multiBbAdoptionPending":True,"multiBbPositions":{}}
    r=run_multi_bb_step(client=Client(positions=positions,prices={"AAAUSDT":100},leverage=75),ref=ref,raw_state=raw,
        settings=cfg(),uid="u",account={"availableBalance":"100"},positions=positions,open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=False)
    assert r["status"]=="blocked" and r["ordersSent"]==0
    assert ref.updates[-1]["enabled"] is False and ref.updates[-1]["phase"]=="MIGRATION_BLOCKED"
