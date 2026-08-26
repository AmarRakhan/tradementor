from aster_strategy2 import Strategy2Config
from aster_strategy2_focus_adapter import (
    build_focus_shadow_report, current_focus_markets, focus_state_from_mapping,
    focus_state_to_mapping,
)


class FakeClient:
    def __init__(self):
        self.orders_sent=0
    def public_exchange_info(self):
        return {"symbols":[
            {"symbol":"AAAUSDT","quoteAsset":"USDT","status":"TRADING","contractType":"PERPETUAL"},
            {"symbol":"BBBUSDT","quoteAsset":"USDT","status":"TRADING","contractType":"PERPETUAL"},
            {"symbol":"OLDUSDT","quoteAsset":"USDT","status":"BREAK","contractType":"PERPETUAL"},
        ]}
    def ticker_24h(self):
        return [
            {"symbol":"AAAUSDT","priceChangePercent":"20","quoteVolume":"50000000"},
            {"symbol":"BBBUSDT","priceChangePercent":"10","quoteVolume":"40000000"},
            {"symbol":"OLDUSDT","priceChangePercent":"99","quoteVolume":"999999999"},
        ]
    def ticker_prices(self):
        return [{"symbol":"AAAUSDT","price":"120"},{"symbol":"BBBUSDT","price":"105"}]
    def klines(self,symbol,interval,limit):
        base=100 if symbol=="AAAUSDT" else 90
        return [[i,0,0,0,str(base+i*.1),0] for i in range(60)]
    def account_information(self):
        return {"totalMarginBalance":"1000","availableBalance":"500","totalMaintMargin":"25"}
    def position_risk(self):
        return []
    def remaining_openable_notional_value(self,symbol,leverage):
        return 100000
    def place_order(self,*args,**kwargs):
        self.orders_sent+=1
        raise AssertionError("adapter mag geen orderpad gebruiken")


def focus_raw(**settings):
    base={"tradingMode":"focus","focusShadowEnabled":True,"minimumQuoteVolume24hUsdt":1_000_000,"leverage":20,"strategyBudget":.5,"focusMaxBudgetUsd":5000}
    base.update(settings)
    return {"settings":base,"focusShadowState":{}}


def test_market_adapter_uses_only_trading_usdt_perpetuals():
    rows=current_focus_markets(FakeClient(),Strategy2Config.from_mapping(focus_raw()["settings"]))
    assert [x.symbol for x in rows]==["AAAUSDT","BBBUSDT"]
    assert rows[0].change_24h_pct==.20
    assert len(rows[0].closes)==60


def test_shadow_adapter_is_read_only_and_reports_zero_orders():
    client=FakeClient()
    report=build_focus_shadow_report(client=client,raw_state=focus_raw(),timestamp_ms=123)
    assert report["ordersSent"]==0
    assert report["readOnly"] is True
    assert report["capturedAtMs"]==123
    assert client.orders_sent==0
    assert report["side"]=="LONG"
    assert report["newFocusPairLimit"]==1


def test_shadow_adapter_returns_full_rank_audit():
    report=build_focus_shadow_report(client=FakeClient(),raw_state=focus_raw(),timestamp_ms=123)
    assert len(report["ranking"])==2
    row=report["ranking"][0]
    for key in ("symbol","change_24h_pct","price","momentum_pct","bollinger_middle","bollinger_upper","bollinger_lower","score","reason"):
        assert key in row


def test_focus_state_mapping_roundtrip_uses_ui_camel_case_contract():
    state=focus_state_from_mapping({"activePair":"AAAUSDT","cycleId":"c1","weightedEntry":100,"dcaCount":2,"focusBudgetUsed":300,"partialsTaken":[1]})
    mapped=focus_state_to_mapping(state)
    assert mapped["activePair"]=="AAAUSDT"
    assert mapped["weightedEntry"]==100
    assert mapped["dcaCount"]==2
    assert mapped["focusBudgetUsed"]==300
    assert mapped["partialsTaken"]==[1]


def test_wait_until_flat_uses_current_position_count_without_closing_anything():
    class PositionsClient(FakeClient):
        def position_risk(self):
            return [{"symbol":"LEGACYUSDT","positionAmt":"2","positionSide":"LONG"}]
    report=build_focus_shadow_report(client=PositionsClient(),raw_state=focus_raw(focusWaitUntilFlat=True),timestamp_ms=123)
    assert report["ordersSent"]==0
    assert report["decision"]["kind"]=="HOLD"
    assert "bestaande" in report["decision"]["reason"]
