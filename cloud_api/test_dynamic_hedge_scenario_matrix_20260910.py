from __future__ import annotations

import pytest

from aster_cross_risk import cross_account_risk
from aster_dynamic_hedge import assess_dynamic_hedge, robust_hedge_coverage
from aster_dynamic_hedge_manual import (
    ManualActionMismatch, begin_manual_action, complete_manual_action, fail_manual_action,
    validate_manual_close_scope,
)
from aster_gateway import AsterSubmissionUncertain, classify_submission


def account(equity=300.0, maintenance=30.0, available=50.0, pnl=0.0):
    return {
        "totalMarginBalance": equity,
        "totalWalletBalance": equity - pnl,
        "totalUnrealizedProfit": pnl,
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
        "leverage": 20,
    }


def exposure(long_value, short_value):
    return {
        "reliable": True,
        "longExposureUsd": long_value,
        "shortExposureUsd": short_value,
    }


def candidate(current_buffer=270, current_ratio=10, projected_buffer=250, projected_ratio=7.5,
              projected_maintenance=40, projected_equity=300):
    return {
        "currentMarginBufferUsd": current_buffer,
        "currentBufferRatio": current_ratio,
        "projectedMarginBufferUsd": projected_buffer,
        "projectedBufferRatio": projected_ratio,
        "projectedMaintenanceMarginUsd": projected_maintenance,
        "projectedEquity": projected_equity,
    }


class FakeSnapshot:
    def __init__(self, data): self.data = data
    def to_dict(self): return dict(self.data)


class FakeRef:
    def __init__(self, data=None): self.data = dict(data or {})
    def get(self): return FakeSnapshot(self.data)
    def set(self, value, merge=False): self.data = {**self.data, **value} if merge else dict(value)


def test_scenario_01_only_long_positions():
    risk = cross_account_risk(account(), [row("BTCUSDT", "LONG", 1000)])
    assert risk["longNotional"] == 1000
    assert risk["shortNotional"] == 0
    assert risk["hedgeCoveragePercent"] == 0
    assert risk["netSide"] == "LONG"


def test_scenario_02_only_short_positions():
    risk = cross_account_risk(account(), [row("BTCUSDT", "SHORT", 1000)])
    assert risk["longNotional"] == 0
    assert risk["shortNotional"] == 1000
    assert risk["hedgeCoveragePercent"] == 0
    assert risk["netSide"] == "SHORT"


def test_scenario_03_same_symbol_long_and_short():
    risk = cross_account_risk(account(), [row("BTCUSDT", "LONG", 1000), row("BTCUSDT", "SHORT", 1000)])
    assert risk["hedgeCoveragePercent"] == 100
    assert risk["signedNetExposure"] == 0
    assert risk["grossExposure"] == 2000
    assert risk["liquidationRiskPct"] > 0


def test_scenario_04_current_35_long_48_short_style_portfolio():
    coverage = robust_hedge_coverage(8769, 2041)
    assert round(coverage or 0, 1) == 23.3
    assert 8769 - 2041 == 6728


def test_scenario_05_dynamic_hedge_off_is_monitor_only():
    risk = cross_account_risk(account(), [row("BTCUSDT", "LONG", 1000), row("BTCUSDT", "SHORT", 250)])
    out = assess_dynamic_hedge(enabled=False, ownership_state="NORMAL", exposure=exposure(1000, 250), risk=risk)
    assert out["engineState"] == "MONITORING"
    assert out["riskAddingAllowed"] is False


def test_scenario_06_dynamic_hedge_on_with_existing_positions_adopts_first():
    risk = cross_account_risk(account(), [row("BTCUSDT", "LONG", 1000)])
    out = assess_dynamic_hedge(enabled=True, ownership_state="ADOPTING", exposure=exposure(1000, 0), risk=risk, candidate=candidate())
    assert out["engineState"] == "POSITIONS_ADOPTING"
    assert out["riskAddingAllowed"] is False


def test_scenario_07_low_hedge_and_ample_margin_can_build_only_with_projection():
    risk = cross_account_risk(account(equity=500, maintenance=20), [row("BTCUSDT", "LONG", 1000), row("BTCUSDT", "SHORT", 100)])
    out = assess_dynamic_hedge(enabled=True, ownership_state="DYNAMIC_HEDGE_ACTIVE", exposure=exposure(1000, 100), risk=risk,
                               candidate=candidate(current_buffer=480, current_ratio=25, projected_buffer=450, projected_ratio=10, projected_maintenance=50, projected_equity=500))
    assert out["engineState"] == "HEDGE_BUILDING"
    assert out["recommendedAction"] == "OPEN_SHORT"
    assert out["riskAddingAllowed"] is True


def test_scenario_08_low_hedge_but_critical_margin_never_adds_short():
    risk = cross_account_risk(account(equity=100, maintenance=85), [row("BTCUSDT", "LONG", 1000), row("BTCUSDT", "SHORT", 100)])
    out = assess_dynamic_hedge(enabled=True, ownership_state="DYNAMIC_HEDGE_ACTIVE", exposure=exposure(1000, 100), risk=risk, candidate=candidate())
    assert out["engineState"] == "REDUCE_GROSS_EXPOSURE"
    assert out["riskAddingAllowed"] is False


def test_scenario_09_available_zero_does_not_fake_liquidation():
    risk = cross_account_risk(account(equity=300, maintenance=30, available=0), [row("BTCUSDT", "LONG", 1000)])
    assert risk["liquidationSafetyStatus"] == "VEILIG"
    assert risk["marginBufferUsd"] == 270


def test_scenario_10_margin_balance_near_maintenance_is_critical():
    risk = cross_account_risk(account(equity=101, maintenance=100), [row("BTCUSDT", "LONG", 1000)])
    assert risk["liquidationSafetyStatus"] == "KRITIEK"
    assert risk["marginBufferUsd"] == 1


def test_scenario_11_close_long_same_symbol_keeps_short_exactly_unchanged():
    before = [row("BTCUSDT", "LONG", 1000), row("BTCUSDT", "SHORT", 700)]
    after = [row("BTCUSDT", "LONG", 500), row("BTCUSDT", "SHORT", 700)]
    proof = validate_manual_close_scope(before, after, "LONG")
    assert all(item["side"] == "LONG" for item in proof["changed"])


def test_scenario_12_close_short_same_symbol_keeps_long_exactly_unchanged():
    before = [row("BTCUSDT", "LONG", 1000), row("BTCUSDT", "SHORT", 700)]
    after = [row("BTCUSDT", "LONG", 1000), row("BTCUSDT", "SHORT", 200)]
    proof = validate_manual_close_scope(before, after, "SHORT")
    assert all(item["side"] == "SHORT" for item in proof["changed"])


def test_scenario_13_duplicate_click_stays_locked_until_one_exchange_result_is_reconciled():
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    before = [row("BTCUSDT", "SHORT", 700)]
    first = begin_manual_action(ref, "SHORT", before)
    assert ref.data["ownershipState"] == "MANUAL_ACTION_LOCK"
    second = begin_manual_action(ref, "SHORT", before)
    assert first.active and second.active
    complete_manual_action(ref, first, [row("BTCUSDT", "SHORT", 200)])
    assert ref.data["ownershipState"] == "ADOPTING"


def test_scenario_14_timeout_after_submit_is_uncertain_and_never_blind_retry():
    with pytest.raises(AsterSubmissionUncertain):
        classify_submission(503, {"msg": "Unknown error"})
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    guard = begin_manual_action(ref, "LONG", [row("BTCUSDT", "LONG", 1000)])
    fail_manual_action(ref, guard, "503 after submit; query exchange truth first")
    assert ref.data["ownershipState"] == "MANUAL_ACTION_LOCK"


def test_scenario_15_restart_preserves_fail_closed_adoption_state():
    persisted = {"enabled": True, "ownershipState": "ADOPTING"}
    risk = cross_account_risk(account(), [row("BTCUSDT", "LONG", 1000), row("BTCUSDT", "SHORT", 300)])
    out = assess_dynamic_hedge(enabled=persisted["enabled"], ownership_state=persisted["ownershipState"], exposure=exposure(1000, 300), risk=risk, candidate=candidate())
    assert out["engineState"] == "POSITIONS_ADOPTING"
    assert out["riskAddingAllowed"] is False
