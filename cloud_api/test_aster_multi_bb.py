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




def test_definite_max_notional_rejection_skips_symbol_and_continues(monkeypatch):
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"3000"},{"symbol":"BBBUSDT","quoteVolume":"2000"}],
             prices={"AAAUSDT":100,"BBBUSDT":100},leverage=100)
    def fake_execute(client, plan, **kwargs):
        if plan.symbol=="AAAUSDT":
            raise RuntimeError("Aster -5018: maximum notional value limit")
        return {"result":{"avgPrice":"100","executedQty":str(plan.quantity)},"leverage":plan.leverage}
    monkeypatch.setattr(aster_multi_bb,"execute_leg_once",fake_execute)
    ref=Ref()
    r=run_multi_bb_step(client=c,ref=ref,raw_state={},settings=cfg(universeTopN=2),uid="u",
        account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=False,order_budget=5)
    assert any(x["kind"]=="ENTRY_SKIP" and x["symbol"]=="AAAUSDT" and "5018" in x["reason"] for x in r["actions"])
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

def test_existing_long_short_same_symbol_is_isolated_without_stopping_bot():
    positions=[
        {"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"5","entryPrice":"100","markPrice":"100","leverage":"75"},
        {"symbol":"AAAUSDT","positionSide":"SHORT","positionAmt":"4","entryPrice":"101","markPrice":"100","leverage":"75"},
    ]
    ref=Ref(); raw={"multiBbAdoptionPending":True,"multiBbPositions":{}}
    r=run_multi_bb_step(client=Client(positions=positions,prices={"AAAUSDT":100},leverage=75),ref=ref,raw_state=raw,
        settings=cfg(),uid="u",account={"availableBalance":"100"},positions=positions,open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=False)
    assert r["status"]=="running"
    assert any(u.get("multiBbIsolatedSymbols")==["AAAUSDT"] for u in ref.updates)
    persisted=ref.updates[-1]
    assert persisted["multiBbAdoptionPending"] is False
    assert "AAAUSDT|LONG" not in persisted["multiBbPositions"]
    assert "AAAUSDT|SHORT" not in persisted["multiBbPositions"]
    assert all(u.get("enabled") is not False for u in ref.updates)

@pytest.mark.parametrize("leverage,expected_margin",[(20,1.5),(50,.6),(100,.3)])
def test_fixed_entry_notional_uses_dynamic_margin_across_leverage(leverage,expected_margin):
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"1000"}],prices={"AAAUSDT":100},leverage=leverage)
    settings=cfg(minimumLeverage=20,entryNotionalUsd=30,entryMarginUsd=.2)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=settings,uid="u",
        account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    entry=next(x for x in r["actions"] if x["kind"]=="ENTRY")
    assert entry["leverage"]==leverage
    assert entry["notionalUsd"]==pytest.approx(30)
    assert entry["marginUsd"]==pytest.approx(expected_margin)


def test_legacy_base_notional_migrates_to_fixed_entry_notional():
    settings=MultiBbConfig.from_mapping({"engine":ENGINE,"universeTopN":60,"maximumPositions":60,
        "longSlots":60,"shortSlots":0,"minimumLeverage":20,"entryMarginUsd":.2,"baseNotional":30,
        "dcaDistance":.003,"dcaMarginUsd":.2,"maxDca":10,"takeProfit":.015})
    assert settings.entry_notional_usd==pytest.approx(30)
    assert settings.public_dict()["entryNotionalUsd"]==pytest.approx(30)


def test_new_entries_share_ranked_candidates_between_long_and_short():
    tickers=[{"symbol":f"C{i}USDT","quoteVolume":str(1000-i)} for i in range(4)]
    prices={f"C{i}USDT":100 for i in range(4)}
    c=Client(tickers=tickers,prices=prices,leverage=100)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=cfg(universeTopN=4,maximumPositions=4,longSlots=2,shortSlots=2),uid="u",
        account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True,order_budget=4)
    entries=[x for x in r["actions"] if x["kind"]=="ENTRY"]
    assert [x["side"] for x in entries]==["LONG","SHORT","LONG","SHORT"]
    assert r["activeLong"]==2 and r["activeShort"]==2


def test_new_entries_follow_configured_long_short_ratio_not_long_first():
    tickers=[{"symbol":f"R{i}USDT","quoteVolume":str(2000-i)} for i in range(6)]
    prices={f"R{i}USDT":100 for i in range(6)}
    c=Client(tickers=tickers,prices=prices,leverage=100)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=cfg(universeTopN=6,maximumPositions=6,longSlots=4,shortSlots=2),uid="u",
        account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True,order_budget=6)
    entries=[x for x in r["actions"] if x["kind"]=="ENTRY"]
    assert [x["side"] for x in entries]==["LONG","SHORT","LONG","LONG","SHORT","LONG"]
    assert r["activeLong"]==4 and r["activeShort"]==2


def manual_cfg(symbols, **kw):
    return cfg(manualSymbolSelectionEnabled=True, manualSymbols=symbols, **kw)


def test_manual_selection_disabled_keeps_ranked_topn_flow():
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"200"},{"symbol":"BBBUSDT","quoteVolume":"100"}],prices={"AAAUSDT":100,"BBBUSDT":100},leverage=100)
    settings=cfg(manualSymbolSelectionEnabled=False,manualSymbols=[{"symbol":"BBBUSDT","side":"SHORT"}])
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=settings,uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    entry=next(x for x in r["actions"] if x["kind"]=="ENTRY")
    assert entry["symbol"]=="AAAUSDT" and entry["side"]=="LONG"
    assert r["candidateMode"]=="top_n"


def test_manual_selection_one_long_opens_only_selected_symbol():
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"999"},{"symbol":"BBBUSDT","quoteVolume":"1"}],prices={"AAAUSDT":100,"BBBUSDT":100},leverage=100)
    settings=manual_cfg([{"symbol":"BBBUSDT","side":"LONG"}],maximumPositions=2,longSlots=2,shortSlots=0)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=settings,uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True,order_budget=5)
    entries=[x for x in r["actions"] if x["kind"]=="ENTRY"]
    assert [(x["symbol"],x["side"]) for x in entries]==[("BBBUSDT","LONG")]


def test_manual_selection_one_short_opens_short():
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"999"},{"symbol":"BBBUSDT","quoteVolume":"1"}],prices={"AAAUSDT":100,"BBBUSDT":100},leverage=100)
    settings=manual_cfg([{"symbol":"BBBUSDT","side":"SHORT"}],maximumPositions=2,longSlots=1,shortSlots=1)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=settings,uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True,order_budget=5)
    entries=[x for x in r["actions"] if x["kind"]=="ENTRY"]
    assert [(x["symbol"],x["side"]) for x in entries]==[("BBBUSDT","SHORT")]


def test_manual_selection_mixed_sides_respects_explicit_direction_and_slot_caps():
    symbols=[{"symbol":"AAAUSDT","side":"LONG"},{"symbol":"BBBUSDT","side":"SHORT"},{"symbol":"CCCUSDT","side":"LONG"}]
    c=Client(tickers=[{"symbol":x["symbol"],"quoteVolume":str(100-i)} for i,x in enumerate(symbols)],prices={x["symbol"]:100 for x in symbols},leverage=100)
    settings=manual_cfg(symbols,maximumPositions=2,longSlots=1,shortSlots=1)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=settings,uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True,order_budget=5)
    entries=[x for x in r["actions"] if x["kind"]=="ENTRY"]
    assert [(x["symbol"],x["side"]) for x in entries]==[("AAAUSDT","LONG"),("BBBUSDT","SHORT")]
    assert all(x["symbol"]!="CCCUSDT" for x in entries)


def test_manual_selection_never_opens_unselected_ranked_symbol():
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"10000"},{"symbol":"BBBUSDT","quoteVolume":"1"}],prices={"AAAUSDT":100,"BBBUSDT":100},leverage=100)
    settings=manual_cfg([{"symbol":"BBBUSDT","side":"LONG"}])
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=settings,uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert not any(x.get("symbol")=="AAAUSDT" and x["kind"]=="ENTRY" for x in r["actions"])


def test_removed_manual_symbol_existing_position_still_gets_tp_management():
    pos={"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100","markPrice":"102","leverage":"100"}
    state={"multiBbPositions":{"AAAUSDT|LONG":{"dcaCount":0,"lastBotFillPrice":100,"lastKnownQty":1,"lastKnownEntry":100,"cycleStartedAtMs":1,"botManaged":True}}}
    c=Client(positions=[pos],tickers=[{"symbol":"BBBUSDT","quoteVolume":"1"}],prices={"AAAUSDT":102,"BBBUSDT":100},leverage=100)
    settings=manual_cfg([{"symbol":"BBBUSDT","side":"LONG"}],takeProfit=.015)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state=state,settings=settings,uid="u",account={"availableBalance":"100"},positions=[pos],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert any(x["kind"]=="TP" and x["symbol"]=="AAAUSDT" for x in r["actions"])


def test_manual_selection_active_symbol_does_not_duplicate_entry():
    pos={"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100","markPrice":"100","leverage":"100"}
    state={"multiBbPositions":{"AAAUSDT|LONG":{"dcaCount":0,"lastBotFillPrice":100,"lastKnownQty":1,"lastKnownEntry":100,"cycleStartedAtMs":1,"botManaged":True}}}
    c=Client(positions=[pos],tickers=[{"symbol":"AAAUSDT","quoteVolume":"100"}],prices={"AAAUSDT":100},leverage=100)
    settings=manual_cfg([{"symbol":"AAAUSDT","side":"LONG"}])
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state=state,settings=settings,uid="u",account={"availableBalance":"100"},positions=[pos],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert not any(x["kind"]=="ENTRY" for x in r["actions"])


def test_manual_selection_requires_at_least_one_symbol_when_enabled():
    with pytest.raises(ValueError,match="Selecteer minimaal één munt"):
        manual_cfg([])


def test_manual_selection_public_settings_roundtrip():
    settings=manual_cfg([{"symbol":"btcusdt","side":"long"},{"symbol":"ethusdt","side":"short"}],maximumPositions=5,longSlots=3,shortSlots=2)
    public=settings.public_dict()
    assert public["manualSymbolSelectionEnabled"] is True
    assert public["manualSymbols"]==[{"symbol":"BTCUSDT","side":"LONG"},{"symbol":"ETHUSDT","side":"SHORT"}]
    assert public["maximumPositions"]==5


def test_manual_selection_keeps_minimum_leverage_guard():
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"1"}],prices={"AAAUSDT":100},leverage=10)
    settings=manual_cfg([{"symbol":"AAAUSDT","side":"SHORT"}],minimumLeverage=20,maximumPositions=1,longSlots=0,shortSlots=1)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=settings,uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert not any(x["kind"]=="ENTRY" for x in r["actions"])
    assert any(x["kind"]=="ENTRY_SKIP" and "minimum 20x" in x["reason"] for x in r["actions"])


def test_manual_selection_keeps_available_margin_guard():
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"1"}],prices={"AAAUSDT":100},leverage=100)
    settings=manual_cfg([{"symbol":"AAAUSDT","side":"LONG"}],entryNotionalUsd=1000)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=settings,uid="u",account={"availableBalance":"0.01"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert not any(x["kind"]=="ENTRY" for x in r["actions"])
    assert any(x["kind"]=="ENTRY_MARGIN_WAIT" and x["side"]=="LONG" for x in r["actions"])
