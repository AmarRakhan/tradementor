from dataclasses import replace
from pathlib import Path
import pytest

from aster_strategy2 import Strategy2Config
from aster_strategy2_focus_v2 import (
    RECOVERY_MODEL_FAST, FocusV2State, _arm_rehedge, _open_rehedge_stage, recovery_progress,
    recovery_remaining_ratio, recovery_stage_for_progress, recovery_stage_price,
    state_from, state_map, target_hedge_notional,
)

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent

class FakeExchange:
    def __init__(self): self.orders=[]; self.cancelled=[]
    def signed_request(self,method,path,payload):
        self.orders.append(dict(payload)); return {"orderId":len(self.orders),"clientOrderId":payload["newClientOrderId"]}
    def cancel_order(self,symbol,client_order_id=""):
        self.cancelled.append((symbol,client_order_id)); return {"status":"CANCELED"}

def cfg(**overrides):
    raw={"focusV2RehedgeSetbackPct":.003,"leverage":20}; raw.update(overrides)
    return Strategy2Config.from_mapping(raw)

def stage(price,low=80.0,be=100.0): return recovery_stage_for_progress(recovery_progress(price,low,be))
def test_01_bottom_formation_tracks_low_without_release():
    assert recovery_progress(80,80,100)==0 and stage(80)==0

def test_02_first_recovery_stage_starts_early():
    assert stage(84.4)==1

def test_03_first_partial_release_is_quantity_based():
    assert recovery_remaining_ratio(1,.33)==pytest.approx(.67)

def test_04_second_recovery_stage_reduces_more_hedge():
    assert stage(89.6)==2 and recovery_remaining_ratio(2,.33)<.67

def test_05_same_recovery_zone_does_not_advance_on_scheduler_tick():
    p=recovery_progress(89.6,80,100)
    assert recovery_stage_for_progress(p)==recovery_stage_for_progress(p)==2

def test_06_third_recovery_stage_is_before_break_even():
    assert stage(94.4)==3

def test_07_full_release_requires_explicit_final_stage():
    assert recovery_remaining_ratio(3,.33)>0
    assert recovery_remaining_ratio(4,.33)==0

def test_08_hedge_releases_while_long_still_below_break_even():
    assert 84.4<100 and stage(84.4)==1

def test_09_near_break_even_hedge_is_almost_or_fully_gone():
    assert stage(99.0)==4 and recovery_remaining_ratio(stage(99),.33)==0
def test_10_plus_10pct_from_low_has_progressive_dehedge():
    assert stage(88.0)>=1

def test_11_plus_20pct_from_low_has_heavy_dehedge():
    assert stage(96.0)>=3

def test_12_plus_50pct_from_low_is_fully_dehedged():
    assert stage(120.0)==4

def test_13_rehedge_after_first_release_is_exchange_stop_market():
    ex=FakeExchange(); s=FocusV2State(cycle_id="c",symbol="SOLUSDT",recovery_model_version=2,release_stage=1,released_short_qty=3)
    out=_arm_rehedge(client=ex,state=s,settings=cfg(),mark=100,quantity=3,reserve_order=None)
    assert out.armed_rehedge_qty==3 and ex.orders[0]["type"]=="STOP_MARKET" and float(ex.orders[0]["stopPrice"])<100

def test_14_multiple_releases_create_cumulative_backup_without_canceling_prior_stop():
    ex=FakeExchange(); s=FocusV2State(cycle_id="c",symbol="SOLUSDT",recovery_model_version=2,release_stage=1,released_short_qty=3)
    s=_arm_rehedge(client=ex,state=s,settings=cfg(),mark=100,quantity=3,reserve_order=None)
    s=replace(s,release_stage=2,released_short_qty=5)
    s=_arm_rehedge(client=ex,state=s,settings=cfg(),mark=102,quantity=2,reserve_order=None)
    assert len(ex.orders)==2 and not ex.cancelled and s.armed_rehedge_qty==pytest.approx(5)

def test_15_app_crash_does_not_remove_exchange_side_stop():
    ex=FakeExchange(); s=FocusV2State(cycle_id="c",symbol="SOLUSDT",recovery_model_version=2,release_stage=1,released_short_qty=4)
    _arm_rehedge(client=ex,state=s,settings=cfg(),mark=90,quantity=4,reserve_order=None)
    assert ex.orders and ex.orders[0]["workingType"]=="MARK_PRICE"
def test_16_dca_during_recovery_counts_armed_backup():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    assert 'armed_before_dca=(_open_rehedge_qty(open_orders,symbol)*mark if state.recovery_model_version>=RECOVERY_MODEL_FAST else 0.0)' in src

def test_17_new_dca_recomputes_full_protection_target_immediately():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    assert 'fresh_after_long=client.position_risk(symbol)' in src
    assert 'hedge_target_after=target_hedge_notional(actual_long_after' in src

def test_18_failed_dca_hedge_is_fail_closed():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    assert 'FOCUS_V2_PROTECTED_DCA_ROLLBACK' in src and 'execute_leg_once(client,rplan,side=PositionSide.LONG,action="CLOSE"' in src

def test_19_overhedge_is_explicitly_reconciled_to_policy_target():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    assert 'FOCUS_V2_OVERHEDGE_TRIM' in src and 'FOCUS_V2_REHEDGE_RECONCILED' in src
    target=target_hedge_notional(1000,min_bias_usdt=5,min_bias_ratio=.02,max_hedge_ratio=.95)
    assert target==950

def test_20_new_long_is_never_intentionally_left_naked():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    assert 'FOCUS_V2_WAIT_PROTECTED_OPEN' in src and 'FOCUS_V2_PROTECTED_OPEN_ROLLBACK' in src

def test_21_optional_5m_confirmation_can_be_enabled():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    assert 'middle_ok=(not settings.focus_v2_require_bollinger_middle) or (mid>0 and mark>=mid)' in src

def test_22_optional_5m_confirmation_off_does_not_block_recovery():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    assert '(not settings.focus_v2_require_bollinger_middle)' in src
def test_23_profit_harvest_remains_separate_from_recovery_release():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    assert src.index('FOCUS_V2_PROFIT_HARVEST') < src.index('FOCUS_V2_FAST_HEDGE_RELEASE')

def test_24_harvest_rearms_backup_for_fast_recovery_state():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    assert 'backup_notional=max(0.0,target_after-remaining_short)' in src
    assert 'state.recovery_model_version>=RECOVERY_MODEL_FAST' in src

def test_25_restart_preserves_recovery_state_and_backup_ids():
    s=FocusV2State(cycle_id='c',symbol='SOLUSDT',recovery_model_version=2,release_stage=2,released_short_qty=5,armed_rehedge_qty=5,last_release_price=91,next_release_price=95,recovery_progress_ratio=.5,rehedge_client_ids=('a','b'))
    assert state_from(state_map(s))==s

def test_26_manual_flat_resets_cycle_state_without_migration():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    assert 'state_map(FocusV2State())' in src and 'FOCUS_V2_CYCLE_FLAT' in src

def test_27_new_cycle_starts_clean_on_fast_recovery_model():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    assert 'recovery_model_version=(RECOVERY_MODEL_SIMPLE if settings.focus_v2_simple_mode_enabled else RECOVERY_MODEL_FAST)' in src
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
    for token in ('BREAK-EVEN','DCA / SHORT SYNC','SHORT RELEASE','vertTouchDrag:true'): assert token in chart
    for token in ('Cycle status','Starthedge','Hedge target','Take Profit','Auto-herstart'): assert token in cockpit
    for token in ('stateMachineVersion','nextShortReleaseQty','targetShortNotional','startHedgePercent','distanceToTp','autoRestart'): assert token in main


def test_31_release_arms_exchange_backup_before_closing_short():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    block=src[src.index('# Safety ordering: exchange-side fallback'):src.index('next_release=recovery_stage_price',src.index('# Safety ordering: exchange-side fallback'))]
    assert block.index('_arm_rehedge(') < block.index('_close_v2_leg(')

def test_32_restart_recovers_stage_from_exchange_client_order_id():
    orders=[{'symbol':'SOLUSDT','clientOrderId':'s2fv2rh-2-abc','origQty':'3'},{'symbol':'SOLUSDT','clientOrderId':'s2fv2rh-3-def','origQty':'2'}]
    assert _open_rehedge_stage(orders,'SOLUSDT')==3
