from aster_hedge_recovery import (
    apply_notional_impact,
    average_start_margin,
    normalize_settings,
    portfolio_exposure,
    recommended_actions,
    step_target_percent,
    validate_recovery_direction,
)


def row(symbol, side, qty, mark, *, margin=None, pnl=0):
    value = {"symbol": symbol, "positionSide": side, "positionAmt": qty, "markPrice": mark, "unRealizedProfit": pnl}
    if margin is not None:
        value["startMarginUsd"] = margin
    return value


def test_canonical_hedge_math_and_overhedge():
    settings = normalize_settings(None)
    exposure = portfolio_exposure([row("L", "LONG", 10, 1000), row("S", "SHORT", 8, 1000)], settings)
    assert exposure["hedgeCoveragePercent"] == 80
    assert exposure["netExposureUsd"] == 2000
    assert exposure["netSide"] == "LONG"
    over = portfolio_exposure([row("L", "LONG", 10, 1000), row("S", "SHORT", 11.2, 1000)], settings)
    assert over["hedgeCoveragePercent"] == 112
    assert over["netExposureUsd"] == -1200
    assert over["netSide"] == "SHORT"


def test_config_is_not_hardcoded_to_80():
    settings = normalize_settings({"targetPercent": 60, "healthyMinPercent": 50, "healthyMaxPercent": 70, "maxCorrectionPercent": 7})
    exposure = portfolio_exposure([row("L", "LONG", 10, 1000), row("S", "SHORT", 6, 1000)], settings)
    assert exposure["hedgeCoveragePercent"] == 60
    assert exposure["status"] == "within_target"
    assert step_target_percent(20, settings) == 27


def test_recovery_direction_is_symmetric():
    assert recommended_actions("below_target") == {"recommended": "OPEN_SHORT", "alternative": "CLOSE_LONG"}
    assert recommended_actions("above_target") == {"recommended": "CLOSE_SHORT", "alternative": "OPEN_LONG"}
    validate_recovery_direction("below_target", "OPEN_SHORT")
    validate_recovery_direction("below_target", "CLOSE_LONG")
    validate_recovery_direction("above_target", "CLOSE_SHORT")
    validate_recovery_direction("above_target", "OPEN_LONG")


def test_same_side_original_margin_only_and_dca_does_not_distort():
    rows = [
        row("L1", "LONG", 1, 100, margin=3),
        row("L2", "LONG", 1, 100, margin=5),
        {**row("L3", "LONG", 20, 100), "positionInitialMargin": 40},  # current/DCA margin is deliberately ignored
        row("S1", "SHORT", 1, 100, margin=2),
        row("S2", "SHORT", 1, 100, margin=4),
    ]
    assert average_start_margin(rows, "LONG", 9)["marginUsd"] == 4
    assert average_start_margin(rows, "SHORT", 9)["marginUsd"] == 3


def test_open_and_close_impact_use_notional_not_seat_count():
    settings = normalize_settings(None)
    before = portfolio_exposure([row("L", "LONG", 10, 1000), row("S", "SHORT", 2, 1000)], settings)
    opened = apply_notional_impact(before, "OPEN_SHORT", 2000, settings, seat_count=10)
    assert opened["hedgeCoveragePercent"] == 40
    closed = apply_notional_impact(before, "CLOSE_LONG", 5000, settings, seat_count=2)
    assert closed["hedgeCoveragePercent"] == 40
