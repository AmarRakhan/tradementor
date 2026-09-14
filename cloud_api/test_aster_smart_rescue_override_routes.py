from pathlib import Path

SOURCE = (Path(__file__).with_name("main.py")).read_text(encoding="utf-8")


def route_block(start: str, end: str) -> str:
    left = SOURCE.index(start)
    right = SOURCE.index(end, left)
    return SOURCE[left:right]


def test_active_cycle_get_route_is_read_only_and_requires_persisted_smart_state():
    block = route_block(
        '@app.get("/v1/me/aster/strategy2/smart-rescue/{symbol}")',
        '@app.put("/v1/me/aster/strategy2/smart-rescue/{symbol}/extend")',
    )
    context = route_block("def _smart_rescue_override_context", '@app.get("/v1/me/aster/strategy2/smart-rescue/{symbol}")')
    assert 'outer.get("smartRescue")' in context
    assert 'position_risk(normalized)' in context
    assert 'positionAmt' in context
    assert 'ordersSent": 0' in block
    assert "execute_leg_once" not in block
    assert "submit_order" not in block


def test_extend_route_rechecks_cycle_and_has_no_order_execution_path():
    block = route_block(
        '@app.put("/v1/me/aster/strategy2/smart-rescue/{symbol}/extend")',
        '@app.put("/v1/me/aster/strategy2/settings")',
    )
    assert 'requested_cycle' in block and 'live_cycle' in block
    assert 'requested_cycle != live_cycle' in block
    assert 'extend_future_levels' in block
    assert 'merge=["multiBbPositions", "updatedAt", "lastReason"]' in block
    assert 'SMART_RESCUE_LADDER_EXTENDED' in block
    assert '"ordersSent": 0' in block
    assert "execute_leg_once" not in block
    assert "submit_order" not in block
    assert "change_leverage" not in block


def test_extend_route_uses_existing_strategy2_serialization_lease():
    block = route_block(
        '@app.put("/v1/me/aster/strategy2/smart-rescue/{symbol}/extend")',
        '@app.put("/v1/me/aster/strategy2/settings")',
    )
    assert "_strategy2_order_queue_enabled" in block
    assert "_acquire_strategy2_queue_lease" in block
    assert "_acquire_mexc_automation_lease" in block
    assert "_release_strategy2_queue_lease" in block
    assert 'leaseUntil' in block


def test_closed_or_non_smart_cycle_fails_closed_in_context_helper():
    block = route_block("def _smart_rescue_override_context", '@app.get("/v1/me/aster/strategy2/smart-rescue/{symbol}")')
    assert 'geen actieve Smart Rescue-cycle' in block
    assert 'Smart Rescue-cycle is niet meer actief op Aster' in block
    assert 'HTTPException(409' in block
