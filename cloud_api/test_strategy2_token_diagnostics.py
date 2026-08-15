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
