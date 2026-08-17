from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = {
    "deploy-cloud-production.yml": "DEPLOY_PRODUCTION_BACKEND",
    "deploy-cloud-staging.yml": "DEPLOY_CLOUD_STAGING",
    "deploy-cloud-live-canary.yml": "DEPLOY_LIVE_CANARY",
    "deploy-cloud-strategy2-test-live.yml": "DEPLOY_STRATEGY2_TEST_LIVE",
}


def test_cloud_deployments_are_manual_only_and_confirmation_gated():
    for filename, confirmation in WORKFLOWS.items():
        workflow = (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
        trigger = workflow.split("permissions:", 1)[0]
        assert "workflow_dispatch:" in trigger
        assert "push:" not in trigger
        assert "pull_request:" not in trigger
        assert 'test "$GITHUB_EVENT_NAME" = "workflow_dispatch"' in workflow
        assert f'test "${{{{ inputs.confirmation }}}}" = "{confirmation}"' in workflow


def test_push_cloud_backend_workflow_can_only_run_tests():
    workflow = (ROOT / ".github" / "workflows" / "cloud-backend-ci.yml").read_text(
        encoding="utf-8"
    )
    assert "push:" in workflow
    assert "pull_request:" in workflow
    assert "pytest -q" in workflow
    assert "id-token: write" not in workflow
    for forbidden in (
        "gcloud",
        "docker build",
        "docker push",
        "run deploy",
        "update-traffic",
        "scheduler jobs",
        "workflow_dispatch:",
    ):
        assert forbidden not in workflow
