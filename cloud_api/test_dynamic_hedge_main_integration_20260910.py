from pathlib import Path

MAIN = Path(__file__).with_name("main.py").read_text(encoding="utf-8")


def segment(start: str, end: str) -> str:
    a = MAIN.index(start)
    b = MAIN.index(end, a + len(start))
    return MAIN[a:b]


def test_profit_close_is_wrapped_in_dynamic_hedge_manual_lock_and_reconcile():
    text = segment("def close_profitable_aster_positions(", '@app.post("/v1/me/aster/positions/{symbol}/close")')
    assert 'begin_manual_action(dynamic_hedge_ref, scope, before_manual_rows)' in text
    assert 'complete_manual_action(dynamic_hedge_ref, manual_guard, after_manual_rows)' in text
    assert 'fail_manual_action(dynamic_hedge_ref, manual_guard' in text
    assert '_release_strategy2_queue_lease(strategy_ref, queue_token)' in text


def test_single_side_close_locks_using_exact_requested_side():
    text = segment("def close_one_aster_position(", '@app.post("/v1/me/aster/simulate")')
    assert 'begin_manual_action(dynamic_hedge_ref, request.side, live_rows)' in text
    assert 'complete_manual_action(dynamic_hedge_ref, manual_guard, after_manual_rows)' in text
    assert 'str(row.get("positionSide", "")).upper() == request.side' in text
    assert 'fail_manual_action(dynamic_hedge_ref, manual_guard' in text


def test_emergency_all_close_locks_entire_dynamic_controller_until_flat_confirmed():
    text = segment("def close_all_aster_strategy(", '@app.get("/v1/me/aster/positions/profitable-close-preview")')
    assert 'begin_manual_action(dynamic_hedge_ref, "ALL", client.position_risk())' in text
    assert 'complete_manual_action(dynamic_hedge_ref, manual_guard, remaining)' in text
    assert 'fail_manual_action(dynamic_hedge_ref, manual_guard' in text
    assert 'if remaining:' in text


def test_dynamic_execution_gate_remains_off_by_default():
    api = Path(__file__).with_name("aster_dynamic_hedge_api.py").read_text(encoding="utf-8")
    assert 'os.getenv("ASTER_DYNAMIC_HEDGE_EXECUTION_ENABLED", "false")' in api


def test_main_installs_one_dynamic_hedge_route_family():
    assert MAIN.count("install_aster_dynamic_hedge_routes(") == 1
