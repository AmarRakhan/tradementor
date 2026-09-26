from __future__ import annotations

from pathlib import Path


def extension_source() -> str:
    return Path(__file__).with_name("aster_legacy_hedge_scale_extension.py").read_text(encoding="utf-8")


def test_legacy_scale_is_owner_only_manual_and_separate_from_dca():
    value = extension_source()
    assert "main.require_continuity_owner(user)" in value
    assert 'EVENT_TYPE' in value
    assert 'LEGACY_HEDGE_SCALE' in Path(__file__).with_name("aster_legacy_hedge_scale.py").read_text(encoding="utf-8")
    assert 'request.confirm is not True' in value
    assert '"userConfirmed": True' in value
    assert 'marginPerSideUsd' in value
    assert 'plannedExtraQuantity' in value
    assert 'legacyScaleAddedQty' in value
    # The extension must not write any DCA state-machine field.
    forbidden_writes = [
        '"dcaCount"',
        '"nextDca"',
        '"lastDca"',
        '"smartRescue"',
        '"dcaHistory"',
        '"cycleId":',
    ]
    for marker in forbidden_writes:
        assert marker not in value


def test_legacy_scale_has_idempotency_pair_lock_partial_fill_repair_and_restart_recovery():
    value = extension_source()
    assert "_pair_lock" in value
    assert "_claim_persisted_pair_lock" in value
    assert "_release_persisted_pair_lock" in value
    assert "legacyScaleLock" in value
    assert "stable_scale_intent_id" in value
    assert "_query_existing" in value
    assert "_confirmed_fill" in value
    assert "parity_repair_action" in value
    assert "excess_rollback_action" in value
    assert '"rollback-excess"' in value
    assert "legacy-hedge-scale-recovery" in value
    assert "RECOVERABLE_OPERATION_STATUSES" in value
    assert '"RECONCILING"' in value
    assert "FAILED_NO_NEW_EXPOSURE" in value
    assert "main._acquire_aster_account_coordination" in value
    assert "main._release_aster_account_coordination" in value


def test_preview_and_execution_routes_are_distinct_and_preview_has_no_live_submit():
    value = extension_source()
    assert '/scale/preview' in value
    assert '/scale")' in value
    preview = value[value.index("def preview_legacy_hedge_scale"):value.index("def execute_legacy_hedge_scale")]
    assert "live_client=False" in preview
    assert "submit_order_once" not in preview
    execution = value[value.index("def execute_legacy_hedge_scale"):]
    assert "_resume_operation" in execution
    assert "confirm" in execution


def test_production_entrypoint_registers_legacy_scale_extension():
    entry = Path(__file__).with_name("withdraw_app.py").read_text(encoding="utf-8")
    assert "import aster_legacy_hedge_scale_extension" in entry


def test_break_even_preview_uses_exchange_break_even_when_available_and_fresh_current_price():
    value = extension_source()
    planner = Path(__file__).with_name("aster_legacy_hedge_scale.py").read_text(encoding="utf-8")
    assert 'row.get("breakEvenPrice")' in value
    assert '"ASTER_POSITION_RISK.breakEvenPrice"' in value
    assert '"ASTER_POSITION_RISK.entryPrice_FALLBACK"' in value
    assert '"ASTER_BOOK_TICKER_MID"' in value
    assert '"ASTER_POSITION_RISK_MARK"' in value
    assert "current_price=current_price" in value
    assert "long_break_even=long_break_even" in value
    assert "short_break_even=short_break_even" in value
    assert "break_even_distance(" in planner
    assert "break_even_distance_change(" in planner
    assert '"breakEvenDistanceBeforePct"' in planner
    assert '"breakEvenDistanceAfterPct"' in planner
    assert '"distanceChangeKind"' in planner
    assert '"distanceChangePct"' in planner


def test_build443_preflights_account_specific_opening_capacity_and_replans_stale_no_fill_operations():
    value = extension_source()
    planner = Path(__file__).with_name("aster_legacy_hedge_scale.py").read_text(encoding="utf-8")
    assert "remaining_openable_notional_value" in value
    assert "ASTER_REMAINING_OPENABLE_NOTIONAL_VALUE" in value
    assert "remaining_openable_notional_usd=remaining_capacity" in value
    assert "RECOVERY_REPLAN_REQUIRED" in value
    assert "initial_exists" in value
    assert "no_new_exposure" in value
    assert '"capacityLimited"' in planner
    assert '"plannedOpenNotionalUsd"' in planner


def test_build444_returns_actionable_lower_leverage_guidance_without_submitting_orders():
    value = extension_source()
    planner = Path(__file__).with_name("aster_legacy_hedge_scale.py").read_text(encoding="utf-8")
    assert "_recommended_lower_leverage" in value
    assert "_capacity_guidance" in value
    assert "client.leverage_brackets(symbol)" in value
    assert "client.remaining_openable_notional_value(symbol, candidate)" in value
    assert "capacityLimited" in value
    assert "leverage_capacity_guidance" in value
    assert "lower_leverage_candidates" in planner
    assert "heeft wel voldoende capaciteit" in planner
    assert "Verlaag {coin} naar" in planner
