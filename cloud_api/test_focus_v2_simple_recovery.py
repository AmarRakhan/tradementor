from pathlib import Path

from aster_strategy2 import Strategy2Config
from aster_strategy2_focus_v2 import RECOVERY_MODEL_SIMPLE, state_from, state_map

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent

def test_simple_mode_is_explicit_opt_in_and_roundtrips():
    old=Strategy2Config.from_mapping({"tradingMode":"focus","focusV2Enabled":True})
    new=Strategy2Config.from_mapping({"tradingMode":"focus","focusV2Enabled":True,"focusV2SimpleModeEnabled":True})
    assert old.focus_v2_simple_mode_enabled is False
    assert new.focus_v2_simple_mode_enabled is True
    assert new.public_dict()["focusV2SimpleModeEnabled"] is True

def test_legacy_active_state_is_not_version_stamped():
    state=state_from({"cycleId":"legacy-live","symbol":"SOLUSDT"})
    assert state.recovery_model_version==1
    assert "recoveryModelVersion" not in state_map(state)

def test_new_saved_simple_cycle_selects_model_3():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "RECOVERY_MODEL_SIMPLE=3" in src
    assert "RECOVERY_MODEL_SIMPLE if settings.focus_v2_simple_mode_enabled else RECOVERY_MODEL_FAST" in src

def test_simple_recovery_arms_stop_before_full_short_release():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    start=src.index("release_pending=bool(recovery_ok and middle_ok")
    end=src.index("# No recovery:",start)
    block=src[start:end]
    assert block.index("_arm_rehedge(") < block.index("_close_v2_leg(")
    assert "quantity=target_qty" in block
    assert "short_qty*mark" in block
    assert "FOCUS_V2_SIMPLE_SHORT_RELEASED" in block

def test_simple_recovery_has_no_staged_33_percent_release():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    start=src.index("# Recovery model 3: one simple airbag cycle")
    end=src.index("# No recovery:",start)
    block=src[start:end]
    assert "recovery_remaining_ratio" not in block
    assert "focus_v2_release_ratio" not in block
    assert "desired_stage" not in block

def test_simple_mode_disables_continuous_profit_harvest():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "state.recovery_model_version<RECOVERY_MODEL_SIMPLE and trigger_usdt>0" in src

def test_simple_long_tp_closes_long_then_strictly_cancels_rehedge():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    start=src.index("# Simple Focus 2.0: once the active SHORT is released")
    end=src.index("# Reconcile protective hedge",start)
    block=src[start:end]
    assert block.index("_close_v2_leg(") < block.index("_cancel_rehedge_strict(")
    assert "FOCUS_V2_TP_CYCLE_CLOSED" in block
    assert "client.position_risk(symbol)" in block

def test_simple_rehedge_restore_and_dca_reuse_exchange_truth():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "FOCUS_V2_REHEDGE_RESTORED" in src
    assert "fresh_after_long=client.position_risk(symbol)" in src
    assert "FOCUS_V2_PROTECTED_DCA_ROLLBACK" in src

def test_simple_wizard_has_five_steps_and_hides_legacy_release_controls():
    src=(ROOT/"web/components/aster-strategy2-maker.tsx").read_text()
    start=src.index(" const focusSteps=[")
    end=src.index(" const steps=",start)
    block=src[start:end]
    assert sum(block.count(f'title:"{n} ·') for n in range(1,6))==5
    assert "SHORT vrijgeven per herstelstap" not in block
    assert "Portfolio bijna hersteld" not in block
    assert "doorlopende harvest" not in block
    assert "focusV2SimpleModeEnabled:v.focusV2Enabled" in src

def test_simple_wizard_exposes_only_core_flow_in_summary():
    src=(ROOT/"web/components/aster-strategy2-maker.tsx").read_text()
    for token in ("DCA-afstand (%)","Maximale hedge (%)","Herstel vanaf recente low (%)","Re-hedge terugval (%)","LONG Take Profit (%)"):
        assert token in src
    assert "STOP eerst bevestigd → actieve SHORT volledig weg → terugval = hedge terug." in src

def test_simple_cockpit_and_chart_use_new_semantics():
    cockpit=(ROOT/"web/components/aster-recent-trades.tsx").read_text()
    chart=(ROOT/"web/components/trading-chart.tsx").read_text()
    main=(HERE/"main.py").read_text()
    for token in ("SHORT VRIJ · LONG KRIJGT RUIMTE","BODEM / HERSTEL · SHORT STOP EERST GEWAPEND","longTakeProfitPrice"):
        assert token in main
    assert "HERSTELTRIGGER · SHORT VRIJ" in chart
    assert "LONG TAKE PROFIT" in chart
    assert "Hersteltrigger" in cockpit and "LONG Take Profit" in cockpit

def test_simple_restart_reconstructs_armed_stop_from_exchange_truth():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "armed_ids=_open_rehedge_ids(open_orders,symbol)" in src
    assert "release_stage=max(state.release_stage,armed_stage)" in src
    assert "armed_live_qty>=target_qty-tolerance_qty and armed_ids" in src
    assert "new_backup_cid=""" in src

def test_simple_percent_tp_uses_expected_net_profit_not_raw_price_only():
    src=(HERE/"aster_strategy2_focus_v2.py").read_text()
    assert "tp_profit_target" in src
    assert "long_net>=tp_profit_target" in src
