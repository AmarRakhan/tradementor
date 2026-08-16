from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_deploy_configures_scheduler_paused_then_verifies_and_resumes():
    workflow = (ROOT / ".github/workflows/deploy-cloud-production.yml").read_text(encoding="utf-8")
    assert "GCP_PROJECT_ID: tradementor-production" in workflow
    assert "GCP_REGION: europe-west4" in workflow
    assert "CLOUD_RUN_SERVICE: tradementor-api" in workflow
    assert "SCHEDULER_JOB: tradementor-aster-automation-tick" in workflow
    assert 'TARGET="$SERVICE_URL/internal/aster-automation/tick"' in workflow
    assert '--oidc-service-account-email "$RUNTIME_SERVICE_ACCOUNT"' in workflow
    assert '--oidc-token-audience "$SERVICE_URL"' in workflow
    assert 'job["state"] == "PAUSED"' in workflow
    assert '--uri "$SERVICE_URL/health"' in workflow
    assert '--http-method GET' in workflow
    assert 'gcloud scheduler jobs pause "$SCHEDULER_JOB"' in workflow
    assert "--paused" not in workflow
    assert workflow.index("Configure paused one-minute") < workflow.index("Verify paused scheduler")
    assert workflow.index("Verify paused scheduler") < workflow.index("Promote verified revision")
    assert workflow.index("Promote verified revision") < workflow.index("Resume verified Strategy 1 and 2 scheduler")


def test_production_scheduler_requires_live_s2_boundary_and_rejects_s3_target():
    workflow = (ROOT / ".github/workflows/deploy-cloud-production.yml").read_text(encoding="utf-8")
    assert 'variables.get("ASTER_LIVE_EXECUTION_ENABLED") == "true"' in workflow
    assert 'variables.get("ASTER_STRATEGY2_LIVE_ENABLED") == "true"' in workflow
    assert 'variables.get("ASTER_STRATEGY3_LIVE_ENABLED")' not in workflow
    assert '"/internal/aster-strategy3/tick" not in job["httpTarget"]["uri"]' in workflow


def test_production_scheduler_endpoint_never_processes_isolated_strategy3():
    source = (ROOT / "cloud_api/main.py").read_text(encoding="utf-8")
    start = source.index('@app.post("/internal/aster-automation/tick")')
    end = source.index('@app.post("/internal/aster-strategy3/tick")', start)
    block = source[start:end]
    assert "_run_aster_strategy2_tick" in block
    assert "_run_aster_strategy3_tick" not in block
    assert '"strategy3Isolated":True' in block


def test_strategy2_queue_is_double_gated_and_old_runtime_remains_available():
    source = (ROOT / "cloud_api/main.py").read_text(encoding="utf-8")
    assert 'os.getenv(QUEUE_FEATURE_FLAG,"false").lower()=="true"' in source
    assert 'bool(raw.get("orderQueueEnabled",False))' in source
    assert 'reconcile_only=not queue_enabled' in source
    assert 'drain_pending_only=not queue_enabled and has_pending_reopen' in source
    assert 'if uses_queue_lease else _run_aster_strategy2_tick(item.id)' in source


def test_queue_uses_fenced_account_lease_and_persistent_scan_counter():
    source = (ROOT / "cloud_api/main.py").read_text(encoding="utf-8")
    start = source.index("def _acquire_strategy2_queue_lease")
    end = source.index("@app.post(\"/internal/mexc-automation/tick\")", start)
    block = source[start:end]
    assert '"token":token' in block
    assert 'str(lease.get("token",""))!=token' in block
    assert '"ordersUsed":used' in block
    assert "used<MAX_ORDERS_PER_ACCOUNT_SCAN" in block
    assert "new_used>MAX_ORDERS_PER_ACCOUNT_SCAN" in block
    assert "_reserve_strategy2_queue_order(ref,scan_id,intent,details)" in block


def test_pending_reopen_is_persisted_when_last_budget_slot_is_a_close():
    source = (ROOT / "cloud_api/main.py").read_text(encoding="utf-8")
    assert '"reason":"ORDER_BUDGET_EXHAUSTED"' in source
    assert '"pendingReopens":pending_reopens' in source
    assert 'action":"PENDING_REOPEN"' in source


def test_restart_reconciliation_requires_terminal_fill_and_preserves_dca_metadata():
    source = (ROOT / "cloud_api/main.py").read_text(encoding="utf-8")
    start = source.index("def _reconcile_strategy2_queue_intent")
    end = source.index("def _run_aster_strategy2_queue_scan", start)
    block = source[start:end]
    assert 'status!="FILLED"' in block
    assert "if not matching_fills" in block
    assert 'action_kind=="ADD_DCA"' in block
    assert '"PROCESS_RESTART_AFTER_CONFIRMED_CLOSE"' in block


def test_queue_candidate_deploy_has_zero_traffic_and_explicitly_disabled_flag():
    workflow=(ROOT/".github/workflows/deploy-strategy2-queue-candidate.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert 'test "$GITHUB_EVENT_NAME" = "workflow_dispatch"' in workflow
    assert 'test "${{ inputs.confirmation }}" = "DEPLOY_ZERO_TRAFFIC_CANDIDATE"' in workflow
    assert 'refs/heads/codex/strategy2-account-order-queue' in workflow
    assert '--no-traffic --tag "$CANDIDATE_TAG"' in workflow
    assert 'ASTER_STRATEGY2_ORDER_QUEUE_ENABLED=false' in workflow
    assert 'assert row.get("percent",0)==0' in workflow
    assert 'assert job_before==job_after' in workflow
    assert "/internal/aster-strategy2/tick" not in workflow
