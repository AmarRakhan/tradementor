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
