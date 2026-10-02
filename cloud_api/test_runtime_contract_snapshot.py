from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "runtime_contract_snapshot.py"
SPEC = importlib.util.spec_from_file_location("runtime_contract_snapshot", MODULE_PATH)
assert SPEC and SPEC.loader
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


def test_snapshot_collector_source_is_read_only_by_construction():
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in (
        ".set(",
        ".delete(",
        ".add(",
        "submit_order",
        "cancel_order",
        "execute_leg",
        "AsterV3Client",
    ):
        assert forbidden not in source


def test_service_runtime_requires_background_cpu_and_min_instance():
    service = {
        "metadata": {"annotations": {}},
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "run.googleapis.com/cpu-throttling": "false",
                        "autoscaling.knative.dev/minScale": "1",
                    }
                }
            }
        },
    }
    cpu, minimum = snapshot._service_runtime(service)
    assert cpu is True
    assert minimum == 1


def test_periodic_worker_freshness_uses_recent_complete_tick_only():
    now = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    rows = [{
        "timestamp": "2026-10-02T07:59:15Z",
        "textPayload": "ASTER_PERIODIC_TICK_COMPLETE source=cloud-run-periodic-worker processed=4",
    }]
    assert snapshot._periodic_logs(rows, now_ms=now_ms) is True
    stale = [{
        "timestamp": "2026-10-02T07:50:00Z",
        "textPayload": "ASTER_PERIODIC_TICK_COMPLETE source=cloud-run-periodic-worker processed=4",
    }]
    assert snapshot._periodic_logs(stale, now_ms=now_ms) is False


def test_account_snapshot_contains_only_sanitized_runtime_contract_fields():
    raw = {
        "monitor": True,
        "enabled": True,
        "phase": "RUNNING",
        "lastTickAt": datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
        "settings": {
            "zoneSoldiersEnabled": True,
            "zoneSoldiersOptInVersion": 1,
            "secretField": "do-not-copy",
        },
        "multiBbReport": {
            "scannerDiagnostics": {"updatedAtMs": 123456},
            "positions": [{"symbol": "SECRETUSDT"}],
        },
        "zoneSoldierReport": {
            "activeZone": 28,
            "safeForNewEntries": True,
            "symbol": "SECRETUSDT",
        },
    }
    row = snapshot._account_row("real-user-id", raw)
    assert set(row) == {
        "accountRef",
        "monitor",
        "enabled",
        "phase",
        "lastTickAtMs",
        "scannerUpdatedAtMs",
        "scannerBlocked",
        "zoneEnabled",
        "activeZone",
        "zoneSafeForNewEntries",
    }
    assert row["accountRef"] != "real-user-id"
    assert "SECRETUSDT" not in str(row)
    assert "secretField" not in str(row)
