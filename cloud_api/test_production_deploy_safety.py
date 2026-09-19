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
    assert '--build-arg "SOURCE_COMMIT=$GITHUB_SHA"' in text
    assert "TRADEMENTOR_SOURCE_COMMIT=$GITHUB_SHA" in text
    assert 'health["sourceCommit"] == os.environ["GITHUB_SHA"]' in text
    assert 'health["imageSourceCommit"] == os.environ["GITHUB_SHA"]' in text
    assert '--no-traffic' in text


def test_production_deploy_checks_firestore_and_aster_before_build():
    text = workflow()
    assert 'gcloud firestore databases describe --database="(default)"' in text
    assert "https://fapi.asterdex.com/fapi/v3/exchangeInfo" in text
    assert 'row.get("status", "")' in text


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
