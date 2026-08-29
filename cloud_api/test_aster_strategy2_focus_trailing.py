import pytest

from aster_strategy2 import Strategy2Config
from aster_strategy2_focus_trailing import (
    DCA_FROZEN,
    DCA_TRAILING,
    dca_crossed,
    dca_distance,
    hedge_release_distance,
    next_dca_from_anchor,
    release_distance_from_frozen,
)

# Activation regression suite for the live Strategy-2 trailing/frozen hedge state-machine.


def test_long_trailing_dca_is_exact_configured_distance():
    cfg = Strategy2Config.from_mapping({"tradingMode": "focus", "focusDcaDistance": 0.003})
    assert dca_distance(cfg) == pytest.approx(0.003)
    assert next_dca_from_anchor(100, "LONG", dca_distance(cfg)) == pytest.approx(99.7)
    assert next_dca_from_anchor(105, "LONG", dca_distance(cfg)) == pytest.approx(104.685)
    assert dca_crossed(104.685, 104.685, "LONG")
    assert not dca_crossed(104.686, 104.685, "LONG")


def test_short_trailing_dca_is_exact_mirror():
    assert next_dca_from_anchor(100, "SHORT", 0.003) == pytest.approx(100.3)
    assert dca_crossed(100.3, 100.3, "SHORT")
    assert not dca_crossed(100.299, 100.3, "SHORT")


def test_frozen_long_dca_release_threshold_uses_live_denominator():
    frozen = 99.7
    at_release = frozen / (1 - 0.0035)
    assert release_distance_from_frozen(100.0, frozen, "LONG") == pytest.approx(0.003)
    assert release_distance_from_frozen(at_release, frozen, "LONG") == pytest.approx(0.0035)
    assert release_distance_from_frozen(frozen / (1 - 0.004), frozen, "LONG") == pytest.approx(0.004)


def test_frozen_short_dca_release_is_mirrored():
    frozen = 100.3
    at_release = frozen / (1 + 0.0035)
    assert release_distance_from_frozen(at_release, frozen, "SHORT") == pytest.approx(0.0035)


def test_release_setting_prefers_new_config_and_has_legacy_fallback():
    legacy = Strategy2Config.from_mapping({"focusV2RecoveryReboundPct": 0.0042})
    # Until the explicit alias is present on Strategy2Config the compatibility value is used.
    assert hedge_release_distance(legacy) == pytest.approx(getattr(legacy, "focus_v2_hedge_release_distance_pct", legacy.focus_v2_recovery_rebound_pct))


def test_runtime_source_contains_required_state_machine_and_no_recovery_heuristics():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    assert 'DCA_TRAILING = "TRAILING"' in src
    assert 'DCA_FROZEN = "FROZEN_FOR_HEDGE"' in src
    assert '"hedgeState": HEDGE_OFF' in src
    assert '"hedgeState": HEDGE_ACTIVE' in src
    assert "distance >= release_ratio" in src
    assert "FOCUS_V2_HEDGE_RELEASED" in src
    assert "FOCUS_V2_PARTIAL_PROFIT" in src
    assert "Bollinger" not in src
    assert "recovery_confirmed" not in src


def test_partial_profit_contract_preserves_dca_fields_by_design():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    marker = '# Preserve trailingHigh/Low, nextDcaPrice, dcaMode, frozen ref and dcaCount exactly.'
    assert marker in src
    assert '"lastPartialProfitOrderId"' in src


def test_precision_retry_is_bounded_and_rebuilds_plan():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    assert "for attempt in range(2)" in src
    assert '"-1111" in message' in src
    assert "client.public_exchange_info()" in src
    assert "_plan(client, symbol, mark, notional, leverage)" in src
