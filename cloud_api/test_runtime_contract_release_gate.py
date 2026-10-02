from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cloud-production.yml"


def test_production_deploy_runs_runtime_contract_selection_before_candidate_deploy():
    text = WORKFLOW.read_text(encoding="utf-8")
    select = text.index("Select mandatory contracts for exact production delta")
    backend = text.index("Run mandatory backend release contracts")
    candidate = text.index("Deploy candidate without production traffic")
    assert select < backend < candidate
    assert "tools/runtime_contract_impact.py" in text
    assert '"$PREVIOUS_SOURCE_COMMIT" "$SOURCE_COMMIT"' in text


def test_production_deploy_captures_read_only_runtime_baseline_before_promotion():
    text = WORKFLOW.read_text(encoding="utf-8")
    baseline = text.index("Capture pre-deploy runtime contract baseline")
    promote = text.index("Promote verified revision")
    assert baseline < promote
    assert "tools/runtime_contract_snapshot.py" in text
    assert "runtime-before.json" in text


def test_post_deploy_runtime_contract_is_verified_after_promotion_and_before_success():
    text = WORKFLOW.read_text(encoding="utf-8")
    promote = text.index("Promote verified revision")
    runtime = text.index("Verify post-deploy trading runtime contract")
    success = text.index("Publish successful deployment to agent issue")
    assert promote < runtime < success
    assert "tools/runtime_contract_post_deploy.py" in text


def test_runtime_contract_failure_uses_existing_automatic_rollback_path():
    text = WORKFLOW.read_text(encoding="utf-8")
    runtime = text.index("Verify post-deploy trading runtime contract")
    rollback = text.index("Roll back failed promotion")
    assert runtime < rollback
    assert "PROMOTION_ATTEMPTED == 'true'" in text
    assert '--to-revisions "$PREVIOUS_REVISION=100"' in text


def test_runtime_snapshot_and_contract_artifacts_are_retained_for_diagnosis():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "${{ runner.temp }}/runtime-before.json" in text
    assert "${{ runner.temp }}/runtime-after.json" in text
    assert "${{ runner.temp }}/runtime-contract-result.json" in text


def test_release_gate_does_not_add_any_live_order_or_settings_action():
    snapshot_source = (ROOT / "tools" / "runtime_contract_snapshot.py").read_text(encoding="utf-8")
    evaluator_source = (ROOT / "tools" / "runtime_contract_post_deploy.py").read_text(encoding="utf-8")
    combined = snapshot_source + evaluator_source
    for forbidden in (
        "submit_order",
        "cancel_order",
        "execute_leg_once",
        "execute_pair_once",
        "live_authorized=True",
        ".set(",
        ".delete(",
    ):
        assert forbidden not in combined
