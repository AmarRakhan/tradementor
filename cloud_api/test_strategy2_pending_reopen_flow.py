from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def _tick_source() -> str:
    start = MAIN.index("def _run_aster_strategy2_tick")
    end = MAIN.index("def _aster_brackets", start)
    return MAIN[start:end]


def _pending_reopen_block() -> str:
    tick = _tick_source()
    start = tick.index("management_selected=next_management_decision")
    end = tick.index("selected=take_profit_selected", start)
    return tick[start:end]


def test_pending_reopen_cooldown_does_not_return_before_normal_candidates():
    tick = _tick_source()
    block = _pending_reopen_block()
    assert "pending_reopen_attempt_ready=pending_reopen_cooldown_until<=now_ms" in block
    assert "not take_profit_selected and pending_reopens and pending_reopen_attempt_ready and enabled" in block
    assert "PENDING_REOPEN_COOLDOWN" not in block
    assert tick.index("selected=take_profit_selected") < tick.index("for candidate in candidates")


def test_take_profit_is_selected_before_pending_reopen():
    block = _pending_reopen_block()
    assert "management_selected=next_management_decision" in block
    assert 'management_selected[1].kind in {"FULL_TP","PARTIAL_TP"}' in block
    assert "not take_profit_selected" in block


def test_definitive_pending_reopen_rejection_is_preserved_without_starving_scan():
    block = _pending_reopen_block()
    rejection = block[block.index('except Exception as exc:'):]
    assert 'pending["cooldownUntilMs"]=' in rejection
    assert 'ref.set({"pendingReopens":pending_reopens' in rejection
    assert 'action":"PENDING_REOPEN_REJECTED"' not in rejection
    assert "continue with other proven management" in rejection


def test_pending_reopen_skip_does_not_reserve_order_budget_or_remove_item():
    block = _pending_reopen_block()
    cooldown_gate = block[:block.index("if not ownership_isolated and not protection_selected and not take_profit_selected")]
    assert "before_order" not in cooldown_gate
    assert "pending_reopens.pop(0)" not in cooldown_gate
    assert "ordersUsed" not in cooldown_gate


def test_pending_reopen_margin_wait_never_blocks_free_seat_filling():
    block = _pending_reopen_block()
    assert "required*1.05>portfolio.available_balance" in block
    assert "portfolio.strategy_margin+required>portfolio.equity*settings.strategy_budget" in block
    assert "vrije stoelen blijven doorstromen" in block
    assert 'action":"PENDING_REOPEN_MARGIN"' not in block


def test_existing_position_dca_path_remains_outside_pending_reopen_change():
    tick = _tick_source()
    dca_start = tick.index('if decision.kind in {"ADD_DCA","PROTECTION_INCREASE"}')
    dca_end = tick.index("if dry_run or not live", dca_start)
    dca = tick[dca_start:dca_end]
    assert "pending_reopen_attempt_ready" not in dca
    assert "new_position_leverage" not in dca


def test_queue_hard_limit_remains_fifteen():
    assert "MAX_ORDERS_PER_ACCOUNT_SCAN = 15" in (ROOT / "aster_strategy2_queue.py").read_text(encoding="utf-8")


def test_stale_cost_evidence_is_leg_local_while_user_seats_are_missing():
    tick = _tick_source()
    start = tick.index("if cost_holds:")
    end = tick.index("if ownership_isolated:", start)
    block = tick[start:end]
    assert 'seat_shortage=len(owned)<settings.maximum_pairs' in block
    assert "vrije stoelen blijven doorstromen" in block
    assert "if orders:" not in block
    assert "open_order_symbols" in block


def test_role_only_bookkeeping_never_preempts_empty_seat_refill():
    tick = _tick_source()
    guard = 'if selected and selected[1].kind in {"ASSIGN_PROTECTION","RELEASE_PROTECTION"} and len(owned)<settings.maximum_pairs:'
    assert guard in tick
    assert tick.index(guard) < tick.index("if selected:", tick.index(guard))
    assert "selected=None" in tick[tick.index(guard):tick.index("if selected:", tick.index(guard))]
