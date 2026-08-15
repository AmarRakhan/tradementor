from pathlib import Path


SOURCE = Path(__file__).with_name("strategy2_test_entrypoint.py").read_text(encoding="utf-8")


def route_source() -> str:
    start = SOURCE.index('@app.get("/v1/me/aster/strategy2/diagnostics")')
    return SOURCE[start:SOURCE.index("\n@app.", start + 10)]


def test_strategy2_diagnostics_is_token_scoped_and_read_only():
    route = route_source()
    assert "Depends(control_plane.authenticated_user)" in route
    assert 'uid = str(user["uid"])' in route
    assert "get_user_by_email" not in route
    assert ".set(" not in route
    assert ".update(" not in route
    assert ".create(" not in route
    assert "AsterV3Client" not in route
    assert '"readOnly": True' in route


def test_strategy2_diagnostics_exposes_required_ownership_evidence():
    route = route_source()
    for field in (
        '"documentExists"', '"enabled"', '"monitor"', '"exclusiveOwnership"',
        '"ownershipProven"', '"ownedLegs"', '"longLegs"', '"shortLegs"',
        '"unassignedPositions"', '"crossStrategyCollisions"',
        '"legacyStrategiesActive"', '"heartbeatFresh"', '"reason"',
    ):
        assert field in route


def test_exclusive_handoff_is_token_scoped_fail_closed_and_order_free():
    block = SOURCE[SOURCE.index('@app.post("/v1/me/aster/strategy2/exclusive-handoff")'):]
    assert "Depends(control_plane.authenticated_user)" in block
    assert "len(s2_keys) == 68" in block
    assert "not collisions and unassigned == 0" in block
    assert '"enabled": False, "monitor": False' in block
    assert "batch.commit()" in block
    assert '"ordersSent": 0' in block
    assert "AsterV3Client" not in block
    assert "execute_aster" not in block
