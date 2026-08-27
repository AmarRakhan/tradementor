from pathlib import Path


def test_focus_live_is_wired_into_strategy2_scheduler_and_keeps_queue_boundary():
    source=Path("main.py").read_text()
    assert "from aster_strategy2_focus_live import run_focus_live_step" in source
    assert "focus_result=run_focus_live_step" in source
    assert "order_budget=order_budget,reserve_order=focus_queue_reserver,open_orders=orders" in source
    assert 'settings.trading_mode=="focus" and enabled' in source
    assert 'seat_shortage=len(owned)<settings.maximum_pairs' in source
    assert 'if settings.trading_mode=="focus":seat_shortage=False' in source


def test_focus_live_public_status_and_read_only_market_route_exist():
    source=Path("main.py").read_text()
    assert 'focusLiveState' in source
    assert 'focusLiveReport' in source
    assert '/v1/me/aster/strategy2/focus/markets' in source
    assert 'live_authorized=False' in source


def test_legacy_management_excludes_focus_owned_leg_only_while_focus_mode_active():
    source=Path("aster_strategy2_runtime.py").read_text()
    assert 'config.trading_mode=="focus" and str(item.role).upper().startswith("FOCUS")' in source
    assert 'config.trading_mode=="focus" and str(leg.role).upper().startswith("FOCUS")' in source
