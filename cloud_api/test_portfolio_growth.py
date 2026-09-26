from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest

from portfolio_growth import (PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION, PORTFOLIO_GROWTH_START_DATE, average_daily_return, chain_linked_return_percent, daily_return_percentage, estimate_close_value, external_cashflow_breakdown, external_cashflow_since, historical_day_windows, is_exposure_order, select_day_start_snapshot, utc_ms)


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


def test_build432_signed_cashflow_breakdown_separates_deposits_withdrawals_and_trading():
    rows=[
        {"time":1000,"incomeType":"TRANSFER","income":"200"},
        {"time":1100,"incomeType":"TRANSFER","income":"-100"},
        {"time":1200,"incomeType":"WELCOME_BONUS","income":"5"},
        {"time":1300,"incomeType":"REALIZED_PNL","income":"11.51"},
    ]
    assert external_cashflow_since(rows,1000) == pytest.approx(105)
    audit=external_cashflow_breakdown(rows,1000)
    assert audit["depositsUsd"] == pytest.approx(200)
    assert audit["withdrawalsUsd"] == pytest.approx(-100)
    assert audit["adjustmentsUsd"] == pytest.approx(5)
    assert audit["netExternalCashflowUsd"] == pytest.approx(105)
    assert audit["count"] == 3
    assert "REALIZED_PNL" not in audit["ledgerTypes"]


def test_build432_deposit_and_withdrawal_are_neutralized_in_daily_return():
    assert daily_return_percentage(100,290,200) == pytest.approx(-10)
    assert daily_return_percentage(300,195,-100) == pytest.approx(-1.6666666667)


def test_build432_twr_primitive_chain_links_subperiod_returns():
    assert chain_linked_return_percent([10,-5]) == pytest.approx(4.5)


def test_build433_day_start_never_uses_stale_previous_day_snapshot():
    assert PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION == 3
    rows=[
        {"atMs":1_000,"firstSampleAtMs":1_020,"open":100},
        {"atMs":2_000,"firstSampleAtMs":2_030,"open":300},
        {"atMs":3_000,"firstSampleAtMs":3_010,"open":305},
    ]
    start=select_day_start_snapshot(rows,day_start_ms=2_000,current_equity=310,current_at_ms=4_000)
    assert start == {"equity":300.0,"atMs":2_030,"source":"portfolio-chart-same-day"}


def test_build433_day_start_falls_back_to_current_equity_instead_of_stale_history():
    rows=[{"atMs":1_000,"firstSampleAtMs":1_010,"open":100}]
    start=select_day_start_snapshot(rows,day_start_ms=2_000,current_equity=340.59,current_at_ms=4_000)
    assert start == {"equity":340.59,"atMs":4_000,"source":"current-exchange-equity"}


def _ams_ms(year,month,day,hour,minute=0):
    zone=ZoneInfo("Europe/Amsterdam")
    return int(datetime(year,month,day,hour,minute,tzinfo=zone).astimezone(timezone.utc).timestamp()*1000)


def test_build438_reconstructs_only_complete_local_days_for_average():
    rows=[
        {"firstSampleAtMs":_ams_ms(2026,9,23,0,5),"sourceAtMs":_ams_ms(2026,9,23,0,55),"open":100,"close":102},
        {"firstSampleAtMs":_ams_ms(2026,9,23,23,0),"sourceAtMs":_ams_ms(2026,9,23,23,55),"open":98,"close":95},
        {"firstSampleAtMs":_ams_ms(2026,9,24,0,4),"sourceAtMs":_ams_ms(2026,9,24,0,55),"open":95,"close":94},
        {"firstSampleAtMs":_ams_ms(2026,9,24,23,0),"sourceAtMs":_ams_ms(2026,9,24,23,56),"open":90,"close":89},
        # Partial day: first observation is far too late and must not influence the average.
        {"firstSampleAtMs":_ams_ms(2026,9,25,8,0),"sourceAtMs":_ams_ms(2026,9,25,23,55),"open":89,"close":88},
    ]
    windows=historical_day_windows(
        rows,timezone_name="Europe/Amsterdam",current_date="2026-09-26",max_days=14,
    )
    assert [row["date"] for row in windows] == ["2026-09-23","2026-09-24"]
    assert windows[0]["startEquity"] == pytest.approx(100)
    assert windows[0]["endEquity"] == pytest.approx(95)
    assert windows[1]["startEquity"] == pytest.approx(95)
    assert windows[1]["endEquity"] == pytest.approx(89)


def test_build438_backfilled_day_keeps_deposit_neutral():
    start,end,deposit=95,189,100
    assert daily_return_percentage(start,end,deposit) == pytest.approx(-6.3157894737)
