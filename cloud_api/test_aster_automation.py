from aster_automation import *
from aster_strategy import *

def s(**v): return AsterStrategySettings.from_mapping({"enabled":True,**v})
def a(r=.1): return Account(120,100,r,120,1)

def test_half_open_pair_is_closed_before_any_new_risk():
    p=Pair("BTCUSDT",Leg("LONG",10,100),None)
    x=decide_tick(s(),a(),[p],TickMarket({"BTCUSDT":100}))
    assert (x.kind,x.side,x.safety)==("CLOSE_LEG","LONG",True)

def test_profitable_leg_is_harvested_and_reset():
    p=Pair("BTCUSDT",Leg("LONG",10,100,unrealized_pnl=.07),Leg("SHORT",10,100,unrealized_pnl=-.07))
    x=decide_tick(s(),a(),[p],TickMarket({"BTCUSDT":100}))
    assert (x.kind,x.side)==("HARVEST_RESET","LONG")

def test_dca_uses_distinct_long_short_spacing():
    p=Pair("BTCUSDT",Leg("LONG",10,100),Leg("SHORT",10,100))
    assert decide_tick(s(),a(),[p],TickMarket({"BTCUSDT":98})).side=="LONG"
    assert decide_tick(s(),a(),[p],TickMarket({"BTCUSDT":105})).side=="SHORT"

def test_block_level_disables_dca_but_keeps_harvest():
    p=Pair("BTCUSDT",Leg("LONG",10,100),Leg("SHORT",10,100))
    assert decide_tick(s(),a(.5),[p],TickMarket({"BTCUSDT":98})).kind=="HOLD"

def test_emergency_may_close_losing_leg():
    p=Pair("BTCUSDT",Leg("LONG",10,100,unrealized_pnl=-2),Leg("SHORT",10,100,unrealized_pnl=1))
    x=decide_tick(s(),a(.8),[p],TickMarket({"BTCUSDT":80}))
    assert (x.kind,x.side)==("CLOSE_LEG","LONG")
