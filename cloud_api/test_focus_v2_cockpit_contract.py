from pathlib import Path

HERE=Path(__file__).resolve().parent


def test_focus_v2_runtime_persists_read_only_recovery_evidence():
    src=(HERE/'aster_strategy2_focus_v2.py').read_text()
    for token in ('bollinger5mMiddle','recoveryReboundPrice','recoveryPriceMet','bollinger5mConfirmed','portfolioRecoveryMet','shortReleaseReady','rehedgeArmed'):
        assert token in src
    assert 'recovery_confirmed(' in src


def test_aster_status_exposes_focus_v2_cockpit_from_runtime_truth():
    src=(HERE/'main.py').read_text()
    assert '"focusV2Cockpit": focus_v2_cockpit' in src
    for token in ('nextLongDcaPrice','nextLongDcaDistancePct','longBreakEvenPrice','nextShortReleasePrice','grossExposure','hedgeRatio','cyclePnl','nextAction','recentActions'):
        assert token in src
    assert 'next_dca_trigger(' in src
    assert 'cycleTargetActive":False' in src


def test_focus_v2_fill_prefix_is_preserved_for_historical_chart_attribution():
    src=(HERE/'aster_history.py').read_text()
    assert 'lowered.startswith("s2fv2-")' in src
    assert 'Strategy 2 · Focus 2.0' in src
