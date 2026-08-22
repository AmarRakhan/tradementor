from pathlib import Path


def _dedicated_strategy3_scheduler_source() -> str:
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    start = source.index('@app.post("/internal/aster-strategy3/tick")')
    end = source.index('@app.post("/internal/aster-automation/{uid}/simulate")', start)
    return source[start:end]


def test_retired_strategy3_scheduler_is_hard_disabled() -> None:
    block = _dedicated_strategy3_scheduler_source()
    assert 'raise HTTPException(410, "Strategy 3 is retired; Strategy 2 is the only Aster runtime")' in block
    assert 'db.collection("asterStrategy3")' not in block
    assert "_run_aster_strategy3_tick" not in block
    assert 'ASTER_STRATEGY3_LIVE_ENABLED' not in block
    assert 'ASTER_STRATEGY3_RUNTIME_ENABLED' not in block


def test_retired_strategy3_scheduler_cannot_process_rapid_build_requests() -> None:
    block = _dedicated_strategy3_scheduler_source()
    assert '"rapidBuildRequested": False' not in block
    assert "_run_strategy3_rapid_batch" not in block
    assert "HTTPException(410" in block


def test_readiness_rearm_preserves_isolated_runtime_boundaries() -> None:
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")

    assert "auth_app = identity_app(" in source
    assert "app=auth_app" in source
    assert "recent_id_token(" in source
    assert "maximum_age_seconds=600" in source
    assert "existing_data_read_bridge" in source
    assert '@app.post("/internal/aster-strategy3/tick")' in source

    assert 'account_authorized=bool(existing.get("canaryValidated")) and bool(existing.get("liveAccountAuthorized"))' in source
    assert 'revalidated=account_authorized and bool(report.get("liveReady"))' in source
    assert '"liveReady":revalidated' in source
    assert '"paperOnly":not account_authorized' in source

    assert 'probe_symbol=(owned_symbols or active_symbols or ["BTCUSDT"])[0]' in source
    assert "client.all_orders(probe_symbol,limit=1)" in source
    assert "client.user_trades(probe_symbol,limit=5)" in source
    assert "client.income_history(limit=50)" in source
