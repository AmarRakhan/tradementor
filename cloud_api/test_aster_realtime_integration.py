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

def test_realtime_mark_override_changes_only_matching_symbol_mark_not_exchange_quantities():
    block=S[S.index('# Realtime Simple Mode must make DCA/release decisions'):S.index('_run_focus_shadow_scheduler_step', S.index('# Realtime Simple Mode must make DCA/release decisions'))]
    assert 'positions=[({**row,"markPrice":event_mark}' in block
    assert 'str(row.get("symbol","")).upper()==event_symbol_norm' in block
    assert 'positionAmt' not in block


def test_realtime_simple_focus_budget_can_complete_atomic_dca_and_short_sync():
    assert '_run_aster_strategy2_queue_scan(uid,maximum_orders=2,management_only=True,event_symbol=event.symbol,event_mark_price=event.mark_price)' in S
    assert 'maximum_orders=1,management_only=True,event_symbol=event.symbol' not in S
