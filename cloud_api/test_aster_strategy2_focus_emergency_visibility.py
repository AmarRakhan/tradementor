from pathlib import Path


def test_focus_owned_leg_remains_visible_to_account_emergency_reduction():
    source=Path("aster_strategy2_runtime.py").read_text()
    assert 'managed=[x for x in owned if not (config.trading_mode=="focus" and str(x.role).upper().startswith("FOCUS"))]' in source
    assert 'candidate=next((x for x in owned if x.side==overweight),None)' in source
