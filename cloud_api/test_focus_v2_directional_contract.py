from pathlib import Path

ENGINE=Path(__file__).with_name("aster_strategy2_focus_v2.py").read_text()

def test_simple_release_is_directional_without_fixed_recovery_gate():
    start=ENGINE.index("# Simple Focus 2.0 is directional")
    end=ENGINE.index("# No recovery:", start)
    block=ENGINE[start:end]
    assert "direction_up=bool(state.recent_low>0 and mark>state.recent_low)" in block
    assert "release_pending=bool(direction_up and middle_ok" in block
    assert "release_pending=bool(recovery_ok" not in block
    assert block.index("_arm_rehedge(") < block.index("_close_v2_leg(")

def test_directional_status_contract():
    assert "OMHOOG · SHORT VRIJ · LONG-ONLY" in ENGINE
    assert "OMLAAG · SHORT BESCHERMT" in ENGINE
    assert "FOCUS_V2_REHEDGE_RESTORED" in ENGINE
