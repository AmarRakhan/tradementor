from aster_strategy2 import *

def cfg(**kw): return Strategy2Config(**kw).validated()
def leg(side="LONG", **kw):
    values={"side":side,"cycle_id":"c1","size":100,"weighted_entry":100,"current_price":100}
    values.update(kw)
    return LegState(**values)
def portfolio(**kw): return PortfolioState(1000,1000,.10,100,100,200,**kw)

def test_weighted_fill_uses_actual_fill():
    value=apply_fill(leg(),fill_notional=50,fill_price=80,fee=.2)
    assert round(value.weighted_entry,6)==round(93.333333,6) and value.size==150 and value.dca_count==1

def test_long_and_short_fixed_dca_are_mirrored():
    assert dca_due(cfg(),leg(current_price=98))
    assert dca_due(cfg(),leg("SHORT",current_price=102))

def test_progressive_and_custom_ladders():
    assert dca_level(cfg(dca_mode="progressive"),"LONG",3)==.12
    assert dca_level(cfg(dca_mode="custom",long_custom_levels=(.02,.05,.09),short_custom_levels=(.03,.07,.12)),"SHORT",2)==.07

def test_max_dca_blocks_more_buys():
    assert not dca_due(cfg(long_max_dca=3),leg(current_price=50,dca_count=3))

def test_tp_is_net_of_fee_funding_and_recorded_fees():
    value=leg(unrealized_pnl=2,fees=.2,funding=-.1)
    assert tp_due(cfg(take_profit=.015),value,.1)
    assert not tp_due(cfg(take_profit=.02),value,.1)

def test_normal_tp_closes_full_leg():
    result=decide_leg(cfg(take_profit=.01),leg(unrealized_pnl=2),portfolio())
    assert result.kind=="FULL_TP" and result.notional==100

def test_extreme_opposite_exposure_never_blocks_proven_tp():
    p=PortfolioState(1000,1100,.60,100,500,600)
    result=decide_leg(cfg(take_profit=.01),leg(unrealized_pnl=2),p)
    assert result.kind=="FULL_TP" and result.notional==100 and result.retain_notional==0

def test_defensive_mode_keeps_normal_dca_running():
    p=PortfolioState(920,1000,.55,100,100,200)
    assert decide_leg(cfg(),leg(current_price=95),p).kind=="ADD_DCA"

def test_budget_blocks_dca():
    p=PortfolioState(1000,1000,.1,250,250,500,strategy_margin=500)
    assert "Budget" in decide_leg(cfg(strategy_budget=.5),leg(current_price=95),p).reason

def test_unknown_state_never_adds_risk():
    assert decide_leg(cfg(),leg(current_price=90),portfolio(exchange_reliable=False)).kind=="HOLD"
    assert decide_leg(cfg(),leg(current_price=90),portfolio(open_orders_unknown=True)).kind=="HOLD"

def test_cashflows_do_not_fake_performance():
    assert cashflow_adjusted_return(1000,1200,deposits=200)==0
    assert cashflow_adjusted_return(1000,800,withdrawals=200)==0
    assert adjusted_high_water_mark(1500,1200,withdrawals=300)==1200

def test_compound_is_not_simple_sum():
    assert round(compounded_return([.10,-.10]),4)==-.01

def test_risk_modes_are_ordered():
    c=cfg()
    assert risk_mode(c,portfolio())=="NORMAL"
    assert risk_mode(c,PortfolioState(960,1000,.4,0,0,0))=="CAUTION"
    assert risk_mode(c,PortfolioState(930,1000,.55,0,0,0))=="DEFENSIVE"
    assert risk_mode(c,PortfolioState(850,1000,.75,0,0,0))=="EMERGENCY"

def test_defensive_mode_does_not_freeze_dca_but_emergency_does():
    config=cfg(long_dca_distance=.02)
    losing=leg(current_price=97,unrealized_pnl=-3)
    defensive=PortfolioState(930,1000,.55,0,0,0,strategy_margin=0)
    emergency=PortfolioState(850,1000,.75,0,0,0,strategy_margin=0)
    assert decide_leg(config,losing,defensive).kind=="ADD_DCA"
    assert decide_leg(config,losing,emergency).kind=="HOLD"

def test_worst_case_validation_is_concrete():
    errors=validate_worst_case(cfg(base_notional=200,maximum_pairs=50,long_max_dca=8,short_max_dca=8,leverage=10,strategy_budget=.01),1000,10,50)
    assert errors and "eerstvolgende zelfstandige positie" in errors[-1] and "geschatte margin" in errors[-1]

def test_worst_case_budget_uses_margin_not_leveraged_notional():
    config=cfg(base_notional=10,maximum_pairs=5,long_max_dca=9,short_max_dca=9,leverage=20,strategy_budget=.10)
    assert validate_worst_case(config,1000,5,50)==[]

def test_future_dca_capacity_is_not_reserved_during_configuration_validation():
    config=cfg(base_notional=25,maximum_pairs=50,long_max_dca=10,short_max_dca=10,leverage=20,strategy_budget=.20)
    assert validate_worst_case(config,295.70,5,200)==[]

def test_side_state_machine_and_recovery_are_explicit():
    value=transition(leg(),"PROTECT");assert value.lifecycle=="HARVEST_PROTECTION"
    value=transition(value,"ESCALATE");assert value.lifecycle=="PROTECTION"
    value=transition(value,"RELEASE");assert value.lifecycle=="HARVEST_PROTECTION"
    recovery=transition(LegState("LONG","c",10,100,100,lifecycle="OPENING"),"UNKNOWN")
    assert recovery.lifecycle=="RECOVERY" and transition(recovery,"RECONCILED").lifecycle=="HARVEST"


def test_new_entry_planning_uses_each_accounts_configured_leverage():
    from aster_execution import plan_pair
    row={"symbol":"TESTUSDT","status":"TRADING","filters":[
        {"filterType":"MARKET_LOT_SIZE","minQty":"0.001","maxQty":"100000","stepSize":"0.001"},
        {"filterType":"LOT_SIZE","minQty":"0.001","maxQty":"100000","stepSize":"0.001"},
        {"filterType":"MIN_NOTIONAL","notional":"1"},
        {"filterType":"PRICE_FILTER","tickSize":"0.001"},
    ]}
    brackets=[{"notionalFloor":"0","notionalCap":"100000","initialLeverage":70,"maintMarginRatio":"0.01"}]
    for leverage in (20,50,70):
        plan=plan_pair(row,brackets,1.0,20.0,accepted_leverage=leverage)
        assert plan.leverage==leverage


def test_new_entries_use_account_specific_aster_openable_capacity_before_submission():
    from pathlib import Path
    source=(Path(__file__).resolve().parent/"main.py").read_text(encoding="utf-8")
    tick=source[source.index("def _run_aster_strategy2_tick"):source.index("def _aster_brackets")]
    assert "remaining_openable_notional_value(candidate,settings.leverage)" in tick
    assert "compatible_codes=[symbol for symbol in codes" in tick
    assert "capacity_cache:dict[str,float]={}" in tick
    assert "if candidate not in capacity_cache" in tick
    assert "capacity_cache[symbol]=max(0.0,capacity_cache[symbol]-(q*p))" in tick
    assert "side_entry_candidates(compatible_codes" in tick
    assert "ASTER_OPENABLE_NOTIONAL_ZERO" in tick
    assert "ENTRY_CANDIDATE_CAPACITY_WAIT" in tick
    assert '"openableCapacityBlocked":capacity_waiting' in tick
    assert "cooldown_version=3" in tick

def test_trend_bollinger_setting_defaults_off_and_missing_is_off():
    assert Strategy2Config().trend_bollinger_entry_enabled is False
    assert Strategy2Config.from_mapping({}).trend_bollinger_entry_enabled is False
    assert Strategy2Config.from_mapping({"trendBollingerEntryEnabled":False}).public_dict()["trendBollingerEntryEnabled"] is False


def test_trend_bollinger_entry_allowed_matrix():
    up=[float(x) for x in range(1,61)]
    down=[float(x) for x in range(200,140,-1)]
    neutral=[100.0]*60
    up_probe=trend_bollinger_entry_check(up,1.0,"LONG"); assert up_probe and up_probe["trend"]=="UP"
    assert trend_bollinger_entry_check(up,up_probe["middle"],"LONG")["eligible"] is True
    assert trend_bollinger_entry_check(up,up_probe["upper"]+1,"SHORT")["eligible"] is True
    down_probe=trend_bollinger_entry_check(down,1.0,"LONG"); assert down_probe and down_probe["trend"]=="DOWN"
    assert trend_bollinger_entry_check(down,down_probe["lower"]-1,"LONG")["eligible"] is True
    assert trend_bollinger_entry_check(down,down_probe["middle"],"SHORT")["eligible"] is True
    neutral_probe=trend_bollinger_entry_check(neutral,99,"LONG"); assert neutral_probe and neutral_probe["trend"]=="NEUTRAL"
    assert neutral_probe["eligible"] is True
    assert trend_bollinger_entry_check(neutral,101,"SHORT")["eligible"] is True


def test_trend_bollinger_insufficient_data_skips_candidate():
    assert trend_bollinger_entry_check([100.0]*49,100.0,"LONG") is None


def test_trend_bollinger_filter_is_only_on_new_seat_entry_path():
    from pathlib import Path
    source=(Path(__file__).resolve().parent/"main.py").read_text(encoding="utf-8")
    tick=source[source.index("def _run_aster_strategy2_tick"):source.index("def _aster_brackets")]
    gate=tick.index("if settings.trend_bollinger_entry_enabled:")
    candle=tick.index('client.klines(candidate,"15m",60)')
    open_plan=tick.index("value=plan_aster_pair",gate)
    assert gate < candle < open_plan
    assert 'if not bool(entry_check["eligible"]):' in tick[gate:open_plan]
    assert "continue" in tick[tick.index('if not bool(entry_check["eligible"]):',gate):open_plan]
    assert tick.index("REOPEN",0,gate) < gate
