from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
EXECUTION = (ROOT / "aster_execution.py").read_text(encoding="utf-8")


def _tick_source() -> str:
    start = MAIN.index("def _run_aster_strategy2_tick")
    end = MAIN.index("def _aster_brackets", start)
    return MAIN[start:end]


def test_every_strategy2_brand_new_entry_route_uses_the_central_guard():
    tick = _tick_source()
    assert tick.count("new_position_leverage=settings.leverage") == 3
    assert '"kind":"PENDING_REOPEN"' in tick
    assert '"kind":"AUTO_RESTART"' in tick
    assert '"kind":"INITIAL_OPEN_LEG" if not initial_build_complete else "OPEN_LEG"' in tick


def test_new_entry_routes_never_use_lower_leverage_fallback():
    tick = _tick_source()
    for marker in ("pending_reopens and pending_reopen_attempt_ready and enabled", 'decision.kind=="FULL_TP"', "for candidate in candidates"):
        assert marker in tick
    assert "reopen=replace(reopen,leverage=min(reopen.leverage,settings.leverage))" not in tick
    assert "accepted=configure_maximum_usable_leverage(client,value)" not in tick
    assert "accepted_leverage=settings.leverage" in tick
    assert "value=replace(value,leverage=settings.leverage)" not in tick


def test_dca_does_not_invoke_the_new_position_guard():
    tick = _tick_source()
    start = tick.index('if decision.kind in {"ADD_DCA","PROTECTION_INCREASE"}')
    end = tick.index("if dry_run or not live", start)
    dca = tick[start:end]
    assert "new_position_leverage" not in dca
    assert "configure_maximum_usable_leverage" in dca


def test_guard_finishes_before_queue_reservation_and_submission():
    start = EXECUTION.index("def execute_leg_once")
    block = EXECUTION[start:EXECUTION.index("def execute_harvest_reset", start)]
    assert block.index("require_exact_new_position_leverage") < block.index("before_submit(intent)")
    assert block.index("before_submit(intent)") < block.index("client.submit_order_once")


def test_candidate_local_leverage_rejection_advances_without_failing_account_scan():
    tick = _tick_source()
    candidate = tick[tick.index("for candidate in candidates"):]
    assert "isinstance(exc,NewPositionLeverageBlocked)" in candidate
    assert "scan_skipped+=1;advanced_after_rejection=True" in candidate
    assert "continue" in candidate


def test_new_guard_does_not_change_configured_notional():
    guard = EXECUTION[EXECUTION.index("def require_exact_new_position_leverage"):EXECUTION.index("def _confirmed_fill")]
    assert "plan.notional_per_leg" in guard
    assert "replace(" not in guard
    assert "quantity" not in guard


def test_no_static_symbol_leverage_table_or_lower_candidate_list_in_new_guard():
    guard = EXECUTION[EXECUTION.index("def require_exact_new_position_leverage"):EXECUTION.index("def _confirmed_fill")]
    assert "contract_brackets(client, [], plan.symbol)" in guard
    assert "(200, 150, 125" not in guard
    assert "min(" not in guard
