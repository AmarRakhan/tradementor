from pathlib import Path
S=Path(__file__).with_name('main.py').read_text()
def test_scoped_management_path():
    assert 'management_only:bool=False,event_symbol:str=""' in S and 'REALTIME_HOLD' in S
def test_existing_durable_queue_is_the_only_order_path():
    assert 'token=_acquire_strategy2_queue_lease(ref)' in S
    assert '_run_aster_strategy2_queue_scan(uid,maximum_orders=2,management_only=True,event_symbol=event.symbol,event_mark_price=event.mark_price)' in S
    assert '_release_strategy2_queue_lease(ref,str(token))' in S
def test_periodic_scheduler_is_retained(): assert '@app.post("/internal/aster-automation/tick")' in S
def test_worker_is_gated(): assert 'ASTER_REALTIME_WORKER' in S and 'ASTER_REALTIME_EXECUTION_ENABLED' in S

def test_simple_focus_marks_accounts_for_every_tick_evaluation():
    assert '_aster_realtime_simple_uids' in S
    assert 'focus_v2_simple_mode_enabled' in S
    assert 'force_evaluate=_aster_realtime_force_evaluate' in S


def test_realtime_mark_is_forwarded_to_strategy_decision_tick():
    assert 'event_mark_price:float|None=None' in S
    assert 'event_mark=safe_float(event_mark_price)' in S
    assert '"markPrice":event_mark' in S

def test_realtime_mark_override_executes_before_multi_bb_return_and_changes_only_matching_mark():
    start=S.index('# Realtime Strategy-2 management must evaluate the triggering symbol')
    normal_return=S.index('return run_multi_bb_step(client=client,ref=ref,raw_state=raw,settings=settings', start)
    assignment_end=S.index('# The legacy Focus/Strategy-2 planners are retired.', start)
    block=S[start:assignment_end]
    assert 'decision_positions=[({**row,"markPrice":event_mark}' in block
    assert 'str(row.get("symbol","")).upper()==event_symbol_norm' in block
    assert 'positionAmt' not in block
    assert 'positions=decision_positions' in S[start:]
    assert start < normal_return


def test_realtime_mark_override_also_reaches_multi_bb_when_dynamic_hedge_is_enabled():
    start=S.index('# Realtime Strategy-2 management must evaluate the triggering symbol')
    dynamic_call=S.index('settings=runtime_settings', start)
    assert 'positions=decision_positions' in S[dynamic_call-220:dynamic_call+220]


def test_realtime_simple_focus_budget_can_complete_atomic_dca_and_short_sync():
    assert '_run_aster_strategy2_queue_scan(uid,maximum_orders=2,management_only=True,event_symbol=event.symbol,event_mark_price=event.mark_price)' in S
    assert 'maximum_orders=1,management_only=True,event_symbol=event.symbol' not in S
