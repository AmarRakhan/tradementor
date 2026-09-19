from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "agent-backend-deploy-dispatcher.yml"


def source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_backend_dispatcher_is_owner_only_and_issue_triggered():
    text = source()
    assert "issues:" in text
    assert "types: [opened]" in text
    assert "[AGENT-CONTROL] deploy backend" in text
    assert "github.event.issue.user.login == 'AmarRakhan'" in text
    assert "actions: write" in text
    assert "issues: write" in text


def test_backend_dispatcher_only_allows_exact_current_cloud_branch_head():
    text = source()
    assert "TARGET_BRANCH: amar-crypto-bot-2026-cloud" in text
    assert 'test "$COMMIT" = "$BRANCH_HEAD"' in text
    assert 'test "$CURRENT_HEAD" = "$COMMIT"' in text
    assert "commit:" in text


def test_backend_dispatcher_ensures_exact_head_backend_ci_before_dispatch():
    text = source()
    assert "cloud-backend-ci.yml/runs" in text
    assert 'select(.head_sha == \"$COMMIT\")' in text
    assert "gh workflow run cloud-backend-ci.yml" in text
    assert 'test "$CI_RESULT" = "success"' in text
    assert 'test "$CURRENT_HEAD" = "$COMMIT"' in text


def test_backend_dispatcher_reuses_existing_hardened_deploy_workflow_only():
    text = source()
    assert "gh workflow run deploy-cloud-production.yml" in text
    assert "-f confirmation=DEPLOY_PRODUCTION_BACKEND" in text
    assert '-f request_issue="$ISSUE_NUMBER"' in text
    assert "gcloud " not in text
