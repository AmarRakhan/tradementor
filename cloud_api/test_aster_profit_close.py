from aster_profit_close import (
    MINIMUM_PROFIT_USD,
    profit_preview,
    profitable_positions,
    strict_profit_preview,
    strictly_profitable_positions,
)


def position(symbol: str, side: str, pnl: float, quantity: float = 1.0) -> dict:
    return {
        "symbol": symbol,
        "positionSide": side,
        "positionAmt": str(quantity),
        "markPrice": "10",
        "unRealizedProfit": str(pnl),
    }


def test_exact_threshold_and_both_position_sides_are_eligible():
    """Legacy Tradecentrum contract stays inclusive at exactly $0.50."""
    rows = [position("BTCUSDT", "LONG", MINIMUM_PROFIT_USD), position("ETHUSDT", "SHORT", 1.25)]
    preview = profit_preview(rows)
    assert preview["eligibleCount"] == 2
    assert preview["totalProfitUsd"] == 1.75
    assert [item["side"] for item in preview["eligible"]] == ["LONG", "SHORT"]


def test_sub_threshold_and_loss_positions_are_never_selected():
    rows = [position("BTCUSDT", "LONG", 0.499999), position("ETHUSDT", "SHORT", -50)]
    assert profitable_positions(rows) == []


def test_closed_invalid_or_unpriced_positions_are_never_selected():
    rows = [
        position("BTCUSDT", "LONG", 5, quantity=0),
        {**position("ETHUSDT", "BOTH", 5)},
        {**position("SOLUSDT", "SHORT", 5), "markPrice": "0"},
        {**position("XRPUSDT", "LONG", 5), "unRealizedProfit": "not-a-number"},
    ]
    assert profitable_positions(rows) == []


def test_preview_never_invents_values_when_exchange_fields_are_missing():
    preview = profit_preview([{"symbol": "BTCUSDT", "positionSide": "LONG"}])
    assert preview == {
        "eligible": [],
        "eligibleCount": 0,
        "totalProfitUsd": 0,
        "minimumProfitUsd": 0.5,
    }


def test_snapshot_exact_threshold_is_excluded_but_legacy_tradecentrum_keeps_it():
    rows = [
        position("BTCUSDT", "LONG", MINIMUM_PROFIT_USD),
        position("ETHUSDT", "SHORT", 0.500001),
    ]
    assert [item["symbol"] for item in profitable_positions(rows)] == ["BTCUSDT", "ETHUSDT"]
    assert [item["symbol"] for item in strictly_profitable_positions(rows)] == ["ETHUSDT"]


def test_snapshot_long_and_short_scopes_are_separate_and_all_is_union():
    rows = [
        position("BTCUSDT", "LONG", 0.75),
        position("ETHUSDT", "SHORT", 1.25),
        position("SOLUSDT", "LONG", 0.50),
        position("XRPUSDT", "SHORT", -2.0),
    ]
    preview = strict_profit_preview(rows)

    assert preview["comparison"] == "strictly_greater_than"
    assert preview["minimumProfitUsd"] == MINIMUM_PROFIT_USD
    assert preview["long"]["eligibleCount"] == 1
    assert preview["long"]["totalProfitUsd"] == 0.75
    assert preview["short"]["eligibleCount"] == 1
    assert preview["short"]["totalProfitUsd"] == 1.25
    assert preview["all"]["eligibleCount"] == 2
    assert preview["all"]["totalProfitUsd"] == 2.0
    assert [item["side"] for item in preview["all"]["eligible"]] == ["LONG", "SHORT"]


def test_snapshot_scope_rejects_unknown_side():
    rows = [position("BTCUSDT", "LONG", 1.0)]
    try:
        strictly_profitable_positions(rows, side="BOTH")
    except ValueError as exc:
        assert "ALL, LONG or SHORT" in str(exc)
    else:
        raise AssertionError("invalid Snapshot side must fail closed")
