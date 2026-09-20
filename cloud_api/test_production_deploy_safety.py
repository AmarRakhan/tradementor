from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cloud-production.yml"


def workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_production_deploy_keeps_wif_and_no_stored_key_authentication():
    text = workflow()
    assert "google-github-actions/auth@v2" in text
    assert "workload_identity_provider:" in text
    assert "service_account:" in text
    assert "id-token: write" in text


def test_production_deploy_verifies_exact_source_commit_before_promotion():
    text = workflow()
    assert "source_commit:" in text
    assert "ref: ${{ inputs.source_commit }}" in text
    assert 'test "$(git rev-parse HEAD)" = "$REQUESTED_SOURCE_COMMIT"' in text
    assert 'git merge-base --is-ancestor "$SOURCE_COMMIT" "origin/amar-crypto-bot-2026-cloud"' in text
    assert '--build-arg "SOURCE_COMMIT=$SOURCE_COMMIT"' in text
    assert "TRADEMENTOR_SOURCE_COMMIT=$SOURCE_COMMIT" in text
    assert 'health["sourceCommit"] == os.environ["SOURCE_COMMIT"]' in text
    assert 'health["imageSourceCommit"] == os.environ["SOURCE_COMMIT"]' in text
    assert '--no-traffic' in text


def test_candidate_updates_runtime_and_image_source_commit_together():
    text = workflow()
    assert '--update-env-vars "TRADEMENTOR_SOURCE_COMMIT=$SOURCE_COMMIT,TRADEMENTOR_IMAGE_SOURCE_COMMIT=$SOURCE_COMMIT' in text
    assert '"TRADEMENTOR_IMAGE_SOURCE_COMMIT":os.environ["SOURCE_COMMIT"]' in text


def test_production_deploy_does_not_depend_on_database_or_exchange_availability_before_candidate():
    text = workflow()
    assert 'gcloud firestore databases describe --database="(default)"' not in text
    assert "https://fapi.asterdex.com/fapi/v3/exchangeInfo" not in text
    assert "DEPLOY_PHASE=aster-public-preflight" not in text


def test_production_deploy_captures_rollback_point_and_restores_it_on_failure():
    text = workflow()
    assert 'print(f"PREVIOUS_REVISION={live[\'revisionName\']}")' in text
    assert "PREVIOUS_SOURCE_COMMIT=" in text
    assert "PROMOTION_ATTEMPTED=true" in text
    assert "Roll back failed promotion" in text
    assert '--to-revisions "$PREVIOUS_REVISION=100"' in text
    assert 'os.environ["PREVIOUS_SOURCE_COMMIT"]' in text


def test_failed_candidate_never_receives_production_traffic():
    text = workflow()
    candidate_index = text.index("Deploy candidate without production traffic")
    verify_index = text.index("Verify candidate health and route contract")
    promote_index = text.index("Promote verified revision")
    assert candidate_index < verify_index < promote_index


def test_production_deploy_can_report_result_back_to_agent_issue():
    text = workflow()
    assert "request_issue:" in text
    assert "issues: write" in text
    assert 'gh issue comment "$REQUEST_ISSUE"' in text
    assert 'gh issue close "$REQUEST_ISSUE"' in text
    assert "Publish failed deployment to agent issue" in text
    assert "issue is intentionally left open for investigation" in text


def test_production_deploy_does_not_implicitly_ship_cloud_branch_head():
    text = workflow()
    assert 'required: true' in text[text.index("source_commit:"):text.index("request_issue:")]
    assert 'IMAGE="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/$ARTIFACT_REPOSITORY/tradementor-api:$SOURCE_COMMIT"' in text
    assert 'REVISION_SUFFIX="src-${SOURCE_COMMIT:0:8}-$RUN_SUFFIX"' in text
    assert 'echo "- Source commit: $SOURCE_COMMIT"' in text


def test_exact_current_source_reuses_existing_live_image_for_noop_proof():
    text = workflow()
    assert "Select exact image strategy" in text
    assert 'if [ "$SOURCE_COMMIT" = "$PREVIOUS_SOURCE_COMMIT" ]; then' in text
    assert 'gcloud run revisions describe "$PREVIOUS_REVISION"' in text
    assert 'echo "REUSE_LIVE_IMAGE=true"' in text
    assert 'echo "IMAGE=$PREVIOUS_IMAGE"' in text
    assert "if: env.REUSE_LIVE_IMAGE != 'true'" in text
    assert 'echo "- Image mode: $DEPLOYMENT_PROOF_MODE"' in text


def test_production_deploy_reports_failure_phase_without_expanding_deploy_identity():
    text = workflow()
    assert 'Failed phase: ${DEPLOY_PHASE:-unknown}' in text
    assert "DEPLOY_PHASE=capture-service-metadata" in text
    assert "DEPLOY_PHASE=capture-iam-policy" in text
    assert "DEPLOY_PHASE=capture-current-health" in text
    assert "DEPLOY_PHASE=select-image" in text
    assert "DEPLOY_PHASE=deploy-candidate" in text
    assert "DEPLOY_PHASE=verify-candidate" in text
    assert "DEPLOY_PHASE=promote" in text
    assert "DEPLOY_PHASE=verify-production" in text


def test_current_production_health_capture_is_retryable_and_http_verified():
    text = workflow()
    assert 'PREVIOUS_HEALTH_HTTP=' in text
    assert '--retry 8' in text
    assert '--retry-all-errors' in text
    assert '--connect-timeout 10' in text
    assert '--max-time 30' in text
    assert 'test "$PREVIOUS_HEALTH_HTTP" = "200"' in text
    assert 'json.load(open(sys.argv[1], encoding="utf-8"))' in text


def test_current_health_uses_same_step_service_url_not_future_github_env():
    text = workflow()
    local_url = 'SERVICE_URL="$(python -c \'import json,sys; d=json.load(open(sys.argv[1],encoding="utf-8")); print(d["status"]["url"])\' "$RUNNER_TEMP/service-before.json")"'
    assert local_url in text
    assert 'test -n "$SERVICE_URL"' in text
    assert text.index(local_url) < text.index('PREVIOUS_HEALTH_HTTP=')
