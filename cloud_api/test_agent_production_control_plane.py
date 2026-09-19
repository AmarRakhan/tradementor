from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "agent-production-control-plane.yml"


def source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_main_control_plane_is_owner_only_github_dispatcher():
    text = source()
    assert "types: [opened]" in text
    assert "[AGENT-CONTROL] diagnose production" in text
    assert "github.event.issue.user.login == 'AmarRakhan'" in text
    assert "actions: write" in text
    assert "issues: write" in text


def test_main_control_plane_does_not_hold_google_identity():
    text = source()
    assert "id-token: write" not in text
    assert "google-github-actions/auth" not in text
    assert "gcloud " not in text
    assert "workload_identity_provider" not in text


def test_main_control_plane_dispatches_trusted_branch_worker():
    text = source()
    assert "TARGET_BRANCH: amar-crypto-bot-2026-cloud" in text
    assert "gh workflow run agent-production-diagnostic-worker.yml" in text
    assert '--ref "$TARGET_BRANCH"' in text
    assert '-f request_issue="$ISSUE_NUMBER"' in text


def test_main_control_plane_can_report_v46_deploy_status_without_google_access():
    text = source()
    assert "[AGENT-CONTROL] diagnose web deploy" in text
    assert "deploy-shared-v44-testapp.yml/runs" in text
    assert "actions/runs/$RUN_ID/jobs" in text
    assert "FAILED STEP:" in text
    assert "CURRENT STEP:" in text
    assert "V46 web deployment status" in text
    assert "gcloud " not in text
