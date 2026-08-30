from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import inspect

import pytest

from aster_strategy2_focus_v2 import (
    RECOVERY_MODEL_FAST,
    FocusV2State,
    continuous_dca_trigger,
    full_recovery,
    harvest_fraction,
    recovery_confirmed,
    recovery_progress,
    recovery_remaining_ratio,
    recovery_stage_for_progress,
    recovery_stage_price,
    release_quantity,
    rehedge_stop,
    state_from,
    state_map,
    target_hedge_notional,
)

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent


def test_01_target_hedge_keeps_small_long_bias():
    assert target_hedge_notional(1000,min_bias_usdt=25,min_bias_ratio=.02,max_hedge_ratio=.98)==975


def test_02_target_hedge_respects_ratio_cap():
    assert target_hedge_notional(1000,min_bias_usdt=0,min_bias_ratio=0,max_hedge_ratio=.8)==800


def test_03_progress_zero_at_low():
    assert recovery_progress(90,90,100)==0


def test_04_progress_one_at_break_even():
    assert recovery_progress(100,90,100)==1


def test_05_progress_can_exceed_one():
    assert recovery_progress(105,90,100)>1


def test_06_stage_threshold_1(): assert recovery_stage_for_progress(.22)==1

def test_07_stage_threshold_2(): assert recovery_stage_for_progress(.48)==2

def test_08_stage_threshold_3(): assert recovery_stage_for_progress(.72)==3

def test_09_stage_threshold_4(): assert recovery_stage_for_progress(.95)==4


def test_10_remaining_ratio_decays():
    assert recovery_remaining_ratio(2,.25)==pytest.approx(.75**2)


def test_11_remaining_zero_after_final(): assert recovery_remaining_ratio(4,.25)==0


def test_12_stage_price_uses_break_even_range():
    assert recovery_stage_price(90,100,1)==pytest.approx(92.2)


def test_13_stage_price_invalid_without_range(): assert recovery_stage_price(100,99,1)==0


def test_14_continuous_dca_trigger(): assert continuous_dca_trigger(100,.02)==98


def test_15_harvest_fraction_caps_at_95pct(): assert harvest_fraction(100,200)==.95


def test_16_harvest_fraction_exact(): assert harvest_fraction(100,25)==.25


def test_17_release_quantity_full(): assert release_quantity(5,.2,True)==5


def test_18_release_quantity_partial(): assert release_quantity(5,.2,False)==1


def test_19_rehedge_stop(): assert rehedge_stop(100,.01)==99


def test_20_recovery_requires_price():
    assert not recovery_confirmed(mark=90,recent_low=90,bollinger_middle=0,equity=100,cycle_start_equity=100,rebound_pct=.01,portfolio_ratio=.95,require_middle=False)


def test_21_recovery_allows_strong_price_before_full_equity():
    assert recovery_confirmed(mark=92,recent_low=90,bollinger_middle=0,equity=96,cycle_start_equity=100,rebound_pct=.01,portfolio_ratio=.99,require_middle=False)


def test_22_recovery_requires_middle_when_enabled():
    assert not recovery_confirmed(mark=92,recent_low=90,bollinger_middle=93,equity=100,cycle_start_equity=100,rebound_pct=.01,portfolio_ratio=.95,require_middle=True)


def test_23_full_recovery(): assert full_recovery(equity=100,cycle_start_equity=100,ratio=.99)


def test_24_state_defaults_legacy_model(): assert state_from({}).recovery_model_version==1


def test_25_state_reads_fast_model():
    assert state_from({'recoveryModelVersion':RECOVERY_MODEL_FAST}).recovery_model_version==RECOVERY_MODEL_FAST


def test_26_state_map_preserves_fast_fields():
    s=FocusV2State(recovery_model_version=RECOVERY_MODEL_FAST,released_short_qty=2,armed_rehedge_qty=3)
    m=state_map(s)
    assert m['releasedShortQty']==2 and m['armedRehedgeQty']==3


def test_27_legacy_state_shape_stays_legacy():
    assert state_from({'cycleId':'existing-live'}).recovery_model_version==1
    assert 'recoveryModelVersion' not in state_map(state_from({'cycleId':'existing-live'}))

def test_28_legacy_focus_engine_is_untouched_by_fast_recovery_module():
    src=(HERE/'aster_strategy2_focus_multi.py').read_text()
    assert 'FOCUS_HEDGE_CLOSE_BLOCKED' in src

def test_29_regular_strategy2_runtime_remains_separate():
    live=(HERE/'aster_strategy2_focus_live.py').read_text(); runtime=(HERE/'aster_strategy2_runtime.py').read_text()
    assert 'run_focus_v2_live_step' in live and 'RECOVERY_MODEL_FAST' not in runtime

def test_30_chart_and_cockpit_contract_exposes_current_focus_trigger_semantics():
    chart=(ROOT/'web/components/trading-chart.tsx').read_text(); cockpit=(ROOT/'web/components/aster-recent-trades.tsx').read_text(); main=(HERE/'main.py').read_text()
    for token in ('TRAILING TERUGVALKOOP','LAATSTE KOOP','SHORT RELEASE','vertTouchDrag:true'): assert token in chart
    for token in ('Cycle status','Starthedge','Hedge target','Take Profit','Auto-herstart'): assert token in cockpit
    for token in ('stateMachineVersion','nextShortReleaseQty','targetShortNotional','startHedgePercent','distanceToTp','autoRestart'): assert token in main


def test_31_v7_rehedge_is_armed_only_after_exchange_confirms_hedge_flat():
    src=(HERE/'aster_strategy2_focus_trailing.py').read_text()
    start=src.index('# v7 protected SHORT release')
    end=src.index('# Legacy non-simple Focus TP only', start)
    block=src[start:end]
    assert block.index('remaining_hedge_qty') < block.index('"reHedgeArmed": last_dca > 0')
    assert block.index('client.position_risk(symbol)') < block.index('"reHedgeArmed": last_dca > 0')
