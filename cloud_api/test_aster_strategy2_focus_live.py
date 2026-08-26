from __future__ import annotations

from aster_strategy2 import Strategy2Config
from aster_strategy2_focus_live import build_focus_live_plan, run_focus_live_step


class FakeClient:
    def public_exchange_info(self):
        return {"symbols":[{"symbol":"BTCUSDT","quoteAsset":"USDT","status":"TRADING","contractType":"PERPETUAL","filters":[
            {"filterType":"PRICE_FILTER","minPrice":"0.1","maxPrice":"1000000","tickSize":"0.1"},
            {"filterType":"LOT_SIZE","minQty":"0.001","maxQty":"1000","stepSize":"0.001"},
            {"filterType":"MARKET_LOT_SIZE","minQty":"0.001","maxQty":"1000","stepSize":"0.001"},
            {"filterType":"MIN_NOTIONAL","notional":"5"}]}]}
    def ticker_24h(self): return [{"symbol":"BTCUSDT","priceChangePercent":"10","quoteVolume":"100000000"}]
    def ticker_prices(self): return [{"symbol":"BTCUSDT","price":"100"}]
    def klines(self,*_args): return [[0,0,0,0,str(80+i*.35)] for i in range(60)]
    def remaining_openable_notional_value(self,*_args): return 1_000_000
    def leverage_brackets(self,*_args): return [{"symbol":"BTCUSDT","brackets":[{"notionalFloor":"0","notionalCap":"1000000","initialLeverage":"20","maintMarginRatio":"0.01"}]}]


class FakeCollection:
    def add(self,_value): pass


class FakeRef:
    def __init__(self): self.values=[]
    def set(self,value,merge=False): self.values.append(value)
    def collection(self,_name): return FakeCollection()


def settings(**extra):
    raw={"tradingMode":"focus","mode":"live","focusShadowEnabled":False,"focusStartOrderNotional":100,
         "focusMaxBudgetUsd":1000,"minimumQuoteVolume24hUsdt":0,"leverage":20,"strategyBudget":.9,
         "focusTrailingActivationPct":.02,"focusMinimumProfitPct":.015}
    raw.update(extra);return Strategy2Config.from_mapping(raw)


def test_live_plan_uses_same_focus_planner_even_when_shadow_is_off():
    report,state,owned=build_focus_live_plan(client=FakeClient(),raw_state={},settings=settings(),
        account={"totalMarginBalance":"1000","availableBalance":"900","totalMaintMargin":"10"},positions=[],timestamp_ms=1)
    assert report["mode"]=="focus-live"
    assert report["decision"]["kind"]=="OPEN"
    assert report["decision"]["symbol"]=="BTCUSDT"
    assert report["ordersSent"]==0
    assert state.total_quantity==0
    assert owned==[]


def test_confirmed_live_open_persists_focus_ownership_and_one_order(monkeypatch):
    calls=[]
    def fake_execute(_client,_plan,**kwargs):
        if kwargs.get("before_submit"): kwargs["before_submit"](object())
        return {"result":{"executedQty":"1","avgPrice":"100","clientOrderId":"focus-open","orderId":"42"}}
    monkeypatch.setattr("aster_strategy2_focus_live.execute_leg_once",fake_execute)
    ref=FakeRef()
    result=run_focus_live_step(client=FakeClient(),ref=ref,raw_state={},settings=settings(),uid="u1",
        account={"totalMarginBalance":"1000","availableBalance":"900","totalMaintMargin":"10"},positions=[],timestamp_ms=1000,
        before_order=lambda _intent,details:calls.append(details))
    assert result["action"]=="FOCUS_OPEN"
    assert result["ordersSent"]==1
    assert calls[0]["kind"]=="FOCUS_OPEN"
    final=next(value for value in reversed(ref.values) if "ownedLegs" in value)
    assert final["ownedLegs"][0]["role"]=="FOCUS"
    assert final["ownedLegs"][0]["side"]=="LONG"
    assert final["focusLiveState"]["activePair"]=="BTCUSDT"
    assert final["focusLiveState"]["totalQuantity"]==1


def test_wait_until_flat_blocks_new_focus_cycle_without_touching_legacy_position():
    report,_,_=build_focus_live_plan(client=FakeClient(),raw_state={},settings=settings(focusWaitUntilFlat=True),
        account={"totalMarginBalance":"1000","availableBalance":"900","totalMaintMargin":"10"},
        positions=[{"symbol":"ETHUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"50","markPrice":"51","leverage":"10"}],timestamp_ms=1)
    assert report["decision"]["kind"]=="HOLD"
    assert "wacht" in report["decision"]["reason"].lower()


def test_zero_order_budget_never_calls_executor(monkeypatch):
    monkeypatch.setattr("aster_strategy2_focus_live.execute_leg_once",lambda *_a,**_k: (_ for _ in ()).throw(AssertionError("order called")))
    result=run_focus_live_step(client=FakeClient(),ref=FakeRef(),raw_state={},settings=settings(),uid="u1",
        account={"totalMarginBalance":"1000","availableBalance":"900","totalMaintMargin":"10"},positions=[],timestamp_ms=1,order_budget=0)
    assert result["status"]=="budget-exhausted"
    assert result["ordersSent"]==0
