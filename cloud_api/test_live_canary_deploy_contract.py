from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_retired_strategy3_canary_deployment_is_absent():
    workflow = ROOT / ".github" / "workflows" / "deploy-cloud-live-canary.yml"
    assert not workflow.exists()
    active = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT/".github"/"workflows").glob("*.yml"))
    assert "ASTER_STRATEGY3_CANARY_ENABLED=true" not in active
