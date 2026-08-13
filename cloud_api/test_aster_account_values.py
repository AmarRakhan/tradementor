from aster_state import account_values as aster_account_values


def test_flat_aster_account_uses_available_as_equity_floor():
    equity, wallet, available, pnl = aster_account_values(
        {"asset": "USDT", "balance": "0", "availableBalance": "120.07", "crossUnPnl": "0"}, []
    )
    assert (equity, wallet, available, pnl) == (120.07, 120.07, 120.07, 0.0)


def test_cross_wallet_balance_is_preferred_when_present():
    equity, wallet, available, pnl = aster_account_values(
        {"crossWalletBalance": "125", "availableBalance": "100", "crossUnPnl": "-2"},
        [{"positionAmt": "1", "positionInitialMargin": "23"}],
    )
    assert (equity, wallet, available, pnl) == (123.0, 125.0, 100.0, -2.0)
