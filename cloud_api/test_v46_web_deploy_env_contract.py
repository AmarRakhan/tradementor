from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-shared-v44-testapp.yml"


def source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_v46_candidate_updates_only_build_env_without_replacing_existing_env():
    text = source()
    assert '--update-env-vars "WEBAPP_BUILD_NUMBER=${WEBAPP_BUILD_NUMBER}"' in text
    assert '--set-env-vars "WEBAPP_BUILD_NUMBER=${WEBAPP_BUILD_NUMBER}"' not in text


def test_v46_candidate_env_safety_ignores_build_value_but_preserves_other_env_contract():
    text = source()
    assert "def env_contract_without_build(spec):" in text
    assert 'if not name or name=="WEBAPP_BUILD_NUMBER":' in text
    assert '"secret" if "valueFrom" in item else "plain"' in text
    assert "assert env_contract_without_build(b)==env_contract_without_build(a)" in text
