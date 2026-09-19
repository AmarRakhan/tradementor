from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "agent-production-diagnostic-worker.yml"


def source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_diagnostic_worker_is_dispatch_only_on_trusted_cloud_branch():
    text = source()
    assert "workflow_dispatch:" in text
    assert "issues:" not in text.split("permissions:", 1)[0]
    assert 'test "$GITHUB_REF" = "refs/heads/amar-crypto-bot-2026-cloud"' in text
    assert "GCP_PROJECT_ID: tradementor-production" in text


def test_diagnostic_worker_uses_existing_keyless_wif_and_is_read_only():
    text = source()
    assert "google-github-actions/auth@v2" in text
    assert "workload_identity_provider:" in text
    assert "id-token: write" in text
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
        "gcloud run deploy",
        "gcloud scheduler jobs pause",
        "gcloud scheduler jobs resume",
        "gcloud scheduler jobs update",
        "gcloud secrets versions access",
        "/fapi/v3/order",
    )
    for item in forbidden:
        assert item not in text


def test_diagnostic_worker_posts_sanitized_result_to_requested_issue():
    text = source()
    assert 'gh issue comment "$REQUEST_ISSUE"' in text
    assert "issues: write" in text
    assert "No secrets, wallet keys, private exchange credentials, order payloads, or account data were collected." in text
