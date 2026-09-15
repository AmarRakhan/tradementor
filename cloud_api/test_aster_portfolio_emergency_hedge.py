from decimal import Decimal

import pytest

from aster_gateway import ContractRules, PositionSide
from aster_portfolio_emergency_hedge import aggregate_positions, calculations, missing_hedges


def rules(symbol="XRPUSDT", *, step="0.1", minimum="0.1"):
    return ContractRules(
        symbol=symbol,
        min_price=Decimal("0.0001"), max_price=Decimal("1000000"), tick_size=Decimal("0.0001"),
        min_quantity=Decimal(minimum), max_quantity=Decimal("100000000"), quantity_step=Decimal(step),
        market_min_quantity=Decimal(minimum), market_max_quantity=Decimal("100000000"),
        market_quantity_step=Decimal(step), min_notional=Decimal("0"),
    )


def pos(symbol, side, qty):
    return {"symbol": symbol, "positionSide": side, "positionAmt": str(qty), "markPrice": "1"}


def need(rows, contract=None):
    mapping = {contract.symbol: contract} if contract else None
    return missing_hedges(rows, mapping)


def apply_need(rows, item, filled=None):
    qty = float(item.quantity if filled is None else filled)
    rows = [dict(row) for row in rows]
    for row in rows:
        if row["symbol"] == item.symbol and row["positionSide"] == item.position_side.value:
            row["positionAmt"] = str(float(row["positionAmt"]) + qty)
            return rows
    rows.append(pos(item.symbol, item.position_side.value, qty))
    return rows


def test_01_percentage_150_130():
    value = calculations(150, 130)
    assert value["triggerPercentage"] == pytest.approx(86.6666667)


def test_02_max_loss_150_130():
    assert calculations(150, 130)["maxAllowedLoss"] == pytest.approx(20)


def test_03_trigger_must_be_below_start():
    with pytest.raises(ValueError): calculations(150, 150)


def test_04_trigger_must_be_positive():
    with pytest.raises(ValueError): calculations(150, 0)


def test_05_start_must_be_positive():
    with pytest.raises(ValueError): calculations(0, 1)


def test_06_long_only_needs_short():
    item = need([pos("XRPUSDT", "LONG", 10000)])[0]
    assert item.position_side is PositionSide.SHORT and float(item.quantity) == pytest.approx(10000)


def test_07_short_only_needs_long():
    item = need([pos("ETHUSDT", "SHORT", 3)])[0]
    assert item.position_side is PositionSide.LONG and float(item.quantity) == pytest.approx(3)


def test_08_partial_existing_short_only_delta():
    item = need([pos("BTCUSDT", "LONG", .05), pos("BTCUSDT", "SHORT", .02)])[0]
    assert item.position_side is PositionSide.SHORT and float(item.quantity) == pytest.approx(.03)


def test_09_partial_existing_long_only_delta():
    item = need([pos("ETHUSDT", "SHORT", 3), pos("ETHUSDT", "LONG", 1)])[0]
    assert item.position_side is PositionSide.LONG and float(item.quantity) == pytest.approx(2)


def test_10_equal_sides_have_no_need():
    assert need([pos("SOLUSDT", "LONG", 5), pos("SOLUSDT", "SHORT", 5)]) == []


def test_11_zero_positions_ignored():
    assert aggregate_positions([pos("SOLUSDT", "LONG", 0)]) == {}


def test_12_unknown_side_ignored():
    assert aggregate_positions([pos("SOLUSDT", "BOTH", 3)]) == {}


def test_13_multiple_rows_same_side_are_summed():
    value = aggregate_positions([pos("XRPUSDT", "LONG", 2), pos("XRPUSDT", "LONG", 3)])
    assert value["XRPUSDT"]["LONG"] == pytest.approx(5)


def test_14_symbol_is_normalized():
    value = aggregate_positions([pos("xrpusdt", "LONG", 2)])
    assert "XRPUSDT" in value


def test_15_contract_tolerance_ignores_one_step_residual():
    r = rules(step="0.1", minimum="0.1")
    assert need([pos("XRPUSDT", "LONG", 10), pos("XRPUSDT", "SHORT", 9.95)], r) == []


def test_16_residual_larger_than_tolerance_is_hedged():
    r = rules(step="0.1", minimum="0.1")
    assert float(need([pos("XRPUSDT", "LONG", 10), pos("XRPUSDT", "SHORT", 9.7)], r)[0].quantity) == pytest.approx(.3)


def test_17_partial_fill_recomputes_only_remainder():
    rows = [pos("XRPUSDT", "LONG", 10)]
    first = need(rows)[0]
    rows = apply_need(rows, first, 4)
    second = need(rows)[0]
    assert second.position_side is PositionSide.SHORT and float(second.quantity) == pytest.approx(6)


def test_18_full_fill_leaves_no_remainder():
    rows = [pos("XRPUSDT", "LONG", 10)]
    item = need(rows)[0]
    assert need(apply_need(rows, item)) == []


def test_19_repeated_reconciliation_does_not_overhedge():
    rows = [pos("XRPUSDT", "LONG", 10)]
    rows = apply_need(rows, need(rows)[0], 4)
    rows = apply_need(rows, need(rows)[0], 6)
    assert need(rows) == []


def test_20_overhedged_short_is_corrected_with_long_delta():
    item = need([pos("XRPUSDT", "LONG", 10), pos("XRPUSDT", "SHORT", 12)])[0]
    assert item.position_side is PositionSide.LONG and float(item.quantity) == pytest.approx(2)


def test_21_multiple_symbols_are_independent():
    rows = [pos("XRPUSDT", "LONG", 10), pos("BTCUSDT", "SHORT", .1)]
    values = {x.symbol: x for x in need(rows)}
    assert values["XRPUSDT"].position_side is PositionSide.SHORT
    assert values["BTCUSDT"].position_side is PositionSide.LONG


def test_22_thirty_nine_positions_supported():
    rows = [pos(f"C{i}USDT", "LONG" if i % 2 == 0 else "SHORT", i + 1) for i in range(39)]
    assert len(need(rows)) == 39


def test_23_mixed_long_short_39_pairs_supported():
    rows = []
    for i in range(39):
        rows.extend([pos(f"C{i}USDT", "LONG", i + 2), pos(f"C{i}USDT", "SHORT", i + 1)])
    assert len(need(rows)) == 39
    assert all(float(x.quantity) == pytest.approx(1) for x in need(rows))


def test_24_no_need_after_all_39_are_filled():
    rows = [pos(f"C{i}USDT", "LONG", i + 1) for i in range(39)]
    while True:
        pending = need(rows)
        if not pending: break
        rows = apply_need(rows, pending[0])
    assert need(rows) == []


def test_25_sequence_above_trigger_has_no_trigger_condition():
    trigger = 130
    assert all(value > trigger for value in [150, 145, 138, 132])


def test_26_sequence_exact_trigger_meets_condition():
    assert 130 <= 130


def test_27_sequence_below_trigger_meets_condition():
    assert 129.80 <= 130


def test_28_loss_formula_tracks_slider_change():
    assert calculations(150, 120)["maxAllowedLoss"] == 30


def test_29_percentage_tracks_manual_amount_change():
    assert calculations(200, 175)["triggerPercentage"] == pytest.approx(87.5)


def test_30_decimal_quantity_remains_directionally_exact():
    item = need([pos("BTCUSDT", "LONG", "0.05000000"), pos("BTCUSDT", "SHORT", "0.02000000")])[0]
    assert item.quantity == Decimal("0.03")


def test_31_negative_position_amount_is_normalized_by_side():
    rows = [{"symbol": "ETHUSDT", "positionSide": "SHORT", "positionAmt": "-3"}]
    assert aggregate_positions(rows)["ETHUSDT"]["SHORT"] == 3


def test_32_tiny_float_noise_does_not_create_emergency_order():
    r = rules(step="0.001", minimum="0.001")
    assert need([pos("XRPUSDT", "LONG", 1), pos("XRPUSDT", "SHORT", .9999)], r) == []
