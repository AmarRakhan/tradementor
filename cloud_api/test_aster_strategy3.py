from dataclasses import replace
from aster_strategy3 import *
from aster_strategy3_simulation import standard_suite, failure_suite

def cfg(**kw): return Strategy3Config(**kw).validated()
def leg(side="LONG",**kw):
    values={"side":side,"size":100,"weighted_entry":100,"current_price":100};values.update(kw);return LegState(**values)
def port(**kw):
    values={"equity":1000,"high_water_mark":1000,"margin_ratio":.1,"long_exposure":100,"short_exposure":100};values.update(kw);return PortfolioState(**values)

def test_strategy_identity_and_live_kill_switch():
    c=Strategy3Config.from_mapping({"mode":"live"});assert c.strategy_id=="aster-strategy-3" and c.mode=="paper"
def test_normal_both_sides_are_profit_harvesters():
    assert decide(cfg(),leg(unrealized_pnl=2),port()).kind=="FULL_TP"
    assert decide(cfg(),leg("SHORT",unrealized_pnl=2),port()).kind=="FULL_TP"
def test_protection_outranks_profit_and_is_dynamic():
    result=decide(cfg(),leg(unrealized_pnl=3),port(margin_ratio=.6,short_exposure=500))
    assert result.kind in {"PARTIAL_TP","ASSIGN_PROTECTION"} and result.retain_notional>0
def test_already_assigned_protection_does_not_repeat_forever():
    result=decide(cfg(),leg(unrealized_pnl=3,role="PROTECTION"),port(margin_ratio=.6,short_exposure=500))
    assert result.kind=="HOLD"
def test_trailing_defaults_off_and_can_be_armed():
    assert not cfg().trailing_enabled
    result=decide(cfg(trailing_enabled=True),leg(unrealized_pnl=2),port())
    assert result.kind=="ARM_TRAILING"
def test_trailing_close_obeys_minimum_net_profit():
    value=leg(unrealized_pnl=1,trailing_peak_return=.02)
    assert decide(cfg(trailing_enabled=True),value,port()).kind=="TRAILING_TP"
def test_protection_blocks_trailing_close():
    value=leg(unrealized_pnl=2,trailing_peak_return=.03)
    assert decide(cfg(trailing_enabled=True),value,port(margin_ratio=.6,short_exposure=500)).kind in {"PARTIAL_TP","ASSIGN_PROTECTION"}
def test_dca_has_own_budget_and_limits():
    assert decide(cfg(),leg(current_price=95),port()).kind=="ADD_DCA"
    assert decide(cfg(long_max_dca=1),leg(current_price=90,dca_count=1),port()).kind=="HOLD"
def test_unknown_state_never_adds_risk():
    assert decide(cfg(),leg(current_price=90),port(exchange_reliable=False)).kind=="HOLD"
def test_scenarios_and_failure_guards_pass():
    c=cfg(trailing_enabled=True);assert all(x.passed for x in standard_suite(c));assert all(failure_suite(c).values())
