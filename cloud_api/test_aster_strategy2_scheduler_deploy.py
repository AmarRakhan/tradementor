from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_deploy_configures_scheduler_paused_then_verifies_and_resumes():
    workflow = (ROOT / ".github/workflows/deploy-cloud-production.yml").read_text(encoding="utf-8")
    assert "GCP_PROJECT_ID: tradementor-production" in workflow
    assert "GCP_REGION: europe-west4" in workflow
    assert "CLOUD_RUN_SERVICE: tradementor-api" in workflow
    assert "SCHEDULER_JOB: tradementor-aster-automation-tick" in workflow
    assert 'TARGET="$SERVICE_URL/internal/aster-automation/tick"' in workflow
    assert '--oidc-service-account-email "$RUNTIME_SERVICE_ACCOUNT"' in workflow
    assert '--oidc-token-audience "$SERVICE_URL"' in workflow
    assert 'job["state"] == "PAUSED"' in workflow
    assert '--uri "$SERVICE_URL/health"' in workflow
    assert '--http-method GET' in workflow
    assert 'gcloud scheduler jobs pause "$SCHEDULER_JOB"' in workflow
    assert "--paused" not in workflow
    assert workflow.index("Configure paused one-minute") < workflow.index("Verify paused scheduler")
    assert workflow.index("Verify paused scheduler") < workflow.index("Promote verified revision")
    assert workflow.index("Promote verified revision") < workflow.index("Resume verified Strategy 1 and 2 scheduler")


def test_production_scheduler_requires_live_s2_boundary_and_rejects_s3_target():
    workflow = (ROOT / ".github/workflows/deploy-cloud-production.yml").read_text(encoding="utf-8")
    assert 'variables.get("ASTER_LIVE_EXECUTION_ENABLED") == "true"' in workflow
    assert 'variables.get("ASTER_STRATEGY2_LIVE_ENABLED") == "true"' in workflow
    assert 'variables.get("ASTER_STRATEGY3_LIVE_ENABLED")' not in workflow
    assert '"/internal/aster-strategy3/tick" not in job["httpTarget"]["uri"]' in workflow


def test_production_scheduler_endpoint_never_processes_isolated_strategy3():
    source = (ROOT / "cloud_api/main.py").read_text(encoding="utf-8")
    start = source.index('@app.post("/internal/aster-automation/tick")')
    end = source.index('@app.post("/internal/aster-strategy3/tick")', start)
    block = source[start:end]
    assert "_run_aster_strategy2_tick" in block
    assert "_run_aster_strategy3_tick" not in block
    assert '"strategy3Isolated":True' in block
