from __future__ import annotations

from pathlib import Path

from aster_runtime_truth import build_multi_bb_runtime_truth


def test_zone_warriors_runtime_truth_is_server_authoritative_and_capacity_consistent():
    result = build_multi_bb_runtime_truth(
        settings={"maximumPositions": 150},
        report={
            "accountPositionCount": 138,
            "accountRemainingCapacity": 12,
            "activeLong": 80,
            "activeShort": 58,
            "remainingLong": 3,
            "remainingShort": 3,
            "entryStatus": "WAITING_BOLLINGER_ENTRY",
            "entryReason": "Geen kandidaat",
            "scannerDiagnostics": {"LONG": {"timeframe": "1m"}, "SHORT": {"timeframe": "15m"}},
        },
        zone_report={"activeZone": 28, "safeForNewEntries": True},
        enabled=True,
        monitor=True,
        last_tick_at="tick",
        zone_active=True,
        dynamic_hedge_blocking=False,
        queue_halted=False,
    )

    assert result["source"] == "SERVER_RUNTIME"
    assert result["strategyMode"] == "ZONE_WARRIORS"
    assert result["activeZone"] == 28
    assert result["accountPositionCount"] == 138
    assert result["accountRemainingCapacity"] == 12
    assert result["invariants"]["capacityConsistent"] is True
    assert result["scannerDiagnostics"]["LONG"]["timeframe"] == "1m"
    assert result["scannerDiagnostics"]["SHORT"]["timeframe"] == "15m"


def test_zone_warriors_runtime_truth_flags_capacity_disagreement_without_mutation():
    report = {
        "accountPositionCount": 149,
        "accountRemainingCapacity": 9,
        "activeLong": 90,
        "activeShort": 59,
    }
    original = dict(report)
    result = build_multi_bb_runtime_truth(
        settings={"maximumPositions": 150},
        report=report,
        zone_report={"activeZone": 30, "safeForNewEntries": True},
        enabled=True,
        monitor=True,
        last_tick_at=None,
        zone_active=True,
        dynamic_hedge_blocking=False,
        queue_halted=False,
    )
    assert report == original
    assert result["invariants"]["capacityConsistent"] is False
    assert result["invariants"]["expectedAccountRemainingCapacity"] == 1


def test_classic_dca_runtime_truth_does_not_invent_operational_zone():
    result = build_multi_bb_runtime_truth(
        settings={"maximumPositions": 60},
        report={
            "accountPositionCount": 20,
            "accountRemainingCapacity": 40,
            "activeLong": 11,
            "activeShort": 9,
            "remainingLong": 19,
            "remainingShort": 21,
        },
        zone_report={"activeZone": 99, "safeForNewEntries": True},
        enabled=True,
        monitor=True,
        last_tick_at="tick",
        zone_active=False,
        dynamic_hedge_blocking=False,
        queue_halted=False,
    )
    assert result["strategyMode"] == "CLASSIC_DCA"
    assert result["activeZone"] is None
    assert result["zoneSafeForNewEntries"] is False


def test_runtime_truth_exposes_blocking_state_without_changing_trading_logic():
    result = build_multi_bb_runtime_truth(
        settings={"maximumPositions": 10},
        report={"accountPositionCount": 2, "accountRemainingCapacity": 8},
        zone_report={},
        enabled=True,
        monitor=True,
        last_tick_at="tick",
        zone_active=False,
        dynamic_hedge_blocking=True,
        queue_halted=True,
    )
    assert result["dynamicHedgeBlocking"] is True
    assert result["queueHalted"] is True


def test_strategy2_public_exposes_runtime_truth_without_replacing_legacy_fields():
    source = (Path(__file__).resolve().parent / "main.py").read_text(encoding="utf-8")
    assert "build_multi_bb_runtime_truth(" in source
    assert '"runtimeTruth":runtime_truth' in source
    assert '"multiBb":report' in source
    assert '"priceZoneSeats":zone_report' in source
