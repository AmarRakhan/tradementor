from pathlib import Path
import pytest

from aster_strategy2 import Strategy2Config
from aster_strategy2_focus_v2 import RECOVERY_MODEL_SIMPLE, harvest_fraction, state_from, state_map

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
ENGINE=(HERE/"aster_strategy2_focus_v2.py").read_text()
MAKER=(ROOT/"web/components/aster-strategy2-maker.tsx").read_text()
COCKPIT=(ROOT/"web/components/aster-recent-trades.tsx").read_text()
CHART=(ROOT/"web/components/trading-chart.tsx").read_text()
MAIN=(HERE/"main.py").read_text()

def simple_cfg(trigger=100,harvest=10):
    return Strategy2Config.from_mapping({"tradingMode":"focus","focusV2Enabled":True,"focusV2SimpleModeEnabled":True,"focusV2ProfitTriggerUsdt":trigger,"focusV2ProfitHarvestUsdt":harvest})

def test_01_simple_mode_is_explicit_opt_in_and_roundtrips():
    old=Strategy2Config.from_mapping({"tradingMode":"focus","focusV2Enabled":True})
    new=simple_cfg()
    assert old.focus_v2_simple_mode_enabled is False and new.focus_v2_simple_mode_enabled is True
    assert new.public_dict()["focusV2SimpleModeEnabled"] is True

def test_02_trigger_100_harvest_10_are_configurable():
    c=simple_cfg(100,10); assert (c.focus_v2_profit_trigger_usdt,c.focus_v2_profit_harvest_usdt)==(100,10)

def test_03_trigger_50_harvest_5_are_configurable():
    c=simple_cfg(50,5); assert (c.focus_v2_profit_trigger_usdt,c.focus_v2_profit_harvest_usdt)==(50,5)

def test_04_harvest_cannot_exceed_trigger():
    with pytest.raises(ValueError): simple_cfg(10,15)

def test_05_simple_harvest_requires_positive_pair():
    with pytest.raises(ValueError): simple_cfg(0,0)

def test_06_legacy_active_state_is_not_version_stamped():
    state=state_from({"cycleId":"legacy-live","symbol":"SOLUSDT"}); assert state.recovery_model_version==1 and "recoveryModelVersion" not in state_map(state)

def test_07_new_saved_simple_cycle_selects_model_3():
    assert "RECOVERY_MODEL_SIMPLE=3" in ENGINE and "RECOVERY_MODEL_SIMPLE if settings.focus_v2_simple_mode_enabled else RECOVERY_MODEL_FAST" in ENGINE

def test_08_simple_recovery_arms_stop_before_full_short_release():
    start=ENGINE.index("release_pending=bool(recovery_ok and middle_ok"); end=ENGINE.index("# No recovery:",start); block=ENGINE[start:end]
    assert block.index("_arm_rehedge(") < block.index("_close_v2_leg(") and "quantity=target_qty" in block and "short_qty*mark" in block

def test_09_simple_recovery_has_no_staged_33_percent_release():
    start=ENGINE.index("# Recovery model 3: one simple airbag cycle"); end=ENGINE.index("# No recovery:",start); block=ENGINE[start:end]
    assert "recovery_remaining_ratio" not in block and "focus_v2_release_ratio" not in block and "desired_stage" not in block

def test_10_model3_uses_continuous_partial_harvest():
    assert "state.recovery_model_version>=RECOVERY_MODEL_SIMPLE and trigger_usdt>0" in ENGINE
    assert 'cycleContinues":True' in ENGINE

def test_11_harvest_uses_only_long_close_in_simple_branch():
    start=ENGINE.index("if state.recovery_model_version>=RECOVERY_MODEL_SIMPLE and trigger_usdt>0"); end=ENGINE.index("if state.recovery_model_version<RECOVERY_MODEL_SIMPLE",start); block=ENGINE[start:end]
    assert 'side=PositionSide.LONG' in block and 'side=PositionSide.SHORT' in block  # SHORT only for post-harvest overhedge trim
    assert "simple-harvest" in block

def test_12_harvest_fraction_never_targets_full_close():
    assert harvest_fraction(100,10)==pytest.approx(.1) and harvest_fraction(50,5)==pytest.approx(.1)

def test_13_engine_explicitly_blocks_full_long_harvest():
    assert "Focus 2.0 harvest mag de volledige LONG niet sluiten" in ENGINE

def test_14_harvest_rereads_exchange_position():
    assert "fresh_positions=client.position_risk(symbol)" in ENGINE

def test_15_harvest_keeps_remaining_long_positive():
    assert "remaining_long<=max(1.0,long_notional*.002)" in ENGINE

def test_16_harvest_sets_new_baseline():
    assert "harvest_baseline_equity=new_equity" in ENGINE and "newBaselineEquity=new_equity" in ENGINE

def test_17_harvest_resets_profit_since_harvest_history():
    assert '"profitSinceHarvest":0.0' in ENGINE and '"profitRemainingUsdt":trigger_usdt' in ENGINE

def test_18_total_harvested_profit_accumulates():
    assert "total_harvested_profit=state.total_harvested_profit+realized_net" in ENGINE

def test_19_last_harvest_profit_is_persisted():
    assert "last_harvest_profit=realized_net" in ENGINE

def test_20_cost_evidence_is_required():
    assert 'action":"FOCUS_V2_HARVEST_COST_EVIDENCE_WAIT"' in ENGINE and "long_costs_reliable" in ENGINE and "short_costs_reliable" in ENGINE

def test_21_fees_funding_and_slippage_are_used():
    assert "combined_close_evidence" in ENGINE and "feesFundingSlippage=costs" in ENGINE

def test_22_harvest_active_short_recalculates_target():
    assert "target_after=target_hedge_notional(remaining_long" in ENGINE

def test_23_harvest_trims_active_overhedge():
    assert "remaining_short>target_after+tolerance" in ENGINE and "-hedgetrim" in ENGINE

def test_24_harvest_reconciles_armed_stop_quantity():
    assert "desired_armed_qty=max(0.0,(target_after-remaining_short)" in ENGINE and "old_orders=_rehedge_orders(fresh_orders,symbol)" in ENGINE

def test_25_replacement_stop_is_armed_before_old_is_cancelled():
    start=ENGINE.index("# Conditional re-hedge quantity must also match the remaining LONG"); end=ENGINE.index("fresh_account=client.account_information()",start); block=ENGINE[start:end]
    assert block.index("_arm_rehedge(") < block.index("client.cancel_order(")

def test_26_rehedge_restore_survives_after_harvest():
    assert "FOCUS_V2_REHEDGE_RESTORED" in ENGINE

def test_27_dca_after_rehedge_still_rereads_exchange_truth():
    assert "fresh_after_long=client.position_risk(symbol)" in ENGINE and "FOCUS_V2_PROTECTED_DCA_ROLLBACK" in ENGINE

def test_28_restart_reconstructs_armed_stop_from_exchange_truth():
    assert "armed_ids=_open_rehedge_ids(open_orders,symbol)" in ENGINE and "armed_live_qty>=target_qty-tolerance_qty and armed_ids" in ENGINE

def test_29_existing_stop_is_reused_without_duplicate():
    assert 'new_backup_cid=""' in ENGINE

def test_30_model2_branch_remains_separate():
    assert "elif state.recovery_model_version==RECOVERY_MODEL_FAST" in ENGINE and "recovery_remaining_ratio" in ENGINE

def test_31_model1_branch_remains_separate():
    assert "if state.recovery_model_version < RECOVERY_MODEL_FAST" in ENGINE

def test_32_wizard_has_exactly_five_focus_steps():
    block=MAKER[MAKER.index(" const focusSteps=["):MAKER.index(" const steps=",MAKER.index(" const focusSteps=["))]
    assert sum(block.count(f'title:"{n} ·') for n in range(1,6))==5

def test_33_step4_core_fields_remain_visible():
    for token in ('label="Maximale hedge (%)"','label="Herstel vanaf recente low (%)"','label="Re-hedge terugval (%)"'): assert token in MAKER

def test_34_step4_advanced_is_collapsed_by_default():
    assert 'advanced:false' in MAKER and 'label="Geavanceerde protection-instellingen"' in MAKER

def test_35_step5_is_profit_harvest_not_take_profit():
    assert 'title:"5 · Winst afromen & controle"' in MAKER and 'label="Winsttrigger (USDT)"' in MAKER and 'label="Winst afromen (USDT)"' in MAKER

def test_36_simple_summary_says_cycle_stays_active():
    assert "cycle blijft actief" in MAKER and "LONG sluiten bij netto winst" not in MAKER

def test_37_cockpit_exposes_harvest_progress_for_simple_mode():
    for token in ("Winst sinds harvest","Nog tot afromen","Laatste / totaal afgeroomd"): assert token in COCKPIT

def test_38_cockpit_has_no_simple_long_take_profit_label():
    assert 'simple?"Winsttrigger"' in COCKPIT and 'simple?"LONG Take Profit"' not in COCKPIT

def test_39_chart_supports_harvest_marker():
    assert 'one?.kind==="harvest"?"HARVEST"' in CHART

def test_40_trade_events_overlay_harvest_audit():
    assert '"kind":"harvest"' in MAIN and 'FOCUS_V2_PROFIT_HARVEST' in MAIN and 'aster-confirmed-fills+focus-audit' in MAIN

def test_41_main_exposes_simple_harvest_statuses():
    for token in ("WINSTTRIGGER BEREIKT","WINST AFGEROOMD · CYCLE BLIJFT ACTIEF","NOG ${profit_remaining:.2f} TOT WINST AFROMEN"): assert token in MAIN

def test_42_simple_hold_history_keeps_configured_harvest_values():
    assert '"profitTriggerUsdt":settings.focus_v2_profit_trigger_usdt' in ENGINE and '"profitHarvestUsdt":settings.focus_v2_profit_harvest_usdt' in ENGINE

def test_43_stop_before_short_release_contract_is_unchanged():
    start=ENGINE.index("release_pending=bool(recovery_ok and middle_ok"); end=ENGINE.index("FOCUS_V2_SIMPLE_SHORT_RELEASED",start); block=ENGINE[start:end]
    assert block.index("_arm_rehedge(") < block.index("_close_v2_leg(")

def test_44_no_simple_full_tp_cycle_close_remains():
    simple_start=ENGINE.index("# Recovery model 3: one simple airbag cycle")
    assert "FOCUS_V2_TP_CYCLE_CLOSED" not in ENGINE[simple_start:]

def test_45_configured_harvest_is_not_hardcoded_100_10():
    assert 'focusV2ProfitTriggerUsdt:num(v.focusV2ProfitTrigger)' in MAKER and 'focusV2ProfitHarvestUsdt:num(v.focusV2ProfitHarvest)' in MAKER
