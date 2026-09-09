from aster_profit_close import (
    HEDGE_HEALTHY_MAX_PERCENT,
    HEDGE_HEALTHY_MIN_PERCENT,
    HEDGE_TARGET_PERCENT,
    MINIMUM_PROFIT_USD,
    portfolio_exposure,
    profit_preview,
    profitable_positions,
    strict_profit_preview,
    strictly_profitable_positions,
)


def position(symbol: str, side: str, pnl: float, quantity: float = 1.0, mark: float = 10.0) -> dict:
    return {
        "symbol": symbol,
        "positionSide": side,
        "positionAmt": str(quantity),
        "markPrice": str(mark),
        "unRealizedProfit": str(pnl),
    }


def test_exact_threshold_and_both_position_sides_are_eligible():
    """Legacy Tradecentrum contract stays inclusive at exactly $0.50."""
    rows = [position("BTCUSDT", "LONG", MINIMUM_PROFIT_USD), position("ETHUSDT", "SHORT", 1.25)]
    preview = profit_preview(rows)
    assert preview["eligibleCount"] == 2
    assert preview["totalProfitUsd"] == 1.75
    assert preview["comparison"] == "greater_than_or_equal"
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


def test_preview_never_invents_exposure_when_exchange_fields_are_missing():
    preview = profit_preview([{"symbol": "BTCUSDT", "positionSide": "LONG"}])
    assert preview["eligible"] == []
    assert preview["eligibleCount"] == 0
    assert preview["totalProfitUsd"] == 0
    assert preview["minimumProfitUsd"] == MINIMUM_PROFIT_USD
    assert preview["comparison"] == "greater_than_or_equal"
    assert preview["exposure"]["longExposureUsd"] == 0
    assert preview["exposure"]["shortExposureUsd"] == 0
    assert preview["exposure"]["hedgeCoveragePercent"] is None
    assert preview["exposure"]["reliable"] is True


def test_portfolio_exposure_uses_mark_notional_not_position_count():
    rows = [
        position("BTCUSDT", "LONG", 0.1, quantity=10, mark=10),   # $100 long
        position("ETHUSDT", "SHORT", 0.1, quantity=8, mark=10),  # $80 short
    ]
    exposure = portfolio_exposure(rows)
    assert exposure["reliable"] is True
    assert exposure["longExposureUsd"] == 100
    assert exposure["shortExposureUsd"] == 80
    assert exposure["netExposureUsd"] == 20
    assert exposure["netSide"] == "LONG"
    assert exposure["hedgeCoveragePercent"] == 80
    assert exposure["status"] == "within_target"


def test_hedge_coverage_can_exceed_one_hundred_percent():
    rows = [
        position("BTCUSDT", "LONG", 0.1, quantity=10, mark=10),
        position("ETHUSDT", "SHORT", 0.1, quantity=12, mark=10),
    ]
    exposure = portfolio_exposure(rows)
    assert exposure["hedgeCoveragePercent"] == 120
    assert exposure["netExposureUsd"] == -20
    assert exposure["netSide"] == "SHORT"
    assert exposure["status"] == "above_target"


def test_preview_exposes_single_config_source_of_truth():
    preview = profit_preview([position("BTCUSDT", "LONG", 1)])
    assert preview["hedgeConfig"] == {
        "targetPercent": HEDGE_TARGET_PERCENT,
        "healthyMinPercent": HEDGE_HEALTHY_MIN_PERCENT,
        "healthyMaxPercent": HEDGE_HEALTHY_MAX_PERCENT,
    }


def test_profitable_short_close_warns_when_it_removes_needed_hedge():
    rows = [
        position("BTCUSDT", "LONG", 0.1, quantity=10, mark=10),      # $100 long
        position("ETHUSDT", "SHORT", 0.1, quantity=6, mark=10),    # $60 hedge retained
        position("SOLUSDT", "SHORT", 1.0, quantity=2, mark=10),    # $20 hedge qualifies to close
    ]
    impact = profit_preview(rows)["short"]["impact"]
    assert impact["before"]["hedgeCoveragePercent"] == 80
    assert impact["after"]["hedgeCoveragePercent"] == 60
    assert impact["removedShortExposureUsd"] == 20
    assert impact["protectionDirection"] == "decreases"
    assert impact["impactType"] == "away_from_target"


def test_overhedged_profitable_short_close_can_move_coverage_back_to_target():
    rows = [
        position("BTCUSDT", "LONG", 0.1, quantity=10, mark=10),      # $100 long
        position("ETHUSDT", "SHORT", 0.1, quantity=8, mark=10),    # $80 hedge retained
        position("SOLUSDT", "SHORT", 1.0, quantity=4, mark=10),    # $40 overhedge qualifies to close
    ]
    preview = profit_preview(rows)
    impact = preview["short"]["impact"]
    assert preview["short"]["eligibleCount"] == 1
    assert impact["before"]["hedgeCoveragePercent"] == 120
    assert impact["before"]["status"] == "above_target"
    assert impact["after"]["hedgeCoveragePercent"] == 80
    assert impact["after"]["status"] == "within_target"
    assert impact["protectionDirection"] == "decreases"
    assert impact["impactType"] == "toward_target"


def test_closing_long_uses_same_impact_engine_and_can_raise_hedge_ratio():
    rows = [
        position("BTCUSDT", "LONG", 0.1, quantity=8, mark=10),      # $80 long retained
        position("SOLUSDT", "LONG", 1.0, quantity=2, mark=10),     # $20 long qualifies to close
        position("ETHUSDT", "SHORT", 0.1, quantity=8, mark=10),    # $80 short
    ]
    impact = profit_preview(rows)["long"]["impact"]
    assert impact["before"]["hedgeCoveragePercent"] == 80
    assert impact["after"]["hedgeCoveragePercent"] == 100
    assert impact["removedLongExposureUsd"] == 20
    assert impact["protectionDirection"] == "increases"
    assert impact["impactType"] == "away_from_target"


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
