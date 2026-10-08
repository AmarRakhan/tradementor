from __future__ import annotations

from pathlib import Path

from aster_runtime_truth import build_canonical_zone_state, build_multi_bb_runtime_truth


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



def test_canonical_zone_state_reconciles_31_account_positions_as_30_zone_plus_one_other():
    positions = [
        *[{"symbol": f"L{i}USDT", "side": "LONG"} for i in range(30)],
        {"symbol": "MANUALUSDT", "side": "LONG"},
    ]
    managed = {
        f"L{i}USDT|LONG": {
            "soldierRole": "ZONE_BASE",
            "originZone": i % 3,
        }
        for i in range(30)
    }
    result = build_canonical_zone_state(
        settings={
            "priceZoneSeats": {"longSeatsPerZone": 2, "shortSeatsPerZone": 0},
            "maximumPositions": 60,
        },
        positions=positions,
        managed_positions=managed,
        zone_report={
            "activeZone": 1,
            "runtimeSync": {
                "activeZone": 1,
                "currentEquity": 315.08,
                "zones": [
                    {"index": 0, "center": 312.9, "lower": 312.0, "upper": 313.8},
                    {"index": 1, "center": 314.7, "lower": 313.8, "upper": 315.6},
                    {"index": 2, "center": 316.5, "lower": 315.6, "upper": 317.4},
                ],
            },
        },
        snapshot_at_ms=123,
    )
    assert result["account"] == {"totalOpen": 31, "longOpen": 31, "shortOpen": 0}
    assert result["strategyOwned"] == {"totalOpen": 30, "longOpen": 30, "shortOpen": 0}
    assert result["nonStrategyOwned"] == {"totalOpen": 1, "longOpen": 1, "shortOpen": 0}
    assert result["capacity"]["perZoneShort"] == 0
    assert result["otherOpenPositions"][0]["positionKey"] == "MANUALUSDT|LONG"
    assert result["reconciliation"]["accountMatches"] is True
    assert result["reconciliation"]["strategyMatches"] is True


def test_canonical_zone_state_keeps_strategy_position_without_origin_explicitly_unassigned():
    result = build_canonical_zone_state(
        settings={"priceZoneSeats": {"longSeatsPerZone": 2, "shortSeatsPerZone": 0}},
        positions=[{"symbol": "ABCUSDT", "side": "LONG"}],
        managed_positions={"ABCUSDT|LONG": {"soldierRole": "ZONE_BASE", "originZone": None}},
        zone_report={},
    )
    assert result["strategyOwned"]["totalOpen"] == 1
    assert result["reconciliation"]["zoneAssignedTotal"] == 0
    assert result["reconciliation"]["unassignedStrategyTotal"] == 1
    assert result["unassignedStrategyPositions"][0]["reason"] == "MISSING_ORIGIN_ZONE"
    assert result["reconciliation"]["strategyMatches"] is True


def test_next_long_levels_follow_canonical_price_and_skip_full_zones():
    from aster_runtime_truth import _canonical_long_next_levels
    zones = [
        {"index": -2, "lower": 70, "upper": 80, "longOpen": 0, "longMax": 2},
        {"index": -1, "lower": 80, "upper": 90, "longOpen": 1, "longMax": 2},
        {"index": 0, "lower": 90, "upper": 100, "longOpen": 2, "longMax": 2},
        {"index": 1, "lower": 100, "upper": 110, "longOpen": 2, "longMax": 2},
        {"index": 2, "lower": 110, "upper": 120, "longOpen": 0, "longMax": 2},
    ]
    result = _canonical_long_next_levels(zones, 95, reliable=True)
    assert result["up"]["zone"] == 2
    assert result["up"]["price"] == 110
    assert result["up"]["distance"] == 15
    assert result["down"]["zone"] == -1
    assert result["down"]["price"] == 90
    assert result["down"]["distance"] == 5
    assert result["up"]["entryPermission"] == "NOT_EVALUATED"


def test_next_long_levels_never_invent_missing_canonical_price():
    from aster_runtime_truth import _canonical_long_next_levels
    row = {"index": 1, "lower": 100, "upper": 110, "longOpen": 0, "longMax": 2}
    assert _canonical_long_next_levels([row], None, reliable=True)["status"] == "UNAVAILABLE"
    assert _canonical_long_next_levels([row], 95, reliable=False)["up"] is None
    assert _canonical_long_next_levels([], 95, reliable=True)["up"] is None


def test_next_free_position_levels_accepts_either_long_or_short_capacity():
    from aster_runtime_truth import _canonical_next_free_position_levels
    zones = [
        {"index": 0, "lower": 309.27, "upper": 311.60, "longOpen": 4, "longMax": 4, "shortOpen": 2, "shortMax": 2},
        {"index": 1, "lower": 311.60, "upper": 313.85, "longOpen": 4, "longMax": 4, "shortOpen": 2, "shortMax": 2},
        {"index": 2, "lower": 313.85, "upper": 315.87, "longOpen": 4, "longMax": 4, "shortOpen": 1, "shortMax": 2},
        {"index": -1, "lower": 307.18, "upper": 309.27, "longOpen": 4, "longMax": 4, "shortOpen": 0, "shortMax": 2},
    ]
    result = _canonical_next_free_position_levels(zones, 311.45, reliable=True)
    assert result["status"] == "AVAILABLE"
    assert result["up"]["zone"] == 2
    assert round(result["up"]["distance"], 2) == 2.40
    assert result["up"]["freeLongSeats"] == 0
    assert result["up"]["freeShortSeats"] == 1
    assert result["down"]["zone"] == -1
    assert round(result["down"]["distance"], 2) == 2.18
    assert result["down"]["freeShortSeats"] == 2
    assert _canonical_next_free_position_levels(zones, 311.45, reliable=False)["status"] == "UNAVAILABLE"
    assert _canonical_next_free_position_levels([], 311.45, reliable=True)["up"] is None
