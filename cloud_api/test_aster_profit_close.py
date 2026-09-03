from aster_profit_close import MINIMUM_PROFIT_USD, profit_preview, profitable_positions


def position(symbol: str, side: str, pnl: float, quantity: float = 1.0) -> dict:
    return {
        "symbol": symbol,
        "positionSide": side,
        "positionAmt": str(quantity),
        "markPrice": "10",
        "unRealizedProfit": str(pnl),
    }


def test_exact_threshold_and_both_position_sides_are_eligible():
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
