from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cloud-production.yml"
REQUEST = ROOT / "PRODUCTION_DEPLOY_REQUEST.json"


def test_production_deploy_can_be_explicitly_requested_from_github():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in text
    assert "- amar-crypto-bot-2026-cloud" in text
    assert '"PRODUCTION_DEPLOY_REQUEST.json"' in text
    assert 'request.get("approvedForProduction") is True' in text
    assert 'request.get("deployCurrentHead") is True' in text
    assert 'request.get("targetBranch") == "amar-crypto-bot-2026-cloud"' in text


def test_current_deploy_request_is_explicit_and_auditable():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert request["approvedForProduction"] is True
    assert request["deployCurrentHead"] is True
    assert request["targetBranch"] == "amar-crypto-bot-2026-cloud"
    assert request["requestId"]
    assert request["reason"]
