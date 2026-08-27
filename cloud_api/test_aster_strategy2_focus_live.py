from __future__ import annotations

from aster_strategy2 import Strategy2Config
from aster_strategy2_focus import FocusState, reset_after_full_exit
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
    raw={"tradingMode":"focus","mode":"live","focusShadowEnabled":False,"focusLiveEnabled":True,"focusStartOrderNotional":100,
         "focusMaxBudgetUsd":1000,"minimumQuoteVolume24hUsdt":0,"leverage":20,"strategyBudget":.9,
         "focusTrailingActivationPct":.02,"focusMinimumProfitPct":.015}
    raw.update(extra);return Strategy2Config.from_mapping(raw)


def account():
    return {"totalMarginBalance":"1000","availableBalance":"900","totalMaintMargin":"10"}


def test_live_plan_uses_same_focus_planner_even_when_shadow_is_off():
    report,state,owned=build_focus_live_plan(client=FakeClient(),raw_state={},settings=settings(),
        account=account(),positions=[],timestamp_ms=1)
    assert report["mode"]=="focus-live"
    assert report["decision"]["kind"]=="OPEN"
    assert report["decision"]["symbol"]=="BTCUSDT"
    assert report["ordersSent"]==0
    assert state.total_quantity==0
    assert owned==[]


def test_confirmed_live_open_persists_focus_ownership_and_one_queue_reservation(monkeypatch):
    calls=[]
    def fake_execute(_client,_plan,**kwargs):
        if kwargs.get("before_submit"): kwargs["before_submit"](object())
        return {"result":{"executedQty":"1","avgPrice":"100","clientOrderId":"focus-open","orderId":"42"}}
    monkeypatch.setattr("aster_strategy2_focus_live.execute_leg_once",fake_execute)
    ref=FakeRef()
    result=run_focus_live_step(client=FakeClient(),ref=ref,raw_state={},settings=settings(),uid="u1",
        account=account(),positions=[],timestamp_ms=1000,
        reserve_order=lambda _intent,details:calls.append(details))
    assert result["action"]=="FOCUS_OPEN"
    assert result["ordersSent"]==1
    assert calls==[{"kind":"FOCUS_OPEN","cycleId":calls[0]["cycleId"],"leverage":20,"marginUsd":5.0,"dcaNumber":None}]
    final=next(value for value in reversed(ref.values) if "ownedLegs" in value)
    assert final["ownedLegs"][0]["role"]=="FOCUS"
    assert final["ownedLegs"][0]["side"]=="LONG"
    assert final["focusLiveState"]["activePair"]=="BTCUSDT"
    assert final["focusLiveState"]["totalQuantity"]==1


def test_wait_until_flat_blocks_new_focus_cycle_without_touching_legacy_position():
    report,_,_=build_focus_live_plan(client=FakeClient(),raw_state={},settings=settings(focusWaitUntilFlat=True),
        account=account(),positions=[{"symbol":"ETHUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"50","markPrice":"51","leverage":"10"}],timestamp_ms=1)
    assert report["decision"]["kind"]=="HOLD"
    assert "wacht" in report["decision"]["reason"].lower()


def test_zero_order_budget_never_calls_executor(monkeypatch):
    monkeypatch.setattr("aster_strategy2_focus_live.execute_leg_once",lambda *_a,**_k: (_ for _ in ()).throw(AssertionError("order called")))
    result=run_focus_live_step(client=FakeClient(),ref=FakeRef(),raw_state={},settings=settings(),uid="u1",
        account=account(),positions=[],timestamp_ms=1,order_budget=0)
    assert result["status"]=="budget-exhausted"
    assert result["ordersSent"]==0


def test_existing_open_order_on_focus_pair_blocks_duplicate_submission(monkeypatch):
    monkeypatch.setattr("aster_strategy2_focus_live.execute_leg_once",lambda *_a,**_k: (_ for _ in ()).throw(AssertionError("duplicate order called")))
    result=run_focus_live_step(client=FakeClient(),ref=FakeRef(),raw_state={},settings=settings(),uid="u1",
        account=account(),positions=[],timestamp_ms=1,open_orders=[{"symbol":"BTCUSDT","status":"NEW"}])
    assert result["action"]=="FOCUS_OPEN_ORDER_PENDING"
    assert result["ordersSent"]==0


def test_full_exit_state_is_immediately_eligible_for_next_focus_open():
    closed=reset_after_full_exit(FocusState(active_pair="BTCUSDT",cycle_id="old",original_entry=90,weighted_entry=90,total_quantity=1,total_notional=90),realized_pnl=10,theoretical_portfolio_value=1010)
    report,_,_=build_focus_live_plan(client=FakeClient(),raw_state={"focusLiveState":{
        "activePair":closed.active_pair,"cycleId":closed.cycle_id,"cycleStatus":closed.cycle_status,"openedAt":closed.opened_at_ms,
        "originalEntry":closed.original_entry,"weightedEntry":closed.weighted_entry,"totalQuantity":closed.total_quantity,"totalNotional":closed.total_notional,
        "usedMargin":closed.used_margin,"dcaCount":closed.dca_count,"nextDcaTrigger":closed.next_dca_trigger,"highestPrice":closed.highest_price,
        "highestProfitPct":closed.highest_profit_pct,"trailingActive":closed.trailing_active,"trailingFloor":closed.trailing_floor,
        "partialsTaken":[],"realizedPnl":closed.realized_pnl,"theoreticalPortfolioValue":closed.theoretical_portfolio_value,
        "focusBudgetUsed":closed.focus_budget_used,"lastSelectionReason":closed.last_selection_reason,"lastAction":closed.last_action,"lastReason":closed.last_reason}},
        settings=settings(),account=account(),positions=[],timestamp_ms=2)
    assert report["decision"]["kind"]=="OPEN"
    assert report["decision"]["symbol"]=="BTCUSDT"


def test_automatic_focus_skips_pair_that_rejects_configured_leverage():
    class LeverageAwareClient(FakeClient):
        def public_exchange_info(self):
            base=super().public_exchange_info()["symbols"][0]
            second={**base,"symbol":"ETHUSDT"}
            return {"symbols":[base,second]}
        def ticker_24h(self):
            return [
                {"symbol":"BTCUSDT","priceChangePercent":"10","quoteVolume":"100000000"},
                {"symbol":"ETHUSDT","priceChangePercent":"8","quoteVolume":"90000000"},
            ]
        def ticker_prices(self):
            return [{"symbol":"BTCUSDT","price":"100"},{"symbol":"ETHUSDT","price":"100"}]
        def remaining_openable_notional_value(self,symbol,*_args):
            if symbol=="BTCUSDT": raise RuntimeError("Invalid leverage")
            return 1_000_000
    report,_,_=build_focus_live_plan(client=LeverageAwareClient(),raw_state={},settings=settings(),
        account=account(),positions=[],timestamp_ms=1)
    assert report["decision"]["kind"]=="OPEN"
    assert report["decision"]["symbol"]=="ETHUSDT"


def test_missing_focus_ownership_is_recovered_from_confirmed_fill_and_exchange_position():
    raw={
        "settings":{"version":7},
        "focusLiveState":{
            "activePair":"BTCUSDT","cycleId":"focus-recover-1","openedAt":1000,
            "originalEntry":100,"weightedEntry":100,"totalQuantity":1,"totalNotional":100,
            "usedMargin":5,"focusBudgetUsed":100,"lastAction":"OPEN"
        },
        "focusLiveReport":{"executedFill":{"quantity":1,"price":100}},
        "focusLiveAt":2.0,
    }
    positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100","markPrice":"101","leverage":"20"}]
    report,_,owned=build_focus_live_plan(client=FakeClient(),raw_state=raw,settings=settings(),
        account=account(),positions=positions,timestamp_ms=3000)
    assert len(owned)==1
    assert owned[0].role=="FOCUS"
    assert owned[0].symbol=="BTCUSDT"
    assert owned[0].cycle_id=="focus-recover-1"
    assert report["preflightReason"]=="Focus-ownership hersteld uit bevestigde fill en exchange-positie"
