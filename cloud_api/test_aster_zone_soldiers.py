from __future__ import annotations

from aster_zone_soldiers import (
    ROLE_EXPOSURE_BALANCER,
    ROLE_LEGACY_UNASSIGNED,
    ROLE_ZONE_BASE,
    STATUS_AVAILABLE,
    STATUS_DORMANT,
    STATUS_OPEN,
    annotate_legacy_positions,
    available_soldiers,
    claim_soldier,
    prepare_zone_runtime,
    record_soldier_homecoming,
)


def pos(symbol: str, side: str, notional: float, qty: float = 1.0) -> dict:
    mark = notional / qty
    return {
        "symbol": symbol,
        "positionSide": side,
        "positionAmt": str(qty),
        "entryPrice": str(mark),
        "markPrice": str(mark),
    }


def owned(symbol: str, side: str, **extra) -> tuple[str, dict]:
    key = f"{symbol}|{side}"
    return key, {
        "cycleId": f"cycle-{symbol}-{side}",
        "cycleStartedAtMs": 1_000,
        "botManaged": True,
        **extra,
    }


def prepare(raw, managed, positions, zone, *, safe=True, at=10_000, base_long=3, base_short=3,
            balancer=True, trigger=20.0, release=8.0, unit=100.0):
    return prepare_zone_runtime(
        raw_zone_state=raw,
        managed_state=managed,
        positions=positions,
        confirmed_zone=zone,
        zone_safe=safe,
        base_long=base_long,
        base_short=base_short,
        balancer_enabled=balancer,
        trigger_percent=trigger,
        release_percent=release,
        fallback_unit_notional=unit,
        timestamp_ms=at,
    )


def test_z0_activates_own_long_and_short_pool():
    state, managed, report = prepare({}, {}, [], 0, balancer=False)
    assert report["activeZone"] == 0
    assert len(available_soldiers(state, "LONG")) == 3
    assert len(available_soldiers(state, "SHORT")) == 3
    assert report["zoneFormation"] == {"baseLongSoldiers": 3, "baseShortSoldiers": 3}


def test_zone_transition_deactivates_only_new_entries_from_previous_zone():
    z0, managed, _ = prepare({}, {}, [], 0, balancer=False)
    z1, managed, report = prepare(z0, managed, [], 1, balancer=False, at=20_000)
    old = z1["pools"]["0"]["soldiers"]
    assert all(row["status"] == STATUS_DORMANT for row in old.values())
    assert len(available_soldiers(z1, "LONG")) == 3
    assert len(available_soldiers(z1, "SHORT")) == 3
    assert report["previousZone"] == 0


def test_open_old_zone_trade_survives_zone_change_and_keeps_origin():
    z0, managed, _ = prepare({}, {}, [], 0, balancer=False)
    soldier = claim_soldier(z0, "LONG", trade_key="BTCUSDT|LONG", symbol="BTCUSDT",
                            entry_price=100, entry_portfolio_equity=145, timestamp_ms=11_000)
    managed = {
        "BTCUSDT|LONG": {
            "cycleId": "c1", "cycleStartedAtMs": 11_000, "botManaged": True,
            "originZone": 0, "originZoneCycleId": soldier["originZoneCycleId"],
            "soldierId": soldier["soldierId"], "soldierRole": ROLE_ZONE_BASE,
            "soldierStatus": STATUS_OPEN, "entryPortfolioEquity": 145,
        }
    }
    z1, managed, report = prepare(z0, managed, [pos("BTCUSDT", "LONG", 100)], 1, balancer=False, at=20_000)
    row = z1["pools"]["0"]["soldiers"][soldier["soldierId"]]
    assert row["status"] == STATUS_OPEN
    assert managed["BTCUSDT|LONG"]["originZone"] == 0
    assert report["oldZonesOpen"]["long"] == 1


def test_closed_old_zone_trade_becomes_dormant():
    z0, managed, _ = prepare({}, {}, [], 0, balancer=False)
    soldier = claim_soldier(z0, "SHORT", trade_key="ETHUSDT|SHORT", symbol="ETHUSDT",
                            entry_price=100, entry_portfolio_equity=145, timestamp_ms=11_000)
    managed = {
        "ETHUSDT|SHORT": {
            "originZone": 0, "originZoneCycleId": soldier["originZoneCycleId"],
            "soldierId": soldier["soldierId"], "soldierRole": ROLE_ZONE_BASE,
            "soldierStatus": STATUS_OPEN,
        }
    }
    z1, _, _ = prepare(z0, {}, [], 1, balancer=False, at=20_000)
    row = z1["pools"]["0"]["soldiers"][soldier["soldierId"]]
    assert row["status"] == STATUS_DORMANT


def test_new_zone_gets_full_base_formation_even_with_old_open_trades():
    z0, managed, _ = prepare({}, {}, [], 0, balancer=False)
    soldier = claim_soldier(z0, "LONG", trade_key="BTCUSDT|LONG", symbol="BTCUSDT",
                            entry_price=100, entry_portfolio_equity=145, timestamp_ms=11_000)
    managed = {
        "BTCUSDT|LONG": {
            "originZone": 0, "originZoneCycleId": soldier["originZoneCycleId"],
            "soldierId": soldier["soldierId"], "soldierRole": ROLE_ZONE_BASE,
        }
    }
    z1, _, report = prepare(z0, managed, [pos("BTCUSDT", "LONG", 100)], 1, balancer=False, at=20_000)
    assert report["currentZone"]["freeLong"] == 3
    assert report["currentZone"]["freeShort"] == 3


def test_second_higher_zone_gets_own_pool_without_mutating_old_pool():
    z0, managed, _ = prepare({}, {}, [], 0, balancer=False)
    z1, managed, _ = prepare(z0, managed, [], 1, balancer=False, at=20_000)
    z2, managed, report = prepare(z1, managed, [], 2, balancer=False, at=30_000)
    assert set(z2["pools"]) == {"0", "1", "2"}
    assert report["activeZone"] == 2
    assert len(available_soldiers(z2, "LONG")) == 3
    assert len(available_soldiers(z2, "SHORT")) == 3


def test_return_to_existing_zone_reuses_pool_without_duplication():
    z0, managed, _ = prepare({}, {}, [], 0, balancer=False)
    z1, managed, _ = prepare(z0, managed, [], 1, balancer=False, at=20_000)
    ids_before = set(z1["pools"]["0"]["soldiers"])
    back, _, _ = prepare(z1, managed, [], 0, balancer=False, at=30_000)
    assert set(back["pools"]["0"]["soldiers"]) == ids_before
    assert len(back["pools"]["0"]["soldiers"]) == 6
    assert back["pools"]["0"]["activationCount"] == 2


def test_multiple_zone_positions_are_aggregated_into_managed_exposure():
    managed = dict([
        owned("A", "LONG", soldierRole=ROLE_LEGACY_UNASSIGNED),
        owned("B", "LONG", soldierRole=ROLE_LEGACY_UNASSIGNED),
        owned("C", "SHORT", soldierRole=ROLE_LEGACY_UNASSIGNED),
    ])
    _, _, report = prepare({}, managed, [pos("A", "LONG", 120), pos("B", "LONG", 80), pos("C", "SHORT", 100)], 0, balancer=False)
    assert report["exposure"]["totalLongOpenCount"] == 2
    assert report["exposure"]["totalShortOpenCount"] == 1
    assert report["exposure"]["totalLongNotional"] == 200
    assert report["exposure"]["totalShortNotional"] == 100


def test_long_overexposure_sets_short_priority_without_creating_extra_capacity():
    managed = dict([
        owned("A", "LONG", soldierRole=ROLE_LEGACY_UNASSIGNED),
        owned("B", "LONG", soldierRole=ROLE_LEGACY_UNASSIGNED),
        owned("C", "SHORT", soldierRole=ROLE_LEGACY_UNASSIGNED),
    ])
    state, _, report = prepare({}, managed, [pos("A", "LONG", 150), pos("B", "LONG", 150), pos("C", "SHORT", 100)], 1)
    assert report["entryPriority"] == "SHORT"
    assert report["balancer"]["mode"] == "PRIORITY_ONLY"
    assert report["balancer"]["desiredCount"] == 0
    assert report["currentZone"]["balancerFree"] == 0
    assert len(available_soldiers(state, "LONG")) == 3
    assert len(available_soldiers(state, "SHORT")) == 3
    assert all(row["role"] == ROLE_ZONE_BASE for row in available_soldiers(state, "SHORT"))

def test_short_overexposure_sets_long_priority_symmetrically_without_extra_capacity():
    managed = dict([
        owned("A", "SHORT", soldierRole=ROLE_LEGACY_UNASSIGNED),
        owned("B", "SHORT", soldierRole=ROLE_LEGACY_UNASSIGNED),
        owned("C", "LONG", soldierRole=ROLE_LEGACY_UNASSIGNED),
    ])
    state, _, report = prepare({}, managed, [pos("A", "SHORT", 150), pos("B", "SHORT", 150), pos("C", "LONG", 100)], -1)
    assert report["entryPriority"] == "LONG"
    assert report["balancer"]["desiredCount"] == 0
    assert len(available_soldiers(state, "LONG")) == 3
    assert len(available_soldiers(state, "SHORT")) == 3

def test_dead_band_releases_balancer_without_closing_open_balancer_trade():
    z0, managed, _ = prepare({}, {}, [], 0, balancer=False)
    # A balancer that is OPEN is preserved even when the target later becomes balanced.
    pool = z0["pools"]["0"]
    soldier = {
        "soldierId": "z0:short:bal:1", "side": "SHORT", "role": ROLE_EXPOSURE_BALANCER,
        "status": STATUS_OPEN, "originZone": 0, "originZoneCycleId": pool["originZoneCycleId"],
        "tradeKey": "B|SHORT", "symbol": "B", "openedAtMs": 10_000,
        "entryPrice": 100, "entryPortfolioEquity": 145, "updatedAtMs": 10_000,
    }
    pool["soldiers"][soldier["soldierId"]] = soldier
    managed = {
        "A|LONG": dict(owned("A", "LONG", soldierRole=ROLE_LEGACY_UNASSIGNED)[1]),
        "B|SHORT": {
            "soldierRole": ROLE_EXPOSURE_BALANCER, "soldierId": soldier["soldierId"],
            "originZone": 0, "originZoneCycleId": pool["originZoneCycleId"],
        },
    }
    next_state, _, report = prepare(z0, managed, [pos("A", "LONG", 100), pos("B", "SHORT", 100)], 0, at=20_000)
    assert report["balancer"]["activeSide"] is None
    assert next_state["pools"]["0"]["soldiers"][soldier["soldierId"]]["status"] == STATUS_OPEN


def test_dca_metadata_does_not_change_origin_zone():
    managed = {
        "BTCUSDT|LONG": {
            "originZone": -1, "originZoneCycleId": "zone-cycle",
            "soldierId": "n1:long:base:1", "soldierRole": ROLE_ZONE_BASE,
            "dcaCount": 4, "lastDcaFillPrice": 99.0,
        }
    }
    raw = {
        "activeZone": -1,
        "pools": {
            "-1": {
                "zone": -1, "originZoneCycleId": "zone-cycle", "createdAtMs": 1,
                "soldiers": {
                    "n1:long:base:1": {
                        "soldierId": "n1:long:base:1", "side": "LONG", "role": ROLE_ZONE_BASE,
                        "status": STATUS_OPEN, "originZone": -1, "originZoneCycleId": "zone-cycle",
                        "tradeKey": "BTCUSDT|LONG",
                    }
                },
            }
        },
    }
    _, next_managed, _ = prepare(raw, managed, [pos("BTCUSDT", "LONG", 100)], -1)
    assert next_managed["BTCUSDT|LONG"]["originZone"] == -1
    assert next_managed["BTCUSDT|LONG"]["soldierId"] == "n1:long:base:1"


def test_active_zone_close_releases_soldier_back_to_available():
    z0, _, _ = prepare({}, {}, [], 0, balancer=False)
    soldier = claim_soldier(z0, "LONG", trade_key="A|LONG", symbol="A", entry_price=100, entry_portfolio_equity=145, timestamp_ms=11_000)
    z0["pools"]["0"]["soldiers"][soldier["soldierId"]]["status"] = STATUS_OPEN
    next_state, _, _ = prepare(z0, {}, [], 0, balancer=False, at=20_000)
    assert next_state["pools"]["0"]["soldiers"][soldier["soldierId"]]["status"] == STATUS_AVAILABLE


def test_inactive_zone_close_releases_soldier_to_dormant():
    z0, _, _ = prepare({}, {}, [], 0, balancer=False)
    soldier = claim_soldier(z0, "LONG", trade_key="A|LONG", symbol="A", entry_price=100, entry_portfolio_equity=145, timestamp_ms=11_000)
    z1, _, _ = prepare(z0, {}, [], 1, balancer=False, at=20_000)
    assert z1["pools"]["0"]["soldiers"][soldier["soldierId"]]["status"] == STATUS_DORMANT


def test_history_gap_fails_closed_for_new_entries_but_keeps_open_soldier():
    z0, managed, _ = prepare({}, {}, [], 0, balancer=False)
    soldier = claim_soldier(z0, "LONG", trade_key="A|LONG", symbol="A", entry_price=100, entry_portfolio_equity=145, timestamp_ms=11_000)
    managed = {
        "A|LONG": {
            "originZone": 0, "originZoneCycleId": soldier["originZoneCycleId"],
            "soldierId": soldier["soldierId"], "soldierRole": ROLE_ZONE_BASE,
        }
    }
    blocked, _, report = prepare(z0, managed, [pos("A", "LONG", 100)], 1, safe=False, at=20_000)
    assert report["safeForNewEntries"] is False
    assert available_soldiers(blocked, "LONG") == []
    assert blocked["pools"]["0"]["soldiers"][soldier["soldierId"]]["status"] == STATUS_OPEN


def test_restart_recovery_is_idempotent_and_does_not_duplicate_pool_soldiers():
    first, managed, _ = prepare({}, {}, [], -1, balancer=False)
    second, managed, _ = prepare(first, managed, [], -1, balancer=False, at=20_000)
    third, _, _ = prepare(second, managed, [], -1, balancer=False, at=30_000)
    assert len(third["pools"]["-1"]["soldiers"]) == 6
    assert third["pools"]["-1"]["activationCount"] == 1


def test_legacy_positions_are_marked_unassigned_and_count_exposure_without_zone_guess():
    source = {"A|LONG": {"cycleId": "old", "botManaged": True}}
    migrated, count = annotate_legacy_positions(source, timestamp_ms=10_000)
    assert count == 1
    assert migrated["A|LONG"]["soldierRole"] == ROLE_LEGACY_UNASSIGNED
    assert migrated["A|LONG"]["originZone"] is None
    _, _, report = prepare({}, migrated, [pos("A", "LONG", 100)], 0, balancer=False)
    assert report["legacyUnassignedOpenCount"] == 1
    assert report["exposure"]["totalLongNotional"] == 100


def test_long_short_base_pool_is_symmetric():
    state, _, report = prepare({}, {}, [], -2, base_long=4, base_short=4, balancer=False)
    assert report["zoneFormation"]["baseLongSoldiers"] == 4
    assert report["zoneFormation"]["baseShortSoldiers"] == 4
    assert len(available_soldiers(state, "LONG")) == 4
    assert len(available_soldiers(state, "SHORT")) == 4


def test_zone_switches_do_not_create_global_seat_ratchet():
    state = {}
    managed = {}
    for index, zone in enumerate([0, 1, 2, 1, 0, -1, -2, -1, 0], start=1):
        state, managed, report = prepare(state, managed, [], zone, balancer=False, at=index * 10_000)
        assert len(available_soldiers(state, "LONG")) == 3
        assert len(available_soldiers(state, "SHORT")) == 3
    assert report["poolCount"] == 5
    assert sum(
        1 for pool in state["pools"].values() for soldier in pool["soldiers"].values()
        if soldier["status"] == STATUS_AVAILABLE
    ) == 6


def test_revisit_same_zone_never_creates_second_base_pool():
    state, managed, _ = prepare({}, {}, [], 1, balancer=False)
    initial_ids = set(state["pools"]["1"]["soldiers"])
    for at in (20_000, 30_000, 40_000):
        state, managed, _ = prepare(state, managed, [], 1, balancer=False, at=at)
    assert set(state["pools"]["1"]["soldiers"]) == initial_ids
    assert state["pools"]["1"]["activationCount"] == 1


def test_claimed_soldier_carries_persistent_zone_ownership_fields():
    state, _, _ = prepare({}, {}, [], -1, balancer=False)
    soldier = claim_soldier(state, "SHORT", trade_key="SOLUSDT|SHORT", symbol="SOLUSDT",
                            entry_price=200, entry_portfolio_equity=146.2, timestamp_ms=50_000)
    assert soldier["originZone"] == -1
    assert soldier["originZoneCycleId"]
    assert soldier["soldierId"].startswith("n1:short:base:")
    assert soldier["role"] == ROLE_ZONE_BASE
    assert soldier["status"] == STATUS_OPEN
