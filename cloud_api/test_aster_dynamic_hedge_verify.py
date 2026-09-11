from __future__ import annotations

from copy import deepcopy

from aster_cross_risk import cross_account_risk
from aster_dynamic_hedge_verify import verify_read_only_projection


def account(equity=300.0, maintenance=30.0, available=0.0):
    return {
        "totalMarginBalance": equity,
        "totalWalletBalance": equity,
        "totalUnrealizedProfit": 0,
        "totalMaintMargin": maintenance,
        "availableBalance": available,
    }


def row(symbol, side, notional, mark=100.0):
    qty = notional / mark
    return {
        "symbol": symbol,
        "positionSide": side,
        "positionAmt": qty if side == "LONG" else -qty,
        "markPrice": mark,
        "entryPrice": mark,
        "marginType": "cross",
    }


def test_read_only_verifier_matches_raw_aster_truth_and_never_orders():
    raw_account = account(300, 30, 0)
    rows = [row("BTCUSDT", "LONG", 1000), row("ETHUSDT", "SHORT", 300)]
    risk = cross_account_risk(raw_account, rows)
    proof = verify_read_only_projection(raw_account, rows, risk)
    assert proof["passed"] is True
    assert proof["readOnly"] is True
    assert proof["ordersSubmitted"] == 0
    assert proof["failureCodes"] == []
    assert proof["raw"]["equity"] == 300
    assert proof["raw"]["maintenanceMarginUsd"] == 30
    assert proof["raw"]["availableBalance"] == 0
    assert proof["raw"]["longExposureUsd"] == 1000
    assert proof["raw"]["shortExposureUsd"] == 300


def test_verifier_rejects_projection_drift():
    raw_account = account()
    rows = [row("BTCUSDT", "LONG", 1000), row("ETHUSDT", "SHORT", 300)]
    risk = cross_account_risk(raw_account, rows)
    corrupted = deepcopy(risk)
    corrupted["shortNotional"] = 301
    proof = verify_read_only_projection(raw_account, rows, corrupted)
    assert proof["passed"] is False
    assert "SHORT_EXPOSURE_MATCH" in proof["failureCodes"]


def test_verifier_rejects_missing_maintenance_even_if_other_numbers_look_safe():
    raw_account = account()
    raw_account.pop("totalMaintMargin")
    rows = [row("BTCUSDT", "LONG", 1000)]
    risk = cross_account_risk(raw_account, rows)
    proof = verify_read_only_projection(raw_account, rows, risk)
    assert proof["passed"] is False
    assert "RAW_MAINTENANCE_PRESENT" in proof["failureCodes"]


def test_verifier_keeps_same_symbol_dual_side_separate():
    raw_account = account(500, 40, 50)
    rows = [row("BTCUSDT", "LONG", 900), row("BTCUSDT", "SHORT", 600)]
    risk = cross_account_risk(raw_account, rows)
    proof = verify_read_only_projection(raw_account, rows, risk)
    assert proof["passed"] is True
    assert proof["raw"]["longExposureUsd"] == 900
    assert proof["raw"]["shortExposureUsd"] == 600
    assert proof["raw"]["grossExposureUsd"] == 1500
    assert proof["raw"]["netExposureUsd"] == 300
