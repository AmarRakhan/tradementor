from pathlib import Path


def test_legacy_focus_runtime_is_not_reachable_from_scheduler():
    source=Path(__file__).with_name("main.py").read_text()
    gate='if str(raw_settings.get("engine",raw_settings.get("strategyKind","")))!=MULTI_BB_ENGINE:'
    dispatch='return run_multi_bb_step(client=client,ref=ref,raw_state=raw,settings=settings'
    assert gate in source and dispatch in source
    assert source.index(gate) < source.index(dispatch) < source.index("# Realtime Simple Mode")


def test_save_switch_disarms_legacy_before_user_start():
    source=Path(__file__).with_name("main.py").read_text()
    # A true engine migration must still be fail-safe: the new Multi-DCA config
    # is stored, but live execution and monitoring are explicitly disarmed and
    # prior Multi-BB position state is cleared. Live edits on the same engine
    # take the separate state-preserving branch.
    assert 'switching=str(old.get("engine",old.get("strategyKind","")))!=MULTI_BB_ENGINE' in source
    assert '"enabled":False,"monitor":False,"multiBbPositions":{}' in source
    assert '"phase":"CONFIGURED"' in source
    assert '"Nieuwe Multi DCA-strategie opgeslagen; start de bot handmatig wanneer je klaar bent"' in source
    assert '"activeStatePreserved":not switching' in source
