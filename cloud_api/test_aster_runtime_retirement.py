from pathlib import Path

from aster_runtime_retirement import retirement_contract


def test_every_legacy_runtime_path_has_an_explicit_removal_gate():
    contract = retirement_contract()
    assert contract["policy"] == "REPLACEMENT_IS_NOT_DONE_UNTIL_LEGACY_IS_REMOVED"
    assert contract["activeLegacyCount"] >= 1
    for item in contract["items"]:
        assert item["id"]
        assert item["legacy"]
        assert item["replacement"]
        assert item["status"] in {"ACTIVE_LEGACY", "RETIRED"}
        assert item["removalGate"]
        assert item["removeWhen"]


def test_runtime_retirement_endpoint_is_read_only():
    source = Path(__file__).with_name("main.py").read_text()
    route = source.split('@app.get("/v1/me/aster/runtime-retirement")', 1)[1].split(
        '@app.get("/v1/me/aster/native-order-shadow")', 1
    )[0]
    assert "retirement_contract()" in route
    assert '"ordersSent": 0' in route
    assert '"settingsChanged": False' in route
    assert '"runtimeChanged": False' in route
    assert ".set(" not in route
    assert "execute_" not in route
