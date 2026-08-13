from portfolio_risk import ExchangeRiskSnapshot, PortfolioRiskLimits, evaluate_risk_increase


NOW = 1_000_000


def row(exchange: str, *, equity=100.0, available=80.0, gross=50.0, net=10.0, used=10.0, liq=.25, read=True, age=0):
    return ExchangeRiskSnapshot(
        exchange, equity, available, gross, net, used, 1.0, liq, NOW - age, read,
    )


def test_balanced_fresh_portfolio_can_approve_small_order():
    result = evaluate_risk_increase(
        [row("mexc"), row("hyperliquid"), row("aster")],
        requested_exchange="aster", requested_notional=20, now_ms=NOW, day_start_equity=300,
    )
    assert result.approved is True
    assert result.total_equity == 300


def test_stale_or_failed_exchange_read_blocks_new_exposure():
    stale = evaluate_risk_increase(
        [row("mexc", age=31_000)], requested_exchange="mexc", requested_notional=10,
        now_ms=NOW, day_start_equity=100,
    )
    failed = evaluate_risk_increase(
        [row("mexc", read=False)], requested_exchange="mexc", requested_notional=10,
        now_ms=NOW, day_start_equity=100,
    )
    assert stale.approved is False
    assert failed.approved is False


def test_drawdown_and_liquidation_circuit_breakers_are_hard_blocks():
    result = evaluate_risk_increase(
        [row("aster", equity=80, liq=.05)], requested_exchange="aster", requested_notional=5,
        now_ms=NOW, day_start_equity=100,
    )
    assert result.approved is False
    assert any("drawdown" in reason for reason in result.reasons)
    assert any("liquidatieafstand" in reason for reason in result.reasons)


def test_single_exchange_concentration_is_checked_after_projected_order():
    result = evaluate_risk_increase(
        [row("aster", gross=60), row("mexc", gross=10), row("hyperliquid", gross=10)],
        requested_exchange="aster", requested_notional=40, now_ms=NOW, day_start_equity=300,
        limits=PortfolioRiskLimits(maximum_single_exchange_share=.70),
    )
    assert result.approved is False
    assert any("één exchange" in reason for reason in result.reasons)

