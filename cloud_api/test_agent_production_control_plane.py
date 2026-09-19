from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "agent-production-control-plane.yml"


def source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_agent_control_plane_is_issue_triggered_and_posts_result_back_to_github():
    text = source()
    assert "issues:" in text
    assert "types: [opened]" in text
    assert "[AGENT-CONTROL] diagnose production" in text
    assert "issues: write" in text
    assert 'gh issue comment "$ISSUE_NUMBER"' in text


def test_agent_control_plane_uses_keyless_wif_for_production():
    text = source()
    assert "GCP_PROJECT_ID: tradementor-production" in text
    assert "google-github-actions/auth@v2" in text
    assert "workload_identity_provider:" in text
    assert "id-token: write" in text
    assert "service_account:" in text


def test_agent_control_plane_checks_runtime_without_mutating_it():
    text = source()
    required = (
        "gcloud beta billing projects describe",
        "gcloud run services describe",
        "gcloud firestore databases describe",
        "gcloud scheduler jobs describe",
        "gcloud logging read",
        "https://fapi.asterdex.com/fapi/v3/exchangeInfo",
    )
    for item in required:
        assert item in text
    forbidden = (
        "gcloud run services update",
        "gcloud run services delete",
        "gcloud scheduler jobs pause",
        "gcloud scheduler jobs resume",
        "gcloud scheduler jobs update",
        "gcloud secrets versions access",
        "/fapi/v3/order",
    )
    for item in forbidden:
        assert item not in text


def test_agent_control_plane_never_publishes_sensitive_exchange_or_account_data():
    text = source()
    assert "No secrets, wallet keys, private exchange credentials, order payloads, or account data were collected." in text
