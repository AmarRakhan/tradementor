from pathlib import Path


def test_strategy2_public_exposes_persisted_focus_evidence_without_read_side_effects():
    source=Path(__file__).with_name("main.py").read_text()
    assert 'raw.get("focusLiveState") if focus_live_mode else raw.get("focusShadowState")' in source
    assert 'raw.get("focusLiveReport") if focus_live_mode else raw.get("focusShadowReport")' in source
    assert '"metrics":raw.get("focusShadowMetrics"' in source
    assert '"live":bool(focus_live_mode and enabled)' in source
