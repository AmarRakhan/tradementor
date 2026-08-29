from pathlib import Path
from aster_strategy2_focus_v2 import target_hedge_notional,release_quantity,recovery_confirmed,full_recovery,rehedge_stop,state_from,state_map,FocusV2State
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
    assert "expected_net" not in src

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

def test_tp_is_cycle_equity_based_and_cancels_rehedge():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "cycle_start_equity+settings.focus_take_profit_usdt" in src
    assert "_cancel_rehedge(client,state)" in src

def test_wizard_has_separate_focus_v2_opt_in():
    ui=(HERE.parent/"web/components/aster-strategy2-maker.tsx").read_text()
    assert 'title:"Focus | Focus 2.0"' in ui
    assert 'label="Focus 2.0 gebruiken"' in ui
    assert "Focus 2.0 · Beschermd LONG opbouwen" in ui
