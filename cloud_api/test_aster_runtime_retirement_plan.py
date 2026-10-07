import json
from pathlib import Path


def test_runtime_retirement_registry_has_no_ungated_removal():
    root = Path(__file__).resolve().parents[1]
    plan = json.loads((root / "docs" / "aster-runtime-retirement-plan.json").read_text())
    assert plan["policy"]["productionMutationAllowed"] is False
    assert plan["policy"]["defaultAction"] == "KEEP_UNTIL_PROVEN"

    items = plan.get("items") or []
    assert items
    for item in items:
        assert item["id"]
        assert item["currentPaths"]
        assert item["replacement"]
        assert item["removalGates"]
        assert item["removeAfter"]
        assert item["keepAsFallbackUntil"] is not None
        assert item["status"] not in {"REMOVE_NOW", "REMOVED"}
        assert item["liveTradingImpact"] in {"LOW", "MEDIUM", "HIGH"}


def test_high_risk_runtime_paths_require_canary_and_rollback_before_removal():
    root = Path(__file__).resolve().parents[1]
    plan = json.loads((root / "docs" / "aster-runtime-retirement-plan.json").read_text())
    high_risk = [item for item in plan["items"] if item["liveTradingImpact"] == "HIGH"]
    assert high_risk
    for item in high_risk:
        gates = " ".join(item["removalGates"]).lower()
        assert "canary" in gates
        assert "rollback" in gates
