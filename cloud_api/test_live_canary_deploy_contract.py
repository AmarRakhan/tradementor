from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cloud-live-canary.yml"


def test_canary_service_is_separate_and_manually_bounded():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "CLOUD_RUN_SERVICE: tradementor-live-canary-api" in workflow
    assert "TRADEMENTOR_ENV=live-canary" in workflow
    assert "ASTER_STRATEGY3_CANARY_ENABLED=true" in workflow
    assert "ASTER_STRATEGY3_RUNTIME_ENABLED=false" in workflow
    assert "TRADEMENTOR_ALLOW_LIVE=false" in workflow
    assert "ASTER_LIVE_EXECUTION_ENABLED=false" in workflow
    assert "ASTER_STRATEGY2_LIVE_ENABLED=false" in workflow
    assert "ASTER_STRATEGY3_LIVE_ENABLED=false" in workflow
    assert "MEXC_LIVE_EXECUTION_ENABLED=false" in workflow
    assert "MEXC_AUTOMATION_EXECUTION_ENABLED=false" in workflow
    assert "scheduler" not in workflow.lower().replace(
        "continuous live orders and every scheduler remain disabled.", ""
    )


def test_workflow_verifies_the_deployed_runtime_boundary():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'variables["ASTER_STRATEGY3_CANARY_ENABLED"] == "true"' in workflow
    assert 'variables["ASTER_STRATEGY3_RUNTIME_ENABLED"] == "false"' in workflow
    assert 'health["ordersEnabled"] is False' in workflow
