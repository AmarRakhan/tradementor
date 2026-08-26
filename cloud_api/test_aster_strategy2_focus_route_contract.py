from pathlib import Path


def test_focus_shadow_route_is_read_only_and_fail_closed():
    source = Path(__file__).with_name("main.py").read_text()
    assert '@app.get("/v1/me/aster/strategy2/focus/shadow")' in source
    assert 'build_focus_shadow_report' in source
    assert 'live_authorized=False' in source
    assert 'report["ordersSent"]=0' in source
    assert 'report["readOnly"]=True' in source
    assert 'settings.trading_mode!="focus" or not settings.focus_shadow_enabled' in source
