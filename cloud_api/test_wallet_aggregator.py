from wallet_aggregator import ExchangeWalletSnapshot, aggregate_wallets


NOW = 100_000


def row(exchange, *, wallet=100, pnl=10, equity=110, available=80, used=20, maintenance=1, age=0, ok=True):
    return ExchangeWalletSnapshot(
        exchange, wallet, pnl, equity, available, used, maintenance, NOW - age, ok,
    )


def test_complete_wallet_sums_three_exchanges_without_double_counting_pnl():
    result = aggregate_wallets(
        [row("mexc"), row("hyperliquid"), row("aster")], now_ms=NOW,
    )
    assert result.is_complete is True
    assert result.total_wallet_balance == 300
    assert result.total_unrealized_pnl == 30
    assert result.total_equity == 330
    assert result.total_equity != 360
    assert result.total_available_to_trade == 240


def test_missing_exchange_is_explicitly_partial_not_silently_zero():
    result = aggregate_wallets([row("mexc"), row("hyperliquid")], now_ms=NOW)
    assert result.is_complete is False
    assert result.missing_or_stale_exchanges == ("aster",)
    assert "Voorlopig" in result.label


def test_stale_or_failed_snapshot_is_excluded_and_reported():
    result = aggregate_wallets(
        [row("mexc"), row("hyperliquid", age=31_000), row("aster", ok=False)], now_ms=NOW,
    )
    assert result.fresh_exchanges == ("mexc",)
    assert result.missing_or_stale_exchanges == ("hyperliquid", "aster")
    assert result.total_equity == 110


def test_margin_ratio_uses_maintenance_over_equity():
    result = aggregate_wallets(
        [row("mexc", equity=100, maintenance=2), row("hyperliquid", equity=100, maintenance=3), row("aster", equity=100, maintenance=1)],
        now_ms=NOW,
    )
    assert result.margin_ratio == .02

