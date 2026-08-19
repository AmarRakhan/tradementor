from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cloud-strategy2-test-live.yml"
MAIN = ROOT / "cloud_api" / "main.py"
DOCKERFILE = ROOT / "cloud_api" / "Dockerfile"
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


def test_strategy2_test_auto_publish_is_branch_and_path_scoped():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    trigger = workflow.split("permissions:", 1)[0]
    assert "push:" in trigger
    assert "- amar-crypto-bot-2026-cloud" in trigger
    assert '      - "cloud_api/**"' in trigger
    assert "pull_request:" not in trigger
    assert 'case "$GITHUB_EVENT_NAME" in' in workflow
    assert 'test "$GITHUB_REF" = "refs/heads/amar-crypto-bot-2026-cloud"' in workflow


def test_deployment_proves_exact_commit_and_money_grabber_routes():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    source = MAIN.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert '"sourceCommit": os.getenv("TRADEMENTOR_SOURCE_COMMIT") or None' in source
    assert '"imageSourceCommit": os.getenv("TRADEMENTOR_IMAGE_SOURCE_COMMIT") or None' in source
    assert "ARG SOURCE_COMMIT=unknown" in dockerfile
    assert "ENV TRADEMENTOR_IMAGE_SOURCE_COMMIT=$SOURCE_COMMIT" in dockerfile
    assert '--build-arg "SOURCE_COMMIT=$TEST_COMMIT"' in workflow
    assert 'IMAGE_REPOSITORY="${IMAGE%:*}"' in workflow
    assert 'IMAGE=$IMAGE_REPOSITORY@$DIGEST' in workflow
    assert 'TRADEMENTOR_SOURCE_COMMIT=$GITHUB_SHA' in workflow
    assert 'health["sourceCommit"] == os.environ["GITHUB_SHA"]' in workflow
    assert 'health["imageSourceCommit"] == os.environ["GITHUB_SHA"]' in workflow
    assert 'variables["TRADEMENTOR_SOURCE_COMMIT"] == os.environ["GITHUB_SHA"]' in workflow
    assert '--revision-suffix "$REVISION_SUFFIX"' in workflow
    assert '"/v1/me/aster/strategy2/money-grabber/activation-preview"' in workflow
    assert '"/v1/me/aster/strategy2/money-grabber/start-round"' in workflow
    assert '"/v1/me/aster/strategy2/money-grabber/shadow"' in workflow


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


def test_completed_canary_authorization_survives_transient_readiness_and_open_orders():
    source = MAIN.read_text(encoding="utf-8")
    tick = source[source.index("def _run_aster_strategy2_tick"):source.index("def aster_automation_public")]
    readiness = source[source.index('def aster_strategy2_readiness('):source.index('@app.post("/v1/me/aster/strategy2/canary")')]
    assert 'if live and (not canary_authorized or not central_live_enabled)' in tick
    assert '"liveReadyRecoveryReason":"COMPLETED_CANARY_AUTHORIZATION"' in tick
    assert 'management_owned=[leg for leg in management_owned if (leg.symbol,leg.side) not in open_order_keys]' in tick
    assert tick.index('if selected:') < tick.index('if orders:')
    assert 'durable_live_ready=bool(raw.get("canaryValidated",False))' in readiness
    assert '"liveReady":report["liveReady"]' not in readiness


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
    assert 'MEXC_INTERNAL_AUDIENCE=$STRATEGY2_INTERNAL_AUDIENCE' in workflow
    assert 'variables["MEXC_INTERNAL_AUDIENCE"] == sys.argv[3]' in workflow
    assert "gcloud scheduler jobs update" not in workflow
    assert "gcloud scheduler jobs create" not in workflow
    assert "gcloud scheduler jobs pause" not in workflow
    assert "gcloud scheduler jobs resume" not in workflow
    assert "gcloud scheduler jobs run" not in workflow
    assert 'assert job["httpTarget"]["oidcToken"]["audience"] == service_url' in workflow
    assert 'assert job["httpTarget"]["oidcToken"]["serviceAccountEmail"] == runtime_service_account' in workflow
    assert workflow.count("--retry-all-errors") >= 2
    shared_group = "group: tradementor-strategy2-test-live-control"
    assert shared_group in workflow
    assert shared_group in resume
    assert "Prove a fresh successful Strategy 2 scheduler execution" in resume
    assert 'gcloud scheduler jobs run "$SCHEDULER_JOB"' in resume
    assert 'last_attempt and last_attempt != before' in resume
    assert 'job["state"] == "ENABLED"' in resume
    assert 'code in {0, None}' in resume


def test_strategy2_test_only_publication_cannot_deploy_other_cloud_environments():
    for deployment in NON_TEST_DEPLOYMENTS:
        workflow = deployment.read_text(encoding="utf-8")
        trigger = workflow.split("permissions:", 1)[0]
        assert "workflow_dispatch:" in trigger
        assert "push:" not in trigger


def test_strategy2_candidate_rejections_are_isolated_and_visible():
    source = MAIN.read_text(encoding="utf-8")
    tick = source[source.index("def _run_aster_strategy2_tick"):source.index("def aster_automation_public")]
    assert 'entryCandidateCooldowns' in tick
    assert 'fingerprint' in tick
    assert 'advancedWithinTick' in tick
    assert 'accountPositionCount' in tick
    assert 'provenStrategy2LegCount' in tick
    assert 'ENTRY_CANDIDATE_REJECTED' in tick
    assert 'errorCode' in tick and 'action":"OPEN"' in tick
    assert 'continue' in tick[tick.index('ENTRY_CANDIDATE_REJECTED'):]
    assert 'except Exception as exc' in tick


def test_confirmed_fill_and_strategy2_ownership_are_committed_atomically():
    source = MAIN.read_text(encoding="utf-8")
    tick = source[source.index("def _run_aster_strategy2_tick"):source.index("def aster_automation_public")]
    start = tick.index('audit_ref=ref.collection("audit").document()')
    end = tick.index('batch.commit()', start) + len('batch.commit()')
    atomic = tick[start:end]
    assert 'batch.set(ref,{"ownedLegs"' in atomic
    assert 'batch.set(audit_ref' in atomic
    assert atomic.count('batch.commit()') == 1


def test_proven_refresh_race_is_reconciled_before_exclusive_completeness_check():
    source = MAIN.read_text(encoding="utf-8")
    tick = source[source.index("def _run_aster_strategy2_tick"):source.index("def aster_automation_public")]
    recovery = tick.index("owned,recovered_ownership=recover_audited_ownership")
    exclusive = tick.index('exclusive=os.getenv("ASTER_STRATEGY2_EXCLUSIVE_OWNERSHIP"')
    assert recovery < exclusive
    recovered_block = tick[recovery:exclusive]
    assert "audit_events=audit_events,fills=fills" in recovered_block
    assert "recovery_batch.set(ref" in recovered_block
    assert '"OWNERSHIP_RECOVERED_FROM_AUDIT"' in recovered_block
    assert "recovery_batch.commit()" in recovered_block


def test_strategy2_candidate_logic_has_no_account_symbol_or_amount_exception():
    source = MAIN.read_text(encoding="utf-8")
    tick = source[source.index("def _run_aster_strategy2_tick"):source.index("def aster_automation_public")]
    for forbidden in ('BULLAUSDT','CRDOUSDT','PLTRUSDT','hotmail.com','gmail.com'):
        assert forbidden not in tick
    assert 'settings.base_notional' in tick
    assert 'maximum_pairs' in tick
