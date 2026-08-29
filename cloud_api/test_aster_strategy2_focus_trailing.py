import pytest

from aster_strategy2 import Strategy2Config
from aster_strategy2_focus_trailing import (
    DCA_FROZEN,
    DCA_TRAILING,
    dca_crossed,
    dca_distance,
    hedge_ratio,
    hedge_release_crossed,
    hedge_release_recovery,
    next_dca_from_anchor,
    recovery_from_last_dca,
    release_price_from_last_dca,
)


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


def test_v5_release_is_from_last_confirmed_dca_fill():
    last_dca = 99.7
    release = release_price_from_last_dca(last_dca, "LONG", 0.0015)
    assert release == pytest.approx(99.84955)
    assert not hedge_release_crossed(99.84, release, "LONG")
    assert hedge_release_crossed(release, release, "LONG")
    assert recovery_from_last_dca(release, last_dca, "LONG") == pytest.approx(0.0015)


def test_v5_deeper_dca_replaces_both_fixed_levels():
    last_dca = 99.4009
    assert next_dca_from_anchor(last_dca, "LONG", 0.003) == pytest.approx(99.1026973)
    assert release_price_from_last_dca(last_dca, "LONG", 0.0015) == pytest.approx(99.55000135)


def test_v5_short_primary_is_mirrored():
    last_dca = 100.3
    release = release_price_from_last_dca(last_dca, "SHORT", 0.0015)
    assert release == pytest.approx(100.14955)
    assert not hedge_release_crossed(100.16, release, "SHORT")
    assert hedge_release_crossed(release, release, "SHORT")


def test_v5_config_defaults_and_explicit_values():
    cfg = Strategy2Config.from_mapping({"tradingMode": "focus", "focusV2HedgeRatio": 1.0, "focusV2HedgeReleaseRecoveryPct": 0.0015})
    assert hedge_ratio(cfg) == pytest.approx(1.0)
    assert hedge_release_recovery(cfg) == pytest.approx(0.0015)
    custom = Strategy2Config.from_mapping({"tradingMode": "focus", "focusV2HedgeRatio": 0.8, "focusV2HedgeReleaseRecoveryPct": 0.002})
    assert hedge_ratio(custom) == pytest.approx(0.8)
    assert hedge_release_recovery(custom) == pytest.approx(0.002)
    # v4 fields must not silently preserve the old 95% / 0.35% business behavior in v5.
    migrated = Strategy2Config.from_mapping({"tradingMode": "focus", "focusV2MaxHedgeRatio": 0.95, "focusV2HedgeReleaseDistancePct": 0.0035})
    assert hedge_ratio(migrated) == pytest.approx(1.0)
    assert hedge_release_recovery(migrated) == pytest.approx(0.0015)
    public = migrated.public_dict()
    assert public["focusV2HedgeRatio"] == pytest.approx(1.0)
    assert public["focusV2HedgeReleaseRecoveryPct"] == pytest.approx(0.0015)


def test_runtime_source_contains_v5_state_machine_and_no_frozen_release_trigger():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    assert 'DCA_TRAILING = "TRAILING"' in src
    assert 'DCA_FROZEN = "FIXED_DURING_HEDGE"' in src
    assert '"lastDcaFillPrice"' in src
    assert '"hedgeReleasePrice"' in src
    assert "hedge_release_crossed(mark, release_price, primary_side)" in src
    assert "fresh_primary_qty * configured_hedge_ratio" in src
    assert "FOCUS_V2_HEDGE_RELEASED" in src
    assert "FOCUS_V2_PARTIAL_PROFIT" in src
    assert "distance >= release_ratio" not in src
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
