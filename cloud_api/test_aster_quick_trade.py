from unittest.mock import patch
import pytest
from aster_multi_bb import MultiBbConfig, quick_trade_once

class Ref:
    def __init__(self): self.writes=[]
    def set(self, value, merge=False): self.writes.append(value)
    def collection(self, name): return self
    def add(self, value): self.writes.append(value)

class Client:
    def public_exchange_info(self): return {"symbols":[{"symbol":"BTCUSDT","quoteAsset":"USDT","status":"TRADING"}]}
    def ticker_prices(self): return [{"symbol":"BTCUSDT","price":"100"}]
    def leverage_brackets(self, symbol): return [{"symbol":symbol,"brackets":[{"initialLeverage":100,"notionalCap":100000}]}]

def cfg():
    return MultiBbConfig.from_mapping({"engine":"multi_bb_v1","maximumPositions":2,"longSlots":1,"shortSlots":1,
        "universeTopN":10,"entryMarginUsd":5,"entryNotionalUsd":500,"entrySizingMode":"margin","minimumLeverage":50,
        "dcaMarginUsd":2,"dcaDistance":.003,"maxDca":3,"takeProfit":.015,
        "standardLong":{"entryMarginUsd":7,"minimumLeverage":80,"maxDca":4}})

def test_quick_trade_rejects_existing_pair_before_order():
    with pytest.raises(ValueError, match="actieve LONG"):
        quick_trade_once(client=Client(), ref=Ref(), raw_state={}, settings=cfg(), uid="u", account={"availableBalance":100},
            positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"1"}], open_orders=[], symbol="BTCUSDT", side="LONG", idempotency_key="abcdefghijkl", timestamp_ms=1)

def test_quick_trade_dry_run_uses_standard_long_profile():
    plan=type("P",(),{"notional_per_leg":700.0,"leverage":100,"quantity":7})()
    with patch("aster_multi_bb._plan_new", return_value=(plan,{"exchangeMaxLeverage":100})):
        out=quick_trade_once(client=Client(), ref=Ref(), raw_state={}, settings=cfg(), uid="u", account={"availableBalance":100},
            positions=[], open_orders=[], symbol="BTCUSDT", side="LONG", idempotency_key="abcdefghijkl", timestamp_ms=1, dry_run=True)
    assert out["effectiveSettings"]["entryMarginUsd"] == 7
    assert out["effectiveSettings"]["minimumLeverage"] == 80
    assert out["effectiveSettings"]["maxDca"] == 4
    assert out["status"] == "PLANNED"
