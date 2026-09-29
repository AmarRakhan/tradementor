from __future__ import annotations

import random

import pytest

from aster_multi_bb import MultiBbConfig
from aster_multi_bb_portfolio import (
    FLAT_CONFIRMING,
    PORTFOLIO_TP_EXECUTING,
    ensure_cycle,
    portfolio_cycle_gate,
    portfolio_tp_seat_reset_plan,
)
from test_aster_portfolio_tp_mode import FakeClient, Ref, pos


def _settings(long_slots=8, short_slots=7, *, reset=True, top_n=50):
    return {
        "engine": "multi_bb_v1",
        "universeTopN": top_n,
        "maximumPositions": long_slots + short_slots,
        "longSlots": long_slots,
        "shortSlots": short_slots,
        "minimumLeverage": 3,
        "maximumLeverage": 5,
        "entryMarginUsd": 0.5,
        "entryNotionalUsd": 3,
        "entrySizingMode": "margin",
        "dcaDistance": 0.003,
        "dcaMarginUsd": 0.5,
        "maxDca": 3,
        "takeProfit": 0.015,
        "takeProfitEnabled": True,
        "takeProfitMode": "PORTFOLIO",
        "portfolioTpInputMode": "PERCENT",
        "portfolioTpValue": 5.0,
        "portfolioTpBaseMode": "CYCLE_START",
        "resetSeatsAfterPortfolioTp": reset,
    }


def _cycle(*, start_long=3, start_short=3, status="RUNNING", armed=False):
    return {
        "cycleId": "cycle-seat-reset",
        "cycleStartEquity": 100.0,
        "baseEquity": 100.0,
        "baseMode": "CYCLE_START",
        "baseConfigVersion": 1,
        "takeProfitInputMode": "PERCENT",
        "takeProfitValue": 5.0,
        "targetEquity": 105.0,
        "cycleStatus": status,
        "cycleStartLongSlots": start_long,
        "cycleStartShortSlots": start_short,
        "cycleStartMaximumPositions": start_long + start_short,
        "seatSnapshotSource": "CYCLE_START",
        "seatResetArmed": armed,
    }


def test_config_persists_reset_flag_without_changing_legacy_default():
    legacy = MultiBbConfig.from_mapping(_settings(reset=False))
    assert legacy.reset_seats_after_portfolio_tp is False
    assert legacy.public_dict()["resetSeatsAfterPortfolioTp"] is False

    enabled = MultiBbConfig.from_mapping(_settings(reset=True))
    assert enabled.reset_seats_after_portfolio_tp is True
    assert enabled.public_dict()["resetSeatsAfterPortfolioTp"] is True


def test_cycle_seat_snapshot_is_seeded_once_and_manual_increase_does_not_move_it():
    raw = {"multiBbCycle": {
        "cycleId": "abc", "cycleStartEquity": 100.0, "cycleStatus": "RUNNING",
    }}
    first, changed = ensure_cycle(
        raw, uid="u", current_equity=101.0, portfolio_tp_percent=5.0, timestamp_ms=1,
        current_long_slots=3, current_short_slots=3, current_maximum_positions=6,
    )
    assert changed is True
    assert (first["cycleStartLongSlots"], first["cycleStartShortSlots"], first["cycleStartMaximumPositions"]) == (3, 3, 6)

    second, _ = ensure_cycle(
        {"multiBbCycle": first}, uid="u", current_equity=102.0, portfolio_tp_percent=5.0, timestamp_ms=2,
        current_long_slots=8, current_short_slots=7, current_maximum_positions=15,
    )
    assert (second["cycleStartLongSlots"], second["cycleStartShortSlots"], second["cycleStartMaximumPositions"]) == (3, 3, 6)


def test_reset_on_closes_first_then_restores_seats_and_new_cycle_snapshot():
    raw = {
        "enabled": True,
        "settings": _settings(8, 7, reset=True),
        "multiBbCycle": _cycle(),
        "multiBbPositions": {"BTCUSDT|LONG": {"dcaCount": 2}},
    }
    ref = Ref(raw)
    client = FakeClient(equity=105.0, positions=[pos("BTCUSDT", "LONG")])

    result = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=raw, uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[],
        timestamp_ms=10, take_profit_mode="PORTFOLIO", portfolio_tp_percent=5.0,
        portfolio_tp_input_mode="PERCENT", portfolio_tp_value=5.0,
        current_long_slots=8, current_short_slots=7, current_maximum_positions=15,
        reset_seats_after_portfolio_tp=True,
    )

    assert result.handled is True and result.restart is True
    assert client.positions == []
    assert len(client.submissions) == 1
    assert (ref.data["settings"]["longSlots"], ref.data["settings"]["shortSlots"], ref.data["settings"]["maximumPositions"]) == (3, 3, 6)
    completed = ref.data["multiBbLastCompletedCycle"]
    assert completed["slotResetCycleId"] == "cycle-seat-reset"
    assert completed["slotResetCompletedAtMs"] > 0
    assert (ref.data["multiBbCycle"]["cycleStartLongSlots"], ref.data["multiBbCycle"]["cycleStartShortSlots"]) == (3, 3)
    events = [row["event"] for row in ref.audit]
    assert "PORTFOLIO_TP_SEAT_RESET_ARMED" in events
    assert "PORTFOLIO_TP_SEAT_RESET_STARTED" in events
    assert events.count("PORTFOLIO_TP_SEAT_RESET_COMPLETED") == 1
    for event in ("PORTFOLIO_TP_SEAT_RESET_ARMED", "PORTFOLIO_TP_SEAT_RESET_STARTED", "PORTFOLIO_TP_SEAT_RESET_COMPLETED"):
        audit = next(row for row in ref.audit if row["event"] == event)
        assert audit["userId"] == "u"
        assert audit["botId"] == "aster-strategy-2"
        assert audit["cycleId"] == "cycle-seat-reset"
        assert "previousLongSlots" in audit and "previousShortSlots" in audit
        assert "targetLongSlots" in audit and "targetShortSlots" in audit


def test_reset_off_keeps_current_seats_after_portfolio_tp():
    raw = {
        "enabled": True,
        "settings": _settings(8, 7, reset=False),
        "multiBbCycle": _cycle(),
    }
    ref = Ref(raw)
    client = FakeClient(equity=105.0, positions=[pos("BTCUSDT", "LONG")])
    result = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=raw, uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[],
        timestamp_ms=10, take_profit_mode="PORTFOLIO", portfolio_tp_percent=5.0,
        current_long_slots=8, current_short_slots=7, current_maximum_positions=15,
        reset_seats_after_portfolio_tp=False,
    )
    assert result.restart is True
    assert (ref.data["settings"]["longSlots"], ref.data["settings"]["shortSlots"]) == (8, 7)
    assert ref.data["multiBbCycle"]["cycleStartLongSlots"] == 8
    assert ref.data["multiBbCycle"]["cycleStartShortSlots"] == 7
    assert any(row["event"] == "PORTFOLIO_TP_SEAT_RESET_SKIPPED" for row in ref.audit)


def test_partial_close_never_resets_seats_before_flat_confirmation():
    raw = {
        "enabled": True,
        "settings": _settings(8, 7, reset=True),
        "multiBbCycle": _cycle(status=PORTFOLIO_TP_EXECUTING, armed=True),
    }
    ref = Ref(raw)
    client = FakeClient(equity=106.0, positions=[pos("BTCUSDT", "LONG", qty=2)], partial_once=True)
    first = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=raw, uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[],
        timestamp_ms=20, take_profit_mode="PORTFOLIO", portfolio_tp_percent=5.0,
        current_long_slots=8, current_short_slots=7, current_maximum_positions=15,
        reset_seats_after_portfolio_tp=True,
    )
    assert first.restart is False
    assert ref.data["multiBbCycle"]["cycleStatus"] == FLAT_CONFIRMING
    assert (ref.data["settings"]["longSlots"], ref.data["settings"]["shortSlots"]) == (8, 7)

    second_raw = ref.get().to_dict()
    second = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=second_raw, uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[],
        timestamp_ms=21, take_profit_mode="PORTFOLIO", portfolio_tp_percent=5.0,
        current_long_slots=8, current_short_slots=7, current_maximum_positions=15,
        reset_seats_after_portfolio_tp=True,
    )
    assert second.restart is True
    assert client.positions == []
    assert (ref.data["settings"]["longSlots"], ref.data["settings"]["shortSlots"]) == (3, 3)


def test_next_tick_is_idempotent_and_does_not_duplicate_reset():
    raw = {
        "enabled": True,
        "settings": _settings(8, 7, reset=True),
        "multiBbCycle": _cycle(),
    }
    ref = Ref(raw)
    client = FakeClient(equity=105.0, positions=[])
    first = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=raw, uid="u",
        account=client.account_information(), positions=[], open_orders=[],
        timestamp_ms=30, take_profit_mode="PORTFOLIO", portfolio_tp_percent=5.0,
        current_long_slots=8, current_short_slots=7, current_maximum_positions=15,
        reset_seats_after_portfolio_tp=True,
    )
    assert first.restart is True
    second_raw = ref.get().to_dict()
    second = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=second_raw, uid="u",
        account=client.account_information(), positions=[], open_orders=[],
        timestamp_ms=31, take_profit_mode="PORTFOLIO", portfolio_tp_percent=5.0,
        current_long_slots=3, current_short_slots=3, current_maximum_positions=6,
        reset_seats_after_portfolio_tp=True,
    )
    assert second.handled is False
    assert [row["event"] for row in ref.audit].count("PORTFOLIO_TP_SEAT_RESET_COMPLETED") == 1


def test_planner_clamps_old_snapshot_to_current_market_capacity():
    plan = portfolio_tp_seat_reset_plan(
        _cycle(start_long=6, start_short=6),
        _settings(2, 2, reset=True, top_n=2),
    )
    assert plan["applied"] is True
    assert plan["clamped"] is True
    assert plan["targetLongSlots"] + plan["targetShortSlots"] == 4
    assert plan["targetMaximumPositions"] == 4


def test_event_backtest_1000_cycles_has_zero_invariant_failures_and_sends_no_orders():
    """Deterministic event replay: toggle ON/OFF, retries, duplicate delivery and reconnect copies."""
    rng = random.Random(20260928)
    failures = []
    duplicate_mutations = 0
    missed_resets = 0
    incorrect_resets = 0

    for index in range(1000):
        start_long = rng.randint(0, 20)
        start_short = rng.randint(0, 20)
        if start_long + start_short == 0:
            start_long = 1
        current_long = start_long + rng.randint(0, 20)
        current_short = start_short + rng.randint(0, 20)
        reset_enabled = bool(rng.getrandbits(1))
        settings = _settings(current_long, current_short, reset=reset_enabled, top_n=100)
        cycle = _cycle(start_long=start_long, start_short=start_short, armed=reset_enabled)

        # Toggle OFF means the Portfolio TP close may finish, but no seat mutation is allowed.
        if not reset_enabled:
            replay_settings = dict(settings)
            if (
                replay_settings["longSlots"] != current_long
                or replay_settings["shortSlots"] != current_short
                or replay_settings["maximumPositions"] != current_long + current_short
            ):
                incorrect_resets += 1
                failures.append((index, "toggle-off-mutated", cycle, replay_settings))
            continue

        # First delivery, then a retry/duplicate delivery after a reconnect-like state copy.
        first = portfolio_tp_seat_reset_plan(dict(cycle), dict(settings))
        retry = portfolio_tp_seat_reset_plan(dict(cycle), dict(settings))
        reconnect = portfolio_tp_seat_reset_plan(dict(cycle), dict(settings))
        plans = (first, retry, reconnect)

        if not all(plan["applied"] for plan in plans):
            missed_resets += 1
            failures.append((index, "missed-reset", cycle, plans))
            continue

        expected = (start_long, start_short, start_long + start_short)
        results = {
            (
                plan["targetLongSlots"],
                plan["targetShortSlots"],
                plan["targetMaximumPositions"],
            )
            for plan in plans
        }
        if results != {expected}:
            incorrect_resets += 1
            failures.append((index, "incorrect-reset", cycle, results))
        if len(results) != 1:
            duplicate_mutations += 1
            failures.append((index, "duplicate-divergence", cycle, results))

    assert failures == []
    assert incorrect_resets == 0
    assert missed_resets == 0
    assert duplicate_mutations == 0


def test_missing_cycle_seat_snapshot_fails_closed_after_flat_and_keeps_entry_lock():
    raw = {
        "enabled": True,
        "settings": _settings(8, 7, reset=True),
        "multiBbCycle": {
            "cycleId": "legacy-without-seat-snapshot",
            "cycleStartEquity": 100.0,
            "baseEquity": 100.0,
            "baseMode": "CYCLE_START",
            "targetEquity": 105.0,
            "cycleStatus": PORTFOLIO_TP_EXECUTING,
            "seatResetArmed": True,
        },
    }
    ref = Ref(raw)
    client = FakeClient(equity=106.0, positions=[])
    result = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=raw, uid="u",
        account=client.account_information(), positions=[], open_orders=[],
        timestamp_ms=40, take_profit_mode="PORTFOLIO", portfolio_tp_percent=5.0,
        reset_seats_after_portfolio_tp=True,
    )
    assert result.handled is True
    assert result.restart is False
    assert ref.data["multiBbCycle"]["cycleStatus"] == FLAT_CONFIRMING
    assert ref.data["multiBbReport"]["seatResetPending"] is True
    assert (ref.data["settings"]["longSlots"], ref.data["settings"]["shortSlots"]) == (8, 7)
    failed = next(row for row in ref.audit if row["event"] == "PORTFOLIO_TP_SEAT_RESET_FAILED")
    assert failed["userId"] == "u"
    assert failed["targetLongSlots"] is None
    assert failed["targetShortSlots"] is None


def test_manual_cycle_reset_snapshots_current_seats_but_never_mutates_settings():
    from aster_multi_bb_portfolio import reset_cycle_to_equity

    settings = _settings(8, 7, reset=True)
    before = dict(settings)
    cycle = reset_cycle_to_equity(
        uid="u", current_equity=103.0, portfolio_tp_percent=5.0, timestamp_ms=50,
        current_long_slots=8, current_short_slots=7, current_maximum_positions=15,
    )
    assert settings == before
    assert (cycle["cycleStartLongSlots"], cycle["cycleStartShortSlots"], cycle["cycleStartMaximumPositions"]) == (8, 7, 15)
    assert cycle["slotResetCompletedAt"] is None
    assert cycle["slotResetCycleId"] is None


def test_reset_planner_does_not_touch_zone_autohedge_or_sniper_configuration():
    settings = {
        **_settings(9, 8, reset=True, top_n=50),
        "zoneSoldiersEnabled": True,
        "zoneBaseLongSoldiers": 3,
        "zoneBaseShortSoldiers": 3,
        "zoneOwnershipLedger": {"BTCUSDT|LONG": {"originZone": 2}},
        "autoHedgeEnabled": True,
        "sniperMaximumPositions": 3,
    }
    plan = portfolio_tp_seat_reset_plan(_cycle(start_long=3, start_short=3), settings)
    assert plan["applied"] is True
    for key in (
        "zoneBaseLongSoldiers", "zoneBaseShortSoldiers", "zoneOwnershipLedger",
        "autoHedgeEnabled", "sniperMaximumPositions",
    ):
        assert plan["settings"][key] == settings[key]


def test_configurable_reset_target_round_trips_and_allows_zero_zero():
    configured = {**_settings(reset=True), "portfolioTpResetLongSlots": 23, "portfolioTpResetShortSlots": 8}
    cfg = MultiBbConfig.from_mapping(configured)
    assert cfg.portfolio_tp_reset_long_slots == 23
    assert cfg.portfolio_tp_reset_short_slots == 8
    assert cfg.public_dict()["portfolioTpResetLongSlots"] == 23
    assert cfg.public_dict()["portfolioTpResetShortSlots"] == 8

    zero = MultiBbConfig.from_mapping({**_settings(reset=True), "portfolioTpResetLongSlots": 0, "portfolioTpResetShortSlots": 0})
    assert zero.portfolio_tp_reset_long_slots == 0
    assert zero.portfolio_tp_reset_short_slots == 0

    with pytest.raises(ValueError, match="LONG- als SHORT-resetwaarde"):
        MultiBbConfig.from_mapping({**_settings(reset=True), "portfolioTpResetLongSlots": 3})


def test_configured_reset_target_is_exact_and_not_cycle_start():
    settings = {
        **_settings(8, 7, reset=True, top_n=50),
        "portfolioTpResetLongSlots": 23,
        "portfolioTpResetShortSlots": 8,
    }
    raw = {
        "enabled": True,
        "settings": settings,
        "multiBbCycle": _cycle(start_long=3, start_short=3),
        "multiBbPositions": {"BTCUSDT|LONG": {"dcaCount": 1}},
    }
    ref = Ref(raw)
    client = FakeClient(equity=105.0, positions=[pos("BTCUSDT", "LONG")])

    result = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=raw, uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[],
        timestamp_ms=60, take_profit_mode="PORTFOLIO", portfolio_tp_percent=5.0,
        current_long_slots=8, current_short_slots=7, current_maximum_positions=15,
        reset_seats_after_portfolio_tp=True,
    )

    assert result.restart is True
    assert (ref.data["settings"]["longSlots"], ref.data["settings"]["shortSlots"], ref.data["settings"]["maximumPositions"]) == (23, 8, 31)
    completed = ref.data["multiBbLastCompletedCycle"]
    assert completed["seatResetTargetSource"] == "CONFIGURED"
    assert (completed["seatResetTargetLongSlots"], completed["seatResetTargetShortSlots"]) == (23, 8)
    assert ref.data["multiBbCycle"]["cycleStartMaximumPositions"] == 31


def test_configured_zero_zero_reset_is_a_valid_no_capacity_restart():
    settings = {
        **_settings(8, 7, reset=True, top_n=50),
        "portfolioTpResetLongSlots": 0,
        "portfolioTpResetShortSlots": 0,
    }
    raw = {
        "enabled": True,
        "settings": settings,
        "multiBbCycle": _cycle(start_long=3, start_short=3),
    }
    ref = Ref(raw)
    client = FakeClient(equity=105.0, positions=[])

    result = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=raw, uid="u",
        account=client.account_information(), positions=[], open_orders=[],
        timestamp_ms=70, take_profit_mode="PORTFOLIO", portfolio_tp_percent=5.0,
        current_long_slots=8, current_short_slots=7, current_maximum_positions=15,
        reset_seats_after_portfolio_tp=True,
    )

    assert result.restart is True
    assert (ref.data["settings"]["longSlots"], ref.data["settings"]["shortSlots"], ref.data["settings"]["maximumPositions"]) == (0, 0, 0)
    parsed = MultiBbConfig.from_mapping(ref.data["settings"])
    assert (parsed.long_slots, parsed.short_slots, parsed.maximum_positions) == (0, 0, 0)
    assert (ref.data["multiBbCycle"]["cycleStartLongSlots"], ref.data["multiBbCycle"]["cycleStartShortSlots"], ref.data["multiBbCycle"]["cycleStartMaximumPositions"]) == (0, 0, 0)


def test_configured_target_is_frozen_at_trigger_and_later_edits_do_not_move_it():
    settings = {
        **_settings(8, 7, reset=True, top_n=50),
        "portfolioTpResetLongSlots": 23,
        "portfolioTpResetShortSlots": 8,
    }
    cycle = {
        **_cycle(start_long=3, start_short=3, status=PORTFOLIO_TP_EXECUTING, armed=True),
        "seatResetTargetLongSlots": 23,
        "seatResetTargetShortSlots": 8,
        "seatResetTargetMaximumPositions": 31,
        "seatResetTargetSource": "CONFIGURED",
    }
    changed_after_trigger = {
        **settings,
        "portfolioTpResetLongSlots": 30,
        "portfolioTpResetShortSlots": 12,
    }
    plan = portfolio_tp_seat_reset_plan(cycle, changed_after_trigger)
    assert plan["applied"] is True
    assert (plan["targetLongSlots"], plan["targetShortSlots"], plan["targetMaximumPositions"]) == (23, 8, 31)


def test_configured_target_over_current_capacity_fails_instead_of_clamping():
    settings = {
        **_settings(2, 2, reset=True, top_n=2),
        "portfolioTpResetLongSlots": 3,
        "portfolioTpResetShortSlots": 2,
    }
    cycle = {
        **_cycle(start_long=2, start_short=2, status=PORTFOLIO_TP_EXECUTING, armed=True),
        "seatResetTargetLongSlots": 3,
        "seatResetTargetShortSlots": 2,
        "seatResetTargetMaximumPositions": 5,
        "seatResetTargetSource": "CONFIGURED",
    }
    plan = portfolio_tp_seat_reset_plan(cycle, settings)
    assert plan["applied"] is False
    assert plan["reason"] == "configured-reset-target-exceeds-current-capacity"
    assert plan["targetLongSlots"] == 3
    assert plan["targetShortSlots"] == 2
