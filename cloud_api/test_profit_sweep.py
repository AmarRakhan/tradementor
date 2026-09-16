from decimal import Decimal

import pytest

from profit_sweep import (
    DEFAULT_SWEEP_ENABLED,
    ProfitSweepError,
    build_sweep_booking,
    normalize_sweep_percent,
    sweep_contribution,
)


def test_profit_sweep_is_off_by_default():
    assert DEFAULT_SWEEP_ENABLED is False


def test_configurable_percentages_apply_only_to_positive_net_realized_profit():
    assert sweep_contribution("1", "5") == Decimal("0.05000000")
    assert sweep_contribution("1", "10") == Decimal("0.10000000")
    assert sweep_contribution("1", "25") == Decimal("0.25000000")
    assert sweep_contribution("1", "50") == Decimal("0.50000000")
    assert sweep_contribution("-12.50", "50") == Decimal("0")
    assert sweep_contribution("0", "100") == Decimal("0")
    assert sweep_contribution("100", "50", enabled=False) == Decimal("0")


def test_percent_must_be_between_zero_and_one_hundred():
    assert normalize_sweep_percent("0") == Decimal("0")
    assert normalize_sweep_percent("100") == Decimal("100")
    with pytest.raises(ProfitSweepError):
        normalize_sweep_percent("-0.01")
    with pytest.raises(ProfitSweepError):
        normalize_sweep_percent("100.01")


def test_booking_snapshots_enabled_state_and_percentage_without_touching_principal_or_unrealized_pnl():
    first = build_sweep_booking(closure_id="cycle-1", net_realized_profit="1", sweep_percent="25", enabled=True)
    later = build_sweep_booking(closure_id="cycle-2", net_realized_profit="1", sweep_percent="5", enabled=True)
    disabled = build_sweep_booking(closure_id="cycle-3", net_realized_profit="10", sweep_percent="50", enabled=False)

    assert first["enabled"] is True
    assert first["sweepPercent"] == "25"
    assert first["sweepContribution"] == "0.25"
    assert later["sweepPercent"] == "5"
    assert later["sweepContribution"] == "0.05"
    assert disabled["sweepContribution"] == "0"
    assert first["sweepPercent"] == "25"
    assert first["principalIncluded"] is False
    assert first["unrealizedPnlIncluded"] is False


def test_missing_closure_id_is_rejected():
    with pytest.raises(ProfitSweepError):
        build_sweep_booking(closure_id="", net_realized_profit="1", sweep_percent="25")
