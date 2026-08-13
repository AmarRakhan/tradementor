from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "deploy-cloud-staging.yml"
)
MAIN = Path(__file__).resolve().parent / "main.py"


def test_cloud_pipeline_is_pinned_to_isolated_staging():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "GCP_PROJECT_ID: tradementor-amar-20260813" in workflow
    assert "CLOUD_RUN_SERVICE: tradementor-staging-api" in workflow
    assert "FIREBASE_AUTH_PROJECT_ID: tradementor-production" in workflow
    assert "docker build --tag \"$IMAGE\" cloud_api" in workflow
    assert "docker push \"$IMAGE\"" in workflow
    assert "--image \"$IMAGE\"" in workflow
    assert "--service-account \"${{ vars.GCP_RUNTIME_SERVICE_ACCOUNT }}\"" in workflow
    assert "--allow-unauthenticated" in workflow
    assert "TRADEMENTOR_READ_SOURCE_URL=https://tradementor-api-604335232956.europe-west4.run.app" in workflow


def test_cloud_pipeline_cannot_enable_trading_or_schedulers():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for variable in (
        "TRADEMENTOR_ALLOW_LIVE=false",
        "ASTER_LIVE_EXECUTION_ENABLED=false",
        "ASTER_STRATEGY2_LIVE_ENABLED=false",
        "ASTER_STRATEGY3_LIVE_ENABLED=false",
        "MEXC_LIVE_EXECUTION_ENABLED=false",
    ):
        assert variable in workflow

    production_lines = [
        line for line in workflow.splitlines() if "tradementor-production" in line
    ]
    assert production_lines
    assert all(
        "FIREBASE_AUTH_PROJECT_ID" in line or "identityProject" in line
        for line in production_lines
    )
    assert "scheduler" not in workflow.lower()


def test_staging_read_source_is_wired_through_the_strict_allowlist():
    main = MAIN.read_text(encoding="utf-8")

    assert "from read_only_source import read_source_url" in main
    assert '@app.middleware("http")' in main
    assert "read_source_url(" in main
    assert 'os.getenv("TRADEMENTOR_READ_SOURCE_URL"' in main
