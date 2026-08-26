from pathlib import Path


def test_strategy2_public_exposes_only_persisted_focus_shadow_evidence():
    source=Path(__file__).with_name("main.py").read_text()
    assert '"focus":{"state":raw.get("focusShadowState"' in source
    assert '"report":raw.get("focusShadowReport"' in source
    assert '"metrics":raw.get("focusShadowMetrics"' in source
    assert '"ordersSent":0' in source
