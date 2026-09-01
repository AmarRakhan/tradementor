from aster_cross_risk import cross_account_risk


def pos(symbol, side, notional, mark=100, leverage=20, margin_type="cross"):
    qty = notional / mark
    return {"symbol": symbol, "positionSide": side, "positionAmt": qty if side == "LONG" else -qty,
            "markPrice": mark, "entryPrice": mark, "leverage": leverage, "marginType": margin_type}


def account(equity=1000, maintenance=10, pnl=0, **extra):
    return {"totalMarginBalance": equity, "totalWalletBalance": equity-pnl,
            "totalUnrealizedProfit": pnl, "totalMaintMargin": maintenance, **extra}


def test_naked_long_risk_rises_when_cross_equity_falls():
    p=[pos("BTCUSDT","LONG",1000)]
    safe=cross_account_risk(account(1000,10),p)
    adverse=cross_account_risk(account(500,10,-500),p)
    assert safe["liquidationRiskPct"] == 1
    assert adverse["liquidationRiskPct"] == 2


def test_naked_short_uses_same_account_wide_threshold_math():
    result=cross_account_risk(account(800,16),[pos("ETHUSDT","SHORT",800,leverage=50)])
    assert result["liquidationRiskPct"] == 2
    assert result["shortNotional"] == 800


def test_equal_same_pair_hedge_never_hardcodes_liquidation_risk_to_zero():
    result=cross_account_risk(account(1000,20),[pos("BTCUSDT","LONG",1000),pos("BTCUSDT","SHORT",1000)])
    assert result["netExposure"] == 0
    assert result["grossExposure"] == 2000
    assert result["liquidationRiskPct"] == 2
    assert result["maintenanceMarginPct"] == 1
    assert result["positionCountIncluded"] == 2


def test_partial_hedge_preserves_residual_exposure():
    result=cross_account_risk(account(1000,15),[pos("BTCUSDT","LONG",1000),pos("BTCUSDT","SHORT",500)])
    assert result["netExposure"] == 500
    assert result["grossExposure"] == 1500
    assert result["liquidationRiskPct"] == 1.5


def test_multi_pair_mixed_leverage_includes_every_leg():
    rows=[pos("BTCUSDT","LONG",1000,leverage=20),pos("ETHUSDT","SHORT",700,leverage=50)]
    result=cross_account_risk(account(1000,17),rows)
    assert result["positionCountIncluded"] == 2
    assert result["totalCrossNotional"] == 1700
    assert round(result["liquidationRiskPct"], 8) == 1.7


def test_fifty_cross_positions_are_not_truncated():
    rows=[pos(f"L{i}USDT","LONG",100+i,leverage=5+(i%20)) for i in range(30)]
    rows += [pos(f"S{i}USDT","SHORT",80+i,leverage=10+(i%40)) for i in range(20)]
    result=cross_account_risk(account(2000,80),rows)
    assert result["positionCountIncluded"] == 50
    assert result["longNotional"] > 0 and result["shortNotional"] > 0
    assert result["liquidationRiskPct"] == 4


def test_official_aster_account_ratio_wins_when_present():
    result=cross_account_risk(account(1000,99,marginRatio="0.1234"),[pos("BTCUSDT","LONG",1000)])
    assert result["liquidationRiskPct"] == 12.34
    assert result["liquidationRiskSource"] == "ASTER_ACCOUNT_RATIO"


def test_reconstructed_source_uses_total_maintenance_over_margin_balance():
    result=cross_account_risk(account(250,25),[pos("BTCUSDT","LONG",1000)])
    assert result["liquidationRiskPct"] == 10
    assert result["liquidationRiskSource"] == "SERVER_RECONSTRUCTED"


def test_near_liquidation_and_no_position_boundaries():
    near=cross_account_risk(account(101,100),[pos("BTCUSDT","LONG",1000)])
    empty=cross_account_risk(account(1000,0),[])
    assert 99 < near["liquidationRiskPct"] < 100
    assert empty["liquidationRiskPct"] == 0
    assert empty["maintenanceMarginPct"] == 0
    assert empty["positionCountIncluded"] == 0


def test_isolated_rows_do_not_pollute_cross_exposure_diagnostics():
    result=cross_account_risk(account(1000,10),[pos("BTCUSDT","LONG",1000),pos("ETHUSDT","SHORT",500,margin_type="isolated")])
    assert result["positionCountIncluded"] == 1
    assert result["grossExposure"] == 1000
