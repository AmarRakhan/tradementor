from decimal import Decimal

import pytest

from aster_portfolio_emergency_margin import estimate_emergency_margin


def row(symbol, side, qty, mark="1", leverage="10"):
    return {
        "symbol": symbol,
        "positionSide": side,
        "positionAmt": str(qty),
        "markPrice": str(mark),
        "leverage": str(leverage),
    }


def test_balanced_pair_requires_no_reserve():
    value = estimate_emergency_margin([
        row("XRPUSDT", "LONG", 100), row("XRPUSDT", "SHORT", 100),
    ], 20)
    assert value.reserve_usd == Decimal("0")
    assert value.feasible_now is True
    assert value.technical_override is False


def test_long_delta_estimates_opposite_margin():
    value = estimate_emergency_margin([row("XRPUSDT", "LONG", 100, mark="2", leverage="20")], 50)
    assert value.hedge_notional_usd == Decimal("200")
    assert value.estimated_initial_margin_usd == Decimal("10")
    assert value.reserve_usd == Decimal("12.50")


def test_existing_opposite_leg_reduces_reserve():
    value = estimate_emergency_margin([
        row("XRPUSDT", "LONG", 100, mark="2", leverage="20"),
        row("XRPUSDT", "SHORT", 40, mark="2", leverage="20"),
    ], 50)
    assert value.hedge_notional_usd == Decimal("120")
    assert value.estimated_initial_margin_usd == Decimal("6")


def test_short_delta_is_symmetric():
    value = estimate_emergency_margin([row("ETHUSDT", "SHORT", 2, mark="3000", leverage="100")], 100)
    assert value.hedge_notional_usd == Decimal("6000")
    assert value.estimated_initial_margin_usd == Decimal("60")


def test_lower_observed_leverage_is_used_conservatively():
    value = estimate_emergency_margin([
        row("BTCUSDT", "LONG", ".02", mark="100000", leverage="100"),
        row("BTCUSDT", "SHORT", ".01", mark="100000", leverage="50"),
    ], 100)
    assert value.hedge_notional_usd == Decimal("1000.00")
    assert value.estimated_initial_margin_usd == Decimal("20.00")


def test_missing_leverage_falls_back_to_one_x():
    position = row("SOLUSDT", "LONG", 10, mark="100", leverage="0")
    value = estimate_emergency_margin([position], 2000)
    assert value.estimated_initial_margin_usd == Decimal("1000")


def test_reserve_adds_25_percent_headroom():
    value = estimate_emergency_margin([row("XRPUSDT", "LONG", 100, mark="1", leverage="10")], 100)
    assert value.reserve_usd == Decimal("12.50")


def test_minimum_execution_buffer_applies_to_small_margin():
    value = estimate_emergency_margin([row("XRPUSDT", "LONG", 1, mark="1", leverage="100")], 10)
    assert value.reserve_usd == Decimal("0.26")


def test_feasibility_false_below_reserve():
    value = estimate_emergency_margin([row("XRPUSDT", "LONG", 100, mark="1", leverage="10")], 12)
    assert value.feasible_now is False
    assert value.headroom_usd == Decimal("-0.50")


def test_technical_override_triggers_before_reserve_is_exhausted():
    value = estimate_emergency_margin([row("XRPUSDT", "LONG", 100, mark="1", leverage="10")], 18)
    assert value.reserve_usd == Decimal("12.50")
    assert value.technical_trigger_available_usd == Decimal("18.7500")
    assert value.feasible_now is True
    assert value.technical_override is True


def test_technical_override_stays_off_with_healthy_headroom():
    value = estimate_emergency_margin([row("XRPUSDT", "LONG", 100, mark="1", leverage="10")], 30)
    assert value.technical_override is False


def test_missing_mark_is_fail_closed():
    value = estimate_emergency_margin([row("XRPUSDT", "LONG", 100, mark="0", leverage="10")], 30)
    assert value.feasible_now is False
    assert value.technical_override is True


def test_multiple_symbols_sum_required_margin():
    value = estimate_emergency_margin([
        row("XRPUSDT", "LONG", 100, mark="1", leverage="10"),
        row("ETHUSDT", "SHORT", 1, mark="2000", leverage="100"),
    ], 100)
    assert value.estimated_initial_margin_usd == Decimal("30")
    assert value.symbol_count == 2


def test_public_dict_uses_stable_api_names():
    public = estimate_emergency_margin([row("XRPUSDT", "LONG", 100, mark="1", leverage="10")], 30).public_dict()
    assert public["estimatedHedgeMarginUsd"] == pytest.approx(10)
    assert public["hedgeReserveUsd"] == pytest.approx(12.5)
    assert public["technicalSafetyOverride"] is False
