from pathlib import Path


def _dedicated_strategy3_scheduler_source() -> str:
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    start = source.index('@app.post("/internal/aster-strategy3/tick")')
    end = source.index('@app.post("/internal/aster-automation/{uid}/simulate")', start)
    return source[start:end]


def test_dedicated_scheduler_is_strategy3_only() -> None:
    block = _dedicated_strategy3_scheduler_source()
    assert 'db.collection("asterStrategy3")' in block
    assert "_run_aster_strategy3_tick" in block
    assert 'os.getenv("ASTER_STRATEGY3_LIVE_ENABLED"' in block
    assert 'os.getenv("ASTER_STRATEGY3_RUNTIME_ENABLED"' in block

    assert 'db.collection("asterAutomation")' not in block
    assert 'db.collection("asterStrategy2")' not in block
    assert "_run_aster_automation_tick" not in block
    assert "_run_aster_strategy2_tick" not in block
    assert "_run_strategy3_rapid_batch" not in block


def test_dedicated_scheduler_clears_rapid_build_requests() -> None:
    block = _dedicated_strategy3_scheduler_source()
    assert '"rapidBuildRequested": False' in block
    assert "normal one-action ticks only" in block
