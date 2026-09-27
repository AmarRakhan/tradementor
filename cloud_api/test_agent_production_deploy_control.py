from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy-cloud-production.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_manual_production_dispatch_is_preserved() -> None:
    text = _workflow()
    assert "workflow_dispatch:" in text
    assert 'description: "Type DEPLOY_PRODUCTION_BACKEND"' in text
    assert 'environment: production' in text


def test_agent_deploy_request_is_owner_only_and_auditable() -> None:
    text = _workflow()
    assert '".github/deploy-requests/production-backend.json"' in text
    assert "github.event_name == 'push' && github.actor == 'AmarRakhan'" in text
    assert 'test "$GITHUB_ACTOR" = "AmarRakhan"' in text
    assert 'request["requestedBy"] != "AmarRakhan"' in text
    assert 'request["confirmation"] != "DEPLOY_PRODUCTION_BACKEND"' in text
    assert 'request["action"] != "deploy-production-backend"' in text


def test_agent_deploy_keeps_exact_source_and_canonical_ancestry_gate() -> None:
    text = _workflow()
    assert '[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]' in text
    assert 'test "$(git rev-parse HEAD)" = "$SOURCE_COMMIT"' in text
    assert 'git merge-base --is-ancestor "$SOURCE_COMMIT" "origin/amar-crypto-bot-2026-cloud"' in text


def test_agent_deploy_keeps_candidate_health_promotion_and_rollback() -> None:
    text = _workflow()
    assert "Deploy candidate without production traffic" in text
    assert "Verify candidate health and route contract" in text
    assert "Promote verified revision" in text
    assert "Verify production after promotion" in text
    assert "Roll back failed promotion" in text
    assert "google-github-actions/auth@v2" in text
