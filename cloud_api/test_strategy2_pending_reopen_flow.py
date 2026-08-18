from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def _tick_source() -> str:
    start = MAIN.index("def _run_aster_strategy2_tick")
    end = MAIN.index("def aster_automation_public", start)
    return MAIN[start:end]


def _pending_reopen_block() -> str:
    tick = _tick_source()
    start = tick.index("pending_reopen_cooldown_until=")
    end = tick.index("selected=protection_selected", start)
    return tick[start:end]


def test_pending_reopen_cooldown_does_not_return_before_normal_candidates():
    tick = _tick_source()
    block = _pending_reopen_block()
    assert "pending_reopen_attempt_ready=pending_reopen_cooldown_until<=now_ms" in block
    assert "pending_reopens and pending_reopen_attempt_ready and enabled" in block
    assert "PENDING_REOPEN_COOLDOWN" not in block
    assert tick.index("selected=protection_selected") < tick.index("for candidate in candidates")


def test_definitive_pending_reopen_rejection_is_preserved_without_starving_scan():
    block = _pending_reopen_block()
    rejection = block[block.index('except Exception as exc:'):]
    assert 'pending["cooldownUntilMs"]=' in rejection
    assert 'ref.set({"pendingReopens":pending_reopens' in rejection
    assert 'action":"PENDING_REOPEN_REJECTED"' not in rejection
    assert "continue with other proven management" in rejection


def test_pending_reopen_skip_does_not_reserve_order_budget_or_remove_item():
    block = _pending_reopen_block()
    cooldown_gate = block[:block.index("if not ownership_isolated and not protection_selected")]
    assert "before_order" not in cooldown_gate
    assert "pending_reopens.pop(0)" not in cooldown_gate
    assert "ordersUsed" not in cooldown_gate


def test_pending_reopen_margin_is_deferred_so_tp_selection_can_continue():
    tick = _tick_source()
    block = _pending_reopen_block()
    margin = block[block.index("required*1.05>portfolio.available_balance"):]
    assert "portfolio.strategy_margin+required>portfolio.equity*settings.strategy_budget" in margin
    assert 'pending["cooldownUntilMs"]=now_ms+60*1000' in margin
    assert "raise Strategy2PendingReopenDeferred()" in margin
    assert "except Strategy2PendingReopenDeferred:" in margin
    assert 'action":"PENDING_REOPEN_MARGIN"' not in margin
    assert tick.index("except Strategy2PendingReopenDeferred:") < tick.index("selected=protection_selected")


def test_pending_recovery_mode_allows_tp_but_blocks_risk_increase_and_entries():
    tick = _tick_source()
    assert "before_order:Any=None,risk_reducing_only:bool=False" in tick
    assert "(ownership_isolated or risk_reducing_only) and selected and not selected[1].risk_reducing" in tick
    recovery_hold = tick.index("if risk_reducing_only:")
    scanner = tick.index("if not enabled or not scanner_allowed", recovery_hold)
    assert recovery_hold < scanner
    queue_start = MAIN.index("def _run_aster_strategy2_queue_scan")
    queue_end = MAIN.index("@app.post", queue_start)
    queue = MAIN[queue_start:queue_end]
    assert "risk_reducing_only=drain_pending_only" in queue


def test_existing_position_dca_path_remains_outside_pending_reopen_change():
    tick = _tick_source()
    dca_start = tick.index('if decision.kind in {"ADD_DCA","PROTECTION_INCREASE"}')
    dca_end = tick.index("if dry_run or not live", dca_start)
    dca = tick[dca_start:dca_end]
    assert "pending_reopen_attempt_ready" not in dca
    assert "new_position_leverage" not in dca


def test_queue_hard_limit_remains_fifteen():
    assert "MAX_ORDERS_PER_ACCOUNT_SCAN = 15" in (ROOT / "aster_strategy2_queue.py").read_text(encoding="utf-8")
