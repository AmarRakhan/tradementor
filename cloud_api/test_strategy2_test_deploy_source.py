from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cloud-strategy2-test-live.yml"
MAIN = ROOT / "cloud_api" / "main.py"
TEST_ENTRYPOINT = ROOT / "cloud_api" / "strategy2_test_entrypoint.py"
NON_TEST_DEPLOYMENTS = (
    ROOT / ".github" / "workflows" / "deploy-cloud-production.yml",
    ROOT / ".github" / "workflows" / "deploy-cloud-staging.yml",
    ROOT / ".github" / "workflows" / "deploy-cloud-live-canary.yml",
)


def test_version_42_workflow_builds_the_exact_triggering_cloud_branch_commit():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "ref: ${{ github.sha }}" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in workflow
    assert 'test "$GITHUB_REF_NAME" = "amar-crypto-bot-2026-cloud"' in workflow
    assert "test-aster-position-capacity-v41" not in workflow


def test_strategy2_start_and_status_read_the_same_firestore_document():
    source = MAIN.read_text(encoding="utf-8")
    bridge = (ROOT / "cloud_api" / "read_only_source.py").read_text(encoding="utf-8")
    entrypoint = TEST_ENTRYPOINT.read_text(encoding="utf-8")
    reference = source[source.index("def aster_strategy2_reference"):source.index("def aster_strategy3_reference")]
    status = source[source.index('@app.get("/v1/me/aster/status")'):source.index('@app.post("/v1/me/aster/strategy2/replays")')]
    start = source[source.index('@app.post("/v1/me/aster/strategy2/start")'):source.index('@app.post("/v1/me/aster/strategy2/stop")')]
    assert 'db.collection("asterStrategy2").document(uid)' in reference
    assert "aster_strategy2_reference(uid).get()" in status
    assert "ref=aster_strategy2_reference(uid)" in start
    assert "ensure_aster_strategy2_control(uid)" in status
    assert '"strategy2-test-live": frozenset({"/v1/me/aster/status"})' in bridge
    assert 'environment=os.getenv("TRADEMENTOR_ENVIRONMENT", "")' in entrypoint


def test_missing_linked_account_registration_never_enables_trading():
    source = MAIN.read_text(encoding="utf-8")
    registration = source[source.index("def ensure_aster_strategy2_control"):source.index("def _record_aster_order_attribution")]
    assert '"enabled":False' in registration
    assert '"monitor":False' in registration
    assert '"liveReady":False' in registration
    assert '"canaryValidated":False' in registration
    assert "ref.create(initial)" in registration
    assert "ref.set(" not in registration


def test_isolated_strategy2_scheduler_route_exists_and_is_fail_closed():
    route = TEST_ENTRYPOINT.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'control_plane.verify_internal_cloud_request(authorization)' in route
    assert 'environment == "strategy2-test-live"' in route
    assert 'os.getenv("ASTER_STRATEGY2_LIVE_ENABLED", "false")' in route
    assert 'os.getenv("ASTER_STRATEGY3_LIVE_ENABLED", "false")' in route
    assert 'os.getenv("ASTER_STRATEGY3_RUNTIME_ENABLED", "false")' in route
    assert 'return {"processed": 0, "status": "centrally-disabled"' in route
    assert 'control_plane.db.collection("asterStrategy2")' in route
    assert 'db.collection("asterAutomation")' not in route
    assert '_run_aster_strategy3_tick' not in route
    assert "ASTER_STRATEGY2_EXCLUSIVE_OWNERSHIP=true" in workflow


def test_push_deploy_verifies_route_without_interrupting_an_enabled_scheduler():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    resume = (ROOT / ".github" / "workflows" / "resume-strategy2-test-live.yml").read_text(encoding="utf-8")
    assert '"/internal/aster-strategy2/tick"' in workflow
    assert 'strategy2_test_entrypoint:app' in workflow
    assert 'openapi["paths"]' in workflow
    assert 'INITIAL_STATE="$(gcloud scheduler jobs describe' in workflow
    assert 'assert job["state"] == initial_state' in workflow
    assert '= "$SCHEDULER_INITIAL_STATE"' in workflow
    assert "gcloud scheduler jobs pause" in workflow  # new-job bootstrap only
    assert 'test "$(gcloud scheduler jobs describe' in workflow
    assert "gcloud scheduler jobs resume" not in workflow
    assert workflow.count("--retry-all-errors") >= 2
    shared_group = "group: tradementor-strategy2-test-live-control"
    assert shared_group in workflow
    assert shared_group in resume
    assert "Prove a fresh successful Strategy 2 scheduler execution" in resume
    assert 'gcloud scheduler jobs run "$SCHEDULER_JOB"' in resume
    assert 'last_attempt and last_attempt != before' in resume
    assert 'job["state"] == "ENABLED"' in resume
    assert 'code in {0, None}' in resume
    existing_job = workflow[workflow.index('if gcloud scheduler jobs describe'):workflow.index('else', workflow.index('if gcloud scheduler jobs describe'))]
    assert "gcloud scheduler jobs pause" not in existing_job


def test_strategy2_test_only_publication_cannot_deploy_other_cloud_environments():
    guard = (
        "github.event_name != 'push' || "
        "!contains(github.event.head_commit.message, '[strategy2-test-only]')"
    )
    for deployment in NON_TEST_DEPLOYMENTS:
        workflow = deployment.read_text(encoding="utf-8")
        assert guard in workflow
