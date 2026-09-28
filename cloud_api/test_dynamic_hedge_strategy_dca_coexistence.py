from pathlib import Path

from aster_dynamic_hedge_execution import dynamic_strategy_scan_blocked

SOURCE = Path(__file__).with_name('main.py').read_text()


def _dynamic_dispatch_block() -> str:
    start = SOURCE.index('if bool(dynamic_stored.get("enabled",False)):')
    end = SOURCE.index('    return run_multi_bb_step(client=client,ref=ref,raw_state=raw,settings=settings', start)
    return SOURCE[start:end]


def test_dynamic_hedge_does_not_claim_every_position_on_smaller_side():
    block = _dynamic_dispatch_block()
    assert 'blocked_side="SHORT" if long_exposure>short_exposure' not in block
    assert 'blocked_side=""' in block


def test_dynamic_hedge_still_fail_closes_each_strategy_order_through_guard():
    block = _dynamic_dispatch_block()
    assert 'dynamic_strategy_order_guard(dynamic_ref,intent,account,positions)' in block
    assert 'before_order=dynamic_before_order' in block


def test_dynamic_hedge_soft_hold_does_not_preempt_dominant_strategy_scan():
    assert dynamic_strategy_scan_blocked(
        enabled=True,
        orders_sent=0,
        reason="NO_MARGIN_SAFE_HEDGE_ORDER_AVAILABLE",
        safety_status="VEILIG",
        ownership_state="DYNAMIC_HEDGE_ACTIVE",
        status="waiting",
    ) is False


def test_dynamic_hedge_hard_safety_states_still_preempt_strategy_scan():
    common = {
        "enabled": True,
        "orders_sent": 0,
        "reason": "HEDGE_STABLE",
        "safety_status": "VEILIG",
        "ownership_state": "DYNAMIC_HEDGE_ACTIVE",
        "status": "waiting",
    }
    assert dynamic_strategy_scan_blocked(**{**common, "orders_sent": 1}) is True
    assert dynamic_strategy_scan_blocked(**{**common, "ownership_state": "ADOPTING"}) is True
    assert dynamic_strategy_scan_blocked(**{**common, "safety_status": "KRITIEK"}) is True
    assert dynamic_strategy_scan_blocked(**{**common, "status": "uncertain"}) is True
    assert dynamic_strategy_scan_blocked(**{**common, "reason": "open_order_reconciliation"}) is True


def test_runtime_uses_shared_dynamic_preemption_contract_not_any_nonstable_reason():
    block = _dynamic_dispatch_block()
    assert "dynamic_strategy_scan_blocked(" in block
    assert 'dynamic_reason!="HEDGE_STABLE"' not in block
