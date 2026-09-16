from decimal import Decimal

from profit_sweep_transfer import (
    deterministic_transfer_id,
    margin_decision,
    reconstruct_closed_cycles,
    sweep_amount_for_cycle,
)


def test_complete_long_cycle_sweeps_only_net_profit_after_fees_and_negative_funding():
    fills = [
        {"id": "open", "orderId": "o1", "symbol": "BTCUSDT", "positionSide": "LONG", "side": "BUY", "qty": "1", "commission": "0.10", "commissionAsset": "USDT", "time": 1000},
        {"id": "close", "orderId": "o2", "symbol": "BTCUSDT", "positionSide": "LONG", "side": "SELL", "qty": "1", "realizedPnl": "4.00", "commission": "0.10", "commissionAsset": "USDT", "time": 2000},
    ]
    income = [
        {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE", "income": "-0.20", "asset": "USDT", "time": 1500},
        {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE", "income": "0.50", "asset": "USDT", "time": 1600},
    ]
    events = reconstruct_closed_cycles(fills, income, armed_at_ms=500)
    assert len(events) == 1
    event = events[0]
    assert event.reliable is True
    assert event.gross_realized_profit == Decimal("4.00")
    assert event.proven_costs == Decimal("0.40")
    assert event.net_realized_profit == Decimal("3.60")
    assert sweep_amount_for_cycle(event, 25) == Decimal("0.90000000")


def test_short_cycle_is_supported_and_loss_never_sweeps():
    fills = [
        {"id": "1", "symbol": "ETHUSDT", "positionSide": "SHORT", "side": "SELL", "qty": "2", "commission": "0.02", "commissionAsset": "USDT", "time": 1000},
        {"id": "2", "symbol": "ETHUSDT", "positionSide": "SHORT", "side": "BUY", "qty": "2", "realizedPnl": "-1", "commission": "0.02", "commissionAsset": "USDT", "time": 2000},
    ]
    event = reconstruct_closed_cycles(fills, [], armed_at_ms=500)[0]
    assert event.net_realized_profit == Decimal("-1.04")
    assert sweep_amount_for_cycle(event, 50) == Decimal("0")


def test_partial_close_does_not_create_booking_until_position_is_fully_flat():
    fills = [
        {"id": "1", "symbol": "SOLUSDT", "positionSide": "LONG", "side": "BUY", "qty": "10", "commission": "0", "commissionAsset": "USDT", "time": 1000},
        {"id": "2", "symbol": "SOLUSDT", "positionSide": "LONG", "side": "SELL", "qty": "4", "realizedPnl": "1", "commission": "0", "commissionAsset": "USDT", "time": 2000},
    ]
    assert reconstruct_closed_cycles(fills, [], armed_at_ms=500) == []
    fills.append({"id": "3", "symbol": "SOLUSDT", "positionSide": "LONG", "side": "SELL", "qty": "6", "realizedPnl": "2", "commission": "0", "commissionAsset": "USDT", "time": 3000})
    events = reconstruct_closed_cycles(fills, [], armed_at_ms=500)
    assert len(events) == 1
    assert events[0].gross_realized_profit == Decimal("3")


def test_missing_opening_fill_fails_closed_instead_of_guessing_principal():
    fills = [
        {"id": "close", "symbol": "XRPUSDT", "positionSide": "LONG", "side": "SELL", "qty": "100", "realizedPnl": "5", "commission": "0.1", "commissionAsset": "USDT", "time": 2000},
    ]
    assert reconstruct_closed_cycles(fills, [], armed_at_ms=500) == []


def test_non_settlement_commission_makes_cycle_unreliable_and_unsweepable():
    fills = [
        {"id": "1", "symbol": "BTCUSDT", "positionSide": "LONG", "side": "BUY", "qty": "1", "commission": "0.001", "commissionAsset": "BNB", "time": 1000},
        {"id": "2", "symbol": "BTCUSDT", "positionSide": "LONG", "side": "SELL", "qty": "1", "realizedPnl": "10", "commission": "0.1", "commissionAsset": "USDT", "time": 2000},
    ]
    event = reconstruct_closed_cycles(fills, [], armed_at_ms=500)[0]
    assert event.reliable is False
    assert sweep_amount_for_cycle(event, 25) == Decimal("0")


def test_pre_arm_closure_is_never_retroactively_swept():
    fills = [
        {"id": "1", "symbol": "BTCUSDT", "positionSide": "LONG", "side": "BUY", "qty": "1", "commission": "0", "commissionAsset": "USDT", "time": 1000},
        {"id": "2", "symbol": "BTCUSDT", "positionSide": "LONG", "side": "SELL", "qty": "1", "realizedPnl": "10", "commission": "0", "commissionAsset": "USDT", "time": 2000},
    ]
    assert reconstruct_closed_cycles(fills, [], armed_at_ms=2500) == []


def test_transfer_id_is_stable_for_same_user_and_closure():
    first = deterministic_transfer_id("u1", "close-1")
    assert first == deterministic_transfer_id("u1", "close-1")
    assert first != deterministic_transfer_id("u1", "close-2")
    assert first.startswith("tmps-")


def test_margin_gate_preserves_largest_required_reserve():
    blocked = margin_decision(
        contribution="5", available_balance="20", maintenance_margin="3",
        emergency_trigger_reserve="16", protection_reserve="10", release_rehedge_reserve="12",
    )
    assert blocked.allowed is False
    assert blocked.required_remaining == Decimal("16")
    allowed = margin_decision(
        contribution="3", available_balance="20", maintenance_margin="3",
        emergency_trigger_reserve="16", protection_reserve="10", release_rehedge_reserve="12",
    )
    assert allowed.allowed is True
    assert allowed.available_after == Decimal("17")
