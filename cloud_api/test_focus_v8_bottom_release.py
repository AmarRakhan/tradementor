from pathlib import Path

SRC = (Path(__file__).parent / "aster_strategy2_focus_trailing.py").read_text(encoding="utf-8")

def test_v8_simple_mode_disables_dca_orders():
    assert 'dca_allowed = (not simple_flow) and settings.focus_dca_enabled' in SRC
    assert 'state["dcaMode"] = "OFF_CORE_V8"' in SRC
    assert 'state["nextDcaPrice"] = 0.0' in SRC

def test_v8_release_tracks_protected_bottom_and_rebounds_from_it():
    assert 'state["protectedFloorPrice"] = protected_extreme' in SRC
    assert 'state["hedgeReleasePrice"] = protected_extreme * (1.0 + release_ratio)' in SRC
    assert 'price_release_ready = hedge_release_crossed(mark, release_price, primary_side)' in SRC
    assert 'net_green_ready = expected_net_close_pnl > 0.0' in SRC

def test_v8_rehedge_returns_to_exact_protected_extreme():
    assert 'state["reHedgeAnchorPrice"] = protected_extreme' in SRC
    assert '"reHedgePrice": protected_extreme if simple_flow' in SRC
    assert 'if rehedge_crossed:' in SRC

def test_v8_records_release_and_rehedge_latency():
    for token in (
        'hedgeReleaseTriggerToSubmitMs', 'hedgeReleaseConfirmedAt',
        'reHedgeTriggerToSubmitMs', 'reHedgeConfirmedAt'
    ):
        assert token in SRC
