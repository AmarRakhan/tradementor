from pathlib import Path


WORKFLOW = (Path(__file__).resolve().parents[1] / ".github" / "workflows" /
            "diagnose-strategy2-queue-shadow-read-only.yml").read_text()


def test_queue_shadow_workflow_is_one_masked_account_and_manual_only():
    assert "workflow_dispatch:" in WORKFLOW
    assert "RUN_QUEUE_SHADOW_READ_ONLY" in WORKFLOW
    assert "ACCOUNT_EMAIL_SHA256: 6368246d6bce" in WORKFLOW
    assert 'name="shadow-identity"' in WORKFLOW
    assert "auth.list_users(app=identity_app)" in WORKFLOW
    assert "firebase_admin.initialize_app(credential,options={\"projectId\":\"tradementor-production\"})" not in WORKFLOW
    assert "len(set(matched))!=1" in WORKFLOW
    assert "refs/heads/codex/strategy2-account-order-queue" in WORKFLOW


def test_queue_shadow_workflow_pins_zero_traffic_candidate_revision():
    assert "EXPECTED_REVISION: tradementor-strategy2-test-live-api-00042-pur" in WORKFLOW
    assert 'tagged.get("percent",0)==0' in WORKFLOW
    assert 'tagged.get("revisionName")==expected' in WORKFLOW
    assert 'service["status"]["latestCreatedRevisionName"]==expected' in WORKFLOW


def test_queue_shadow_workflow_invokes_only_read_only_planner():
    assert "strategy2_queue_shadow" in WORKFLOW
    assert 'result.get("ordersSent")==0' in WORKFLOW
    assert 'result.get("persistentWrites")==0' in WORKFLOW
    assert 'result.get("exchangeSubmissions")==0' in WORKFLOW
    for forbidden in ("submit_order", "change_leverage", "change_margin_type",
                      "scheduler jobs update", "run services update-traffic",
                      ".set(", ".update(", ".add(", ".commit("):
        assert forbidden not in WORKFLOW


def test_queue_shadow_workflow_only_creates_and_removes_ephemeral_job():
    assert 'gcloud run jobs deploy "$JOB"' in WORKFLOW
    assert 'gcloud run jobs delete "$JOB"' in WORKFLOW
    assert "gcloud run deploy" not in WORKFLOW
    assert "gcloud run services update" not in WORKFLOW
    assert "ASTER_STRATEGY2_ORDER_QUEUE_ENABLED=false" in WORKFLOW
