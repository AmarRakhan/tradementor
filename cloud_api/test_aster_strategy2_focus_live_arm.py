from pathlib import Path


def test_legacy_focus_runtime_is_not_reachable_from_scheduler():
    source=Path(__file__).with_name("main.py").read_text()
    gate='if str(raw_settings.get("engine",raw_settings.get("strategyKind","")))!=MULTI_BB_ENGINE:'
    dispatch='return run_multi_bb_step(client=client,ref=ref,raw_state=raw,settings=settings'
    assert gate in source and dispatch in source
    assert source.index(gate) < source.index(dispatch) < source.index("# Realtime Simple Mode")


def test_save_switch_disarms_legacy_before_user_start():
    source=Path(__file__).with_name("main.py").read_text()
    assert 'if switching: update.update({"enabled":False,"monitor":False,"multiBbPositions":{}})' in source
    assert '"Legacy strategie verwijderd; nieuwe Multi BB-configuratie vereist"' in source
