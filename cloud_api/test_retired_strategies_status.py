from pathlib import Path


def test_aster_status_excludes_retired_strategy_runtime_and_projection_data():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    route = source[source.index("def aster_status("):source.index('@app.get("/v1/me/aster/trade-events")')]
    assert "aster_strategy3_reference" not in route
    assert "strategy3_position_tp_contract" not in route
    assert "aster_strategy3_public" not in route
    assert "aster_automation_public" not in route
    assert 'for strategy_state in (strategy2_state,):' in route
    assert '**aster_strategy2_public(uid)' in route
    assert '"activePositions": len(positions)' in route
    assert '"Strategy 3' not in route
    assert 'strategy3_state' not in route
    assert 'timedelta(seconds=30)' in route


def test_strategy2_tick_uses_retired_ownership_only_for_one_way_normalization():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    tick = source[source.index("def _run_aster_strategy2_tick("):source.index("def _aster_brackets(")]
    assert tick.count("aster_strategy3_reference(uid)") == 1
    assert "LEGACY_OWNERSHIP_NORMALIZED_TO_STRATEGY2" in tick
    assert "_explicit_strategy1_owned_keys" not in tick
    assert 's3_keys:set[tuple[str,str]]=set()' in tick
    assert 's1_keys:set[tuple[str,str]]=set()' in tick
    assert "botst met Strategy 3" not in tick


def test_production_aster_scheduler_never_runs_retired_strategy1():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    scheduler = source[source.index("def run_aster_automation_scheduler("):source.index('@app.post("/internal/aster-strategy2/{uid}/simulate")')]
    assert 'db.collection("asterAutomation")' not in scheduler
    assert "_run_aster_automation_tick" not in scheduler
    assert 'db.collection("asterStrategy2")' in scheduler
