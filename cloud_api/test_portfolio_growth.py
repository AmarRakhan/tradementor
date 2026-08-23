from datetime import datetime, timezone
import pytest

from portfolio_growth import (PORTFOLIO_GROWTH_START_DATE, average_daily_return, daily_return_percentage, estimate_close_value, external_cashflow_since, is_exposure_order, utc_ms)


def position(notional=100, side="LONG"):
    return {"symbol":"BTCUSDT","positionSide":side,"positionAmt":str(notional/10),"markPrice":"10"}


def estimate(**overrides):
    values=dict(baseline=359,exchange_equity=369.30,positions=[position()],external_cashflow=0,
        taker_fee_rate=.001,slippage_rate=.002,other_costs=0,equity_includes_unrealized=True,
        funding_in_equity=True,data_fresh=True,cashflow_complete=True)
    values.update(overrides)
    return estimate_close_value(**values)


def test_dollar_percentage_and_conservative_costs():
    result=estimate()
    assert result.expected_fees == pytest.approx(.1)
    assert result.slippage_buffer == pytest.approx(.2)
    assert result.difference == pytest.approx(10)
    assert result.percentage == pytest.approx(2.785515, rel=1e-5)
    assert result.public()["closeEnabled"] is True


@pytest.mark.parametrize(("equity","positive"),[(360,True),(359,False),(358,False)])
def test_positive_zero_negative_states(equity,positive):
    result=estimate(exchange_equity=equity,taker_fee_rate=0,slippage_rate=0)
    assert result.public()["profitable"] is positive


def test_equity_is_not_double_adjusted_for_unrealized_or_funding():
    result=estimate(exchange_equity=400,positions=[],taker_fee_rate=0,slippage_rate=0)
    assert result.expected_end_value == 400


def test_cashflows_adjust_baseline_not_profit():
    result=estimate(exchange_equity=469.30,external_cashflow=100)
    assert result.difference == pytest.approx(10)
    rows=[{"time":1000,"incomeType":"TRANSFER","income":"100"},{"time":1001,"incomeType":"REALIZED_PNL","income":"9"},{"time":999,"incomeType":"TRANSFER","income":"4"}]
    assert external_cashflow_since(rows,1000) == 100


@pytest.mark.parametrize("field",["equity_includes_unrealized","funding_in_equity","data_fresh","cashflow_complete"])
def test_missing_or_stale_evidence_fails_closed(field):
    result=estimate(**{field:False})
    assert result.reliable is False
    assert result.public()["closeEnabled"] is False


def test_entry_order_classification_is_fail_closed_for_unknown():
    assert is_exposure_order({"clientOrderId":"tm-s2-open-1"}) is True
    assert is_exposure_order({"clientOrderId":"tm-tp-close-1"}) is False
    assert is_exposure_order({"clientOrderId":"mystery"}) is None


def test_utc_ms():
    assert utc_ms(datetime(1970,1,1,0,0,1,tzinfo=timezone.utc)) == 1000


def test_daily_growth_start_and_percentage_math():
    assert PORTFOLIO_GROWTH_START_DATE == "2026-08-23"
    assert daily_return_percentage(203, 224) == pytest.approx(10.3448275862)
    assert daily_return_percentage(200, 190) == pytest.approx(-5.0)


def test_daily_growth_removes_external_cashflow_and_averages_arithmetically():
    assert daily_return_percentage(200, 310, 100) == pytest.approx(5.0)
    assert daily_return_percentage(200, 155, -50) == pytest.approx(2.5)
    assert average_daily_return(5.0, 2, 4.0) == pytest.approx(3.0)
