from aster_state import (
    AsterAccountState, AsterLegState, AsterPairState, apply_exchange_event,
    reconcile_aster_state, state_from_mapping, state_to_mapping,
    infer_dca_level,
    account_information_values, dashboard_snapshot,
)


def test_dashboard_snapshot_uses_current_official_account_totals():
    snapshot = dashboard_snapshot({
        "totalMarginBalance": "407.28",
        "totalWalletBalance": "424.91",
        "availableBalance": "218.11",
        "totalUnrealizedProfit": "-17.63",
        "totalMaintMargin": "74.89",
    }, [{
        "symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "0.002",
        "entryPrice": "64000", "markPrice": "65000", "unRealizedProfit": "2", "leverage": "20",
        "positionInitialMargin": "6.50",
    }])
    assert snapshot["equity"] == 407.28
    assert snapshot["availableBalance"] == 218.11
    assert snapshot["activePositions"] == 1
    assert snapshot["positions"][0]["notionalUsd"] == 130.0
    assert snapshot["activeTradeCapital"] == 6.5
    assert snapshot["positions"][0]["initialMarginUsd"] == 6.5
    assert round(snapshot["positions"][0]["returnPct"], 6) == round(2 / 6.5 * 100, 6)
    assert snapshot["positions"][0]["dataSource"] == "ASTER_API"
    assert snapshot["financialDataContract"]["sourceOfTruth"] == "ASTER_API"
    assert snapshot["financialDataContract"]["positionDisplayReturnIsTakeProfitStatus"] is False
    assert round(snapshot["marginRatio"], 6) == round(74.89 / 407.28, 6)


def test_dashboard_snapshot_sums_only_active_exchange_reported_position_margin():
    snapshot = dashboard_snapshot({}, [
        {"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "1", "positionInitialMargin": "10"},
        {"symbol": "ETHUSDT", "positionSide": "SHORT", "positionAmt": "-2", "positionInitialMargin": "25.5"},
        {"symbol": "SOLUSDT", "positionSide": "LONG", "positionAmt": "0", "positionInitialMargin": "99"},
    ])
    assert snapshot["activeTradeCapital"] == 35.5

def test_dashboard_snapshot_falls_back_to_account_initial_margin_for_cross_positions():
    snapshot = dashboard_snapshot({"totalInitialMargin":"214.76"}, [
        {"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"1","initialMargin":"0"},
    ])
    assert snapshot["activeTradeCapital"] == 214.76


def position(symbol, side, amount, entry=100, leverage=10):
    return {
        "symbol": symbol, "positionSide": side, "positionAmt": amount,
        "entryPrice": entry, "leverage": leverage, "marginType": "cross",
    }


def test_long_and_short_are_preserved_as_independent_legs_of_same_pair():
    result = reconcile_aster_state(
        persisted=None,
        exchange_positions=[position("BTCUSDT", "LONG", 1), position("BTCUSDT", "SHORT", -2, entry=110)],
        exchange_open_orders=[], hedge_mode_confirmed=True, exchange_read_ok=True,
    )
    pair = result.state.pair("BTCUSDT")
    assert pair is not None
    assert pair.long.quantity == 1
    assert pair.short.quantity == 2
    assert pair.long.average_entry == 100
    assert pair.short.average_entry == 110


def test_exchange_discovery_requires_persistent_round_trip_before_new_risk():
    first = reconcile_aster_state(
        persisted=None, exchange_positions=[position("ETHUSDT", "LONG", 3)],
        exchange_open_orders=[], hedge_mode_confirmed=True, exchange_read_ok=True,
    )
    assert first.changed is True
    assert first.allow_risk_increase is False
    persisted_only = reconcile_aster_state(
        persisted=first.state, exchange_positions=[position("ETHUSDT", "LONG", 3)],
        exchange_open_orders=[], hedge_mode_confirmed=True, exchange_read_ok=True,
        round_trip_verified=True,
    )
    assert persisted_only.allow_risk_increase is False
    verified = reconcile_aster_state(
        persisted=first.state, exchange_positions=[position("ETHUSDT", "LONG", 3)],
        exchange_open_orders=[], hedge_mode_confirmed=True, exchange_read_ok=True,
        round_trip_verified=True, fills_reconciled=True,
    )
    assert verified.allow_risk_increase is True


def test_quantity_change_marks_metadata_for_fill_rebuild_and_blocks_risk():
    persisted = AsterAccountState(1, True, (
        AsterPairState("BTCUSDT", AsterLegState("LONG", 1, 100, 10, "cross", 2), AsterLegState("SHORT")),
    ))
    result = reconcile_aster_state(
        persisted=persisted, exchange_positions=[position("BTCUSDT", "LONG", 2, entry=95)],
        exchange_open_orders=[], hedge_mode_confirmed=True, exchange_read_ok=True,
        round_trip_verified=True,
    )
    assert result.state.pair("BTCUSDT").metadata_needs_rebuild is True
    assert result.state.pair("BTCUSDT").long.dca_level == 0
    assert result.allow_risk_increase is False


def test_exchange_flat_removes_ghost_pair_after_successful_read():
    persisted = AsterAccountState(1, True, (
        AsterPairState("SOLUSDT", AsterLegState("LONG", 1, 100), AsterLegState("SHORT")),
    ))
    result = reconcile_aster_state(
        persisted=persisted, exchange_positions=[], exchange_open_orders=[],
        hedge_mode_confirmed=True, exchange_read_ok=True,
    )
    assert result.state.pairs == ()
    assert result.allow_risk_increase is False


def test_failed_exchange_read_never_erases_persisted_state():
    persisted = AsterAccountState(1, True, (
        AsterPairState("SOLUSDT", AsterLegState("LONG", 1, 100), AsterLegState("SHORT")),
    ))
    result = reconcile_aster_state(
        persisted=persisted, exchange_positions=[], exchange_open_orders=[],
        hedge_mode_confirmed=True, exchange_read_ok=False,
    )
    assert result.state == persisted
    assert result.allow_risk_increase is False


def test_out_of_order_event_cannot_move_stream_cursor_backwards():
    pair = AsterPairState("BTCUSDT", AsterLegState("LONG"), AsterLegState("SHORT"), last_exchange_event_ms=1000)
    assert apply_exchange_event(pair, {"E": 999}).last_exchange_event_ms == 1000
    assert apply_exchange_event(pair, {"E": 1001}).last_exchange_event_ms == 1001


def test_state_mapping_round_trip_preserves_risk_relevant_fields():
    original = AsterAccountState(1, True, (
        AsterPairState("BTCUSDT", AsterLegState("LONG", .1, 100, 200, "cross", 2),
                       AsterLegState("SHORT", .1, 101, 200, "cross", 1), ("order-1",), 123, False),
    ))
    assert state_from_mapping(state_to_mapping(original)) == original


def test_lost_dca_level_is_rebuilt_only_from_matching_ladder_notional():
    assert infer_dca_level(10.4,10,1,3)==0
    assert infer_dca_level(20,10,1,3)==1
    assert infer_dca_level(30,10,1,3)==2
    assert infer_dca_level(16.8,10,1,3) is None


def test_account_information_uses_exchange_authoritative_maintenance_totals():
    values = account_information_values({
        "totalMarginBalance": "117.50", "totalWalletBalance": "120.00",
        "availableBalance": "91.25", "totalUnrealizedProfit": "-2.50",
        "totalMaintMargin": "1.175",
    })
    assert values == (117.5, 120.0, 91.25, -2.5, 1.175)
