from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cloud-strategy2-test-live.yml"
MAIN = ROOT / "cloud_api" / "main.py"


def test_version_42_workflow_builds_the_exact_triggering_cloud_branch_commit():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "ref: ${{ github.sha }}" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in workflow
    assert 'test "$GITHUB_REF_NAME" = "amar-crypto-bot-2026-cloud"' in workflow
    assert "test-aster-position-capacity-v41" not in workflow


def test_strategy2_start_and_status_read_the_same_firestore_document():
    source = MAIN.read_text(encoding="utf-8")
    reference = source[source.index("def aster_strategy2_reference"):source.index("def aster_strategy3_reference")]
    status = source[source.index('@app.get("/v1/me/aster/status")'):source.index('@app.post("/v1/me/aster/strategy2/replays")')]
    start = source[source.index('@app.post("/v1/me/aster/strategy2/start")'):source.index('@app.post("/v1/me/aster/strategy2/stop")')]
    assert 'db.collection("asterStrategy2").document(uid)' in reference
    assert "aster_strategy2_reference(uid).get()" in status
    assert "ref=aster_strategy2_reference(uid)" in start
