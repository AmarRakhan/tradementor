from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "runtime_contract_post_deploy.py"
SPEC = importlib.util.spec_from_file_location("runtime_contract_post_deploy", MODULE_PATH)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


NOW = 1_000_000


def snapshot(**overrides):
    base = {
        "serviceReady": True,
        "backgroundCpuEnabled": True,
        "minInstances": 1,
        "periodicWorkerRecent": True,
        "periodicWorkerErrors": 0,
        "accounts": [],
    }
    base.update(overrides)
    return base


def account(ref="acct", **overrides):
    base = {
        "accountRef": ref,
        "monitor": True,
        "enabled": True,
        "lastTickAtMs": NOW - 30_000,
        "scannerUpdatedAtMs": NOW - 30_000,
        "scannerBlocked": False,
        "zoneEnabled": True,
        "activeZone": 28,
        "zoneSafeForNewEntries": True,
    }
    base.update(overrides)
    return base


def test_healthy_runtime_with_advancing_account_and_scanner_passes():
    before = snapshot(accounts=[account(lastTickAtMs=NOW - 120_000, scannerUpdatedAtMs=NOW - 120_000)])
    after = snapshot(accounts=[account(lastTickAtMs=NOW - 10_000, scannerUpdatedAtMs=NOW - 10_000)])
    result = gate.evaluate_runtime_contract(before, after, now_ms=NOW)
    assert result.ok is True
    assert result.failures == ()


def test_missing_periodic_worker_heartbeat_fails_release():
    result = gate.evaluate_runtime_contract(snapshot(), snapshot(periodicWorkerRecent=False), now_ms=NOW)
    assert result.ok is False
    assert "PERIODIC_WORKER_HEARTBEAT_MISSING" in result.failures


def test_background_cpu_and_warm_instance_are_hard_runtime_requirements():
    result = gate.evaluate_runtime_contract(
        snapshot(),
        snapshot(backgroundCpuEnabled=False, minInstances=0),
        now_ms=NOW,
    )
    assert result.ok is False
    assert "BACKGROUND_CPU_DISABLED" in result.failures
    assert "NO_WARM_INSTANCE" in result.failures


def test_monitored_account_must_advance_after_deploy():
    prior = account(lastTickAtMs=NOW - 100_000, scannerUpdatedAtMs=NOW - 100_000)
    current = account(lastTickAtMs=prior["lastTickAtMs"], scannerUpdatedAtMs=NOW - 5_000)
    result = gate.evaluate_runtime_contract(
        snapshot(accounts=[prior]),
        snapshot(accounts=[current]),
        now_ms=NOW,
    )
    assert result.ok is False
    assert "acct:ACCOUNT_TICK_DID_NOT_ADVANCE" in result.failures


def test_stale_account_tick_fails_even_when_global_worker_is_healthy():
    prior = account(lastTickAtMs=NOW - 500_000)
    current = account(lastTickAtMs=NOW - 300_000, scannerUpdatedAtMs=NOW - 5_000)
    result = gate.evaluate_runtime_contract(
        snapshot(accounts=[prior]),
        snapshot(accounts=[current]),
        now_ms=NOW,
    )
    assert result.ok is False
    assert "acct:ACCOUNT_TICK_STALE" in result.failures


def test_scanner_must_advance_when_enabled_and_not_dynamic_blocked():
    prior = account(lastTickAtMs=NOW - 100_000, scannerUpdatedAtMs=NOW - 100_000)
    current = account(lastTickAtMs=NOW - 5_000, scannerUpdatedAtMs=prior["scannerUpdatedAtMs"])
    result = gate.evaluate_runtime_contract(
        snapshot(accounts=[prior]),
        snapshot(accounts=[current]),
        now_ms=NOW,
    )
    assert result.ok is False
    assert "acct:SCANNER_DID_NOT_ADVANCE" in result.failures


def test_dynamic_hedge_hard_block_can_pause_scanner_without_failing_account_tick():
    prior = account(lastTickAtMs=NOW - 100_000, scannerUpdatedAtMs=NOW - 100_000)
    current = account(
        lastTickAtMs=NOW - 5_000,
        scannerUpdatedAtMs=prior["scannerUpdatedAtMs"],
        scannerBlocked=True,
    )
    result = gate.evaluate_runtime_contract(
        snapshot(accounts=[prior]),
        snapshot(accounts=[current]),
        now_ms=NOW,
    )
    assert result.ok is True


def test_active_zone_must_not_regress_from_known_zone_to_null():
    prior = account(activeZone=30, lastTickAtMs=NOW - 100_000, scannerUpdatedAtMs=NOW - 100_000)
    current = account(activeZone=None, lastTickAtMs=NOW - 5_000, scannerUpdatedAtMs=NOW - 5_000)
    result = gate.evaluate_runtime_contract(
        snapshot(accounts=[prior]),
        snapshot(accounts=[current]),
        now_ms=NOW,
    )
    assert result.ok is False
    assert "acct:ACTIVE_ZONE_REGRESSED_TO_NULL" in result.failures


def test_zone_entry_safety_change_is_warning_not_automatic_rollback():
    prior = account(zoneSafeForNewEntries=True, lastTickAtMs=NOW - 100_000, scannerUpdatedAtMs=NOW - 100_000)
    current = account(zoneSafeForNewEntries=False, lastTickAtMs=NOW - 5_000, scannerUpdatedAtMs=NOW - 5_000)
    result = gate.evaluate_runtime_contract(
        snapshot(accounts=[prior]),
        snapshot(accounts=[current]),
        now_ms=NOW,
    )
    assert result.ok is True
    assert "acct:ZONE_ENTRY_SAFETY_CHANGED" in result.warnings


def test_deploy_must_not_disable_monitoring_for_existing_account():
    prior = account(monitor=True)
    current = account(monitor=False, enabled=False)
    result = gate.evaluate_runtime_contract(
        snapshot(accounts=[prior]),
        snapshot(accounts=[current]),
        now_ms=NOW,
    )
    assert result.ok is False
    assert "acct:MONITOR_DISABLED_AFTER_DEPLOY" in result.failures


def test_new_periodic_worker_error_is_regression_but_existing_count_is_not():
    stable = gate.evaluate_runtime_contract(
        snapshot(periodicWorkerErrors=1),
        snapshot(periodicWorkerErrors=1),
        now_ms=NOW,
    )
    assert stable.ok is True
    regressed = gate.evaluate_runtime_contract(
        snapshot(periodicWorkerErrors=0),
        snapshot(periodicWorkerErrors=1),
        now_ms=NOW,
    )
    assert regressed.ok is False
    assert "PERIODIC_WORKER_ERRORS_REGRESSED" in regressed.failures


def test_runtime_phase_regression_to_data_hold_fails():
    prior = account(phase="RUNNING", lastTickAtMs=NOW - 100_000, scannerUpdatedAtMs=NOW - 100_000)
    current = account(phase="DATA_HOLD", lastTickAtMs=NOW - 5_000, scannerUpdatedAtMs=NOW - 5_000)
    result = gate.evaluate_runtime_contract(
        snapshot(accounts=[prior]),
        snapshot(accounts=[current]),
        now_ms=NOW,
    )
    assert result.ok is False
    assert "acct:RUNTIME_PHASE_REGRESSED_TO_DATA_HOLD" in result.failures
