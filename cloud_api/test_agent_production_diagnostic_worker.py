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
        "https://cloudbilling.googleapis.com/v1/projects/$GCP_PROJECT_ID/billingInfo",
        "https://cloudbilling.googleapis.com/v1/billingAccounts/$BILLING_ACCOUNT",
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


def test_billing_diagnostics_publish_only_sanitized_http_and_error_status():
    text = source()
    assert 'Billing project API: HTTP %s%s' in text
    assert 'Billing account API: HTTP %s%s' in text
    assert '(error or {}).get("status")' in text
    assert 'billing-project.json' in text
    assert 'billing-account.json' in text
    assert 'rm -f control-plane-report/aster-exchange-info.json control-plane-report/billing-project.json control-plane-report/billing-account.json control-plane-report/web-root.html' in text
    assert 'getPaymentInfo' not in text


def test_unreadable_billing_is_separate_from_runtime_health():
    text = source()
    assert 'BILLING_CONTROL="UNVERIFIED"' in text
    assert 'BILLING_CONTROL="FAILED"' in text
    assert 'direct Billing API unavailable · external billing alert channel required' in text
    assert '### Overall runtime health' in text
    unreadable = text[text.index('else\n            BILLING_LINE="⚠️ direct Billing API unavailable'):text.index('          fi\n\n          SERVICE_JSON=')]
    assert 'STATUS="DEGRADED"' not in unreadable


def test_diagnostic_worker_checks_live_v46_webapp_without_mutation():
    text = source()
    assert "WEB_CLOUD_RUN_SERVICE: amar-bot-v44-direct-install" in text
    assert 'gcloud run services describe "$WEB_CLOUD_RUN_SERVICE"' in text
    assert 'data-webapp-version="([^"]+)"' in text
    assert 'data-webapp-build="([^"]+)"' in text
    assert 'Webapp live revision: %s' in text
    assert 'Webapp visible version/build: v%s · build %s' in text
    assert 'gcloud run services update "$WEB_CLOUD_RUN_SERVICE"' not in text
    assert 'gcloud run deploy "$WEB_CLOUD_RUN_SERVICE"' not in text


def test_web_diagnostics_report_only_env_names_for_live_and_latest_revisions():
    text = source()
    assert "WEB_LIVE_ENV_NAMES" in text
    assert "WEB_LATEST_ENV_NAMES" in text
    assert 'Webapp live env names: %s' in text
    assert 'Webapp latest env names: %s' in text
    assert 'x.get("name","")' in text
    assert 'x.get("value")' not in text[text.index("WEB_LIVE_ENV_NAMES"):text.index('WEB_HTML_FILE=')]
