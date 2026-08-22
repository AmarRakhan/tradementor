from pathlib import Path


def test_retired_strategy3_runtime_has_no_active_scheduler_or_user_routes() -> None:
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    assert '/internal/aster-strategy3/tick' not in source
    assert 'def _run_aster_strategy3_tick' not in source
    for route in ("settings", "simulate", "readiness", "canary", "start", "rapid-build", "stop"):
        assert f'/v1/me/aster/strategy3/{route}' not in source
    assert "from aster_strategy3 import" not in source
    assert "from aster_strategy3_execution import" not in source
