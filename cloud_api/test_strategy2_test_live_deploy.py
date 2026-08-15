from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/deploy-cloud-strategy2-test-live.yml"
MAIN = ROOT / "cloud_api/main.py"


def test_shared_live_test_is_isolated_and_strategy2_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "GCP_PROJECT_ID: tradementor-amar-20260813" in workflow
    assert "CLOUD_RUN_SERVICE: tradementor-strategy2-test-live-api" in workflow
    assert "SCHEDULER_JOB: tradementor-strategy2-test-live-tick" in workflow
    assert 'TARGET="$SERVICE_URL/internal/aster-strategy2/tick"' in workflow
    assert "TRADEMENTOR_ALLOW_LIVE=true" in workflow
    assert "ASTER_LIVE_EXECUTION_ENABLED=true" in workflow
    assert "ASTER_STRATEGY2_LIVE_ENABLED=true" in workflow
    assert "ASTER_CANARY_ENABLED=true" in workflow
    assert "ASTER_STRATEGY3_LIVE_ENABLED=false" in workflow
    assert "ASTER_STRATEGY3_RUNTIME_ENABLED=false" in workflow
    assert "MEXC_LIVE_EXECUTION_ENABLED=false" in workflow


def test_shared_live_test_scheduler_endpoint_never_processes_other_strategies():
    source = MAIN.read_text(encoding="utf-8")
    start = source.index('@app.post("/internal/aster-strategy2/tick")')
    end = source.index('@app.post("/internal/aster-strategy3/tick")', start)
    block = source[start:end]
    assert "_run_strategy2_scheduler_batch" in block
    assert "_run_aster_automation_tick" not in block
    assert "_run_aster_strategy3_tick" not in block
    assert '"strategy3Isolated":True' in block


def test_strategy2_requires_all_three_server_live_gates():
    source = MAIN.read_text(encoding="utf-8")
    start = source.index("def _strategy2_live_runtime_enabled")
    end = source.index("def aster_strategy2_public", start)
    block = source[start:end]
    for variable in (
        "TRADEMENTOR_ALLOW_LIVE",
        "ASTER_LIVE_EXECUTION_ENABLED",
        "ASTER_STRATEGY2_LIVE_ENABLED",
    ):
        assert variable in block
