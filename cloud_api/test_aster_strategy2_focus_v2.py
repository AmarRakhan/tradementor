import pytest
from aster_strategy2_state import OwnedLeg
from pathlib import Path
from aster_strategy2_focus_v2 import target_hedge_notional,release_quantity,recovery_confirmed,full_recovery,rehedge_stop,state_from,state_map,FocusV2State,continuous_dca_trigger,harvest_fraction,combined_close_evidence
from aster_strategy2 import Strategy2Config

HERE=Path(__file__).resolve().parent

def test_focus_v2_defaults_off_and_legacy_focus_guard_remains():
    cfg=Strategy2Config.from_mapping({"tradingMode":"focus"})
    assert cfg.focus_v2_enabled is False
    legacy=(HERE/"aster_strategy2_focus_multi.py").read_text()
    assert "FOCUS_HEDGE_CLOSE_BLOCKED" in legacy and "hedge_evidence.expected_net<=0" in legacy

def test_initial_long_always_keeps_net_long_bias():
    assert target_hedge_notional(100,min_bias_usdt=5,min_bias_ratio=.02,max_hedge_ratio=.95)==95
    assert target_hedge_notional(3000,min_bias_usdt=5,min_bias_ratio=.02,max_hedge_ratio=.95)==2850

def test_hedge_follows_current_long_not_start_size():
    a=target_hedge_notional(100,min_bias_usdt=5,min_bias_ratio=.02,max_hedge_ratio=.95)
    b=target_hedge_notional(500,min_bias_usdt=5,min_bias_ratio=.02,max_hedge_ratio=.95)
    assert a==95 and b==475 and b>a

def test_release_is_tranched_until_full_portfolio_recovery():
    assert release_quantity(900,.33,False)==297
    assert release_quantity(900,.33,True)==900
    assert not full_recovery(equity=296,cycle_start_equity=300,ratio=.99)
    assert full_recovery(equity=297,cycle_start_equity=300,ratio=.99)

def test_recovery_needs_price_structure_and_portfolio_progress():
    assert recovery_confirmed(mark=101,recent_low=100,bollinger_middle=100.5,equity=297,cycle_start_equity=300,rebound_pct=.003,portfolio_ratio=.99,require_middle=True)
    assert not recovery_confirmed(mark=100.1,recent_low=100,bollinger_middle=100.05,equity=300,cycle_start_equity=300,rebound_pct=.003,portfolio_ratio=.99,require_middle=True)
    assert not recovery_confirmed(mark=101,recent_low=100,bollinger_middle=102,equity=300,cycle_start_equity=300,rebound_pct=.003,portfolio_ratio=.99,require_middle=True)

def test_rehedge_trigger_sits_below_release_price():
    assert 99.69<rehedge_stop(100,.003)<99.71

def test_state_roundtrip_freezes_cycle_equity():
    s=FocusV2State(cycle_id="c",symbol="SOLUSDT",cycle_start_equity=300,original_entry=100,dca_count=4)
    r=state_from(state_map(s));assert r.cycle_start_equity==300 and r.cycle_id=="c" and r.dca_count==4

def test_red_hedge_release_is_isolated_from_legacy_close_guard():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "FOCUS_V2_HEDGE_RELEASE" in src
    assert "AsterCloseBlocked" not in src
    assert "hedge_evidence.expected_net" not in src

def test_exchange_side_rehedge_is_stop_market_and_current_long_based():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert '"type":"STOP_MARKET"' in src
    assert "hedge_target=target_hedge_notional(long_notional" in src
    assert "REHEDGE_PREFIX" in src

def test_duplicate_rehedge_is_counted_as_armed_not_reopened():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "armed_qty" in src and "hedge_target-short_notional-armed_qty" in src

def test_existing_focus_is_never_adopted():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "Bestaande Focus ownership wordt nooit gemigreerd" in src
    assert "Bestaande exchange-positie wordt niet geadopteerd" in src

def test_margin_liquidation_guard_precedes_dca():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "maint<settings.emergency_margin_ratio" in src
    assert "liqdist>=.05" in src

def test_focus_v2_replaces_full_tp_with_continuous_profit_harvest():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "FOCUS_V2_PROFIT_HARVEST" in src
    assert "FOCUS_V2_TP_CLOSE" not in src
    assert "harvest_baseline_equity" in src

def test_wizard_has_separate_focus_v2_opt_in():
    ui=(HERE.parent/"web/components/aster-strategy2-maker.tsx").read_text()
    assert 'title:"Focus | Focus 2.0"' in ui
    assert 'label="Focus 2.0 gebruiken"' in ui
    assert "Focus 2.0 · Beschermd LONG opbouwen" in ui


def test_new_cycle_requires_protected_two_leg_open_and_slot_leverage():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "FOCUS_V2_WAIT_PROTECTED_OPEN" in src
    assert 'action":"FOCUS_V2_OPEN_PROTECTED"' in src
    assert 'ordersSent":2' in src
    assert "resolve_slot_leverage" in src
    assert "FOCUS_V2_PROTECTED_OPEN_ROLLBACK" in src
    assert "new_position_leverage=leverage" in src

def test_focus_v2_never_deliberately_returns_after_long_only_open():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert 'action":"FOCUS_V2_OPEN_LONG"' not in src
    assert "next tick reconciles and opens it" not in src


def test_focus_v2_dca_is_protected_pair_and_dashboard_exposes_ladder():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    main=(HERE/"main.py").read_text()
    assert "FOCUS_V2_WAIT_PROTECTED_DCA" in src
    assert "FOCUS_V2_DCA_PROTECTED" in src
    assert "FOCUS_V2_PROTECTED_DCA_ROLLBACK" in src
    assert 'str(row.get("strategy2Role","")).upper()=="FOCUS_V2_LONG"' in main
    assert '"source":"focus-v2-runtime-state"' in main


def test_continuous_dca_trigger_uses_latest_anchor_not_original_low():
    assert continuous_dca_trigger(104,.003)==pytest.approx(103.688)
    assert continuous_dca_trigger(110,.01)==pytest.approx(108.9)

def test_harvest_fraction_realizes_requested_slice_but_keeps_remainder():
    assert harvest_fraction(15,10)==pytest.approx(2/3)
    assert harvest_fraction(100,80)==pytest.approx(.8)
    assert harvest_fraction(1000,300)==pytest.approx(.3)
    assert harvest_fraction(10,100)==pytest.approx(.95)

def test_focus_v2_profit_harvest_config_validation():
    cfg=Strategy2Config.from_mapping({"tradingMode":"focus","focusV2Enabled":True,"focusV2ProfitTriggerUsdt":15,"focusV2ProfitHarvestUsdt":10})
    assert cfg.focus_v2_profit_trigger_usdt==15 and cfg.focus_v2_profit_harvest_usdt==10
    with pytest.raises(ValueError): Strategy2Config.from_mapping({"tradingMode":"focus","focusV2Enabled":True,"focusV2ProfitTriggerUsdt":10,"focusV2ProfitHarvestUsdt":15})

def test_combined_cycle_evidence_allows_losing_hedge_only_when_combination_profitable():
    long=OwnedLeg("aster-strategy-2","strategy2","SOLUSDT","LONG","c",1,2,100,0,"FOCUS_V2_LONG",(),("l",),(),1,fees=.1,funding=0)
    short=OwnedLeg("aster-strategy-2","strategy2","SOLUSDT","SHORT","c",1,1.8,100,0,"FOCUS_V2_HEDGE",(),("s",),(),1,fees=.1,funding=0)
    net,parts=combined_close_evidence(uid="u",symbol="SOLUSDT",mark=110,long_leg=long,short_leg=short,long_qty=1,short_qty=.9)
    assert parts["grossPnl"]>0 and net>0

def test_wizard_exposes_continuous_harvest_fields():
    ui=(HERE.parent/"web/components/aster-strategy2-maker.tsx").read_text()
    assert 'label="Winsttrigger (USDT)"' in ui
    assert 'label="Winst nemen (USDT)"' in ui
    assert "focusV2ProfitTriggerUsdt" in ui and "focusV2ProfitHarvestUsdt" in ui

def test_focus_v2_dca_anchor_and_harvest_are_exposed_to_cockpit():
    main=(HERE/"main.py").read_text(); chart=(HERE.parent/"web/components/aster-recent-trades.tsx").read_text()
    assert '"dcaAnchorPrice":dca_anchor' in main
    assert '"profitSinceHarvest":profit_since_harvest' in main
    assert "Profit sinds harvest" in chart and "Nog tot harvest" in chart
