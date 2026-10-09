from pathlib import Path


def test_health_endpoint_has_no_storage_writes_or_exchange_calls():
    text = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
    route = text.split('@app.get("/v1/me/aster/strategy2/config-health")', 1)[1].split(
        '@app.put("/v1/me/aster/strategy2/settings")', 1
    )[0]
    assert "Depends(authenticated_user)" in route
    assert 'aster_strategy2_reference(str(user["uid"])).get()' in route
    assert "MultiBbConfig.from_mapping(normalized)" in route
    for forbidden in (".set(", ".create(", ".update(", "load_aster_secret(", "AsterV3Client(", "place_order(", "httpx."):
        assert forbidden not in route
    for sensitive in ('"minimumLeverage":', '"maximumLeverage":', '"uid":', '"wallet":'):
        assert sensitive not in route


def test_account_health_reports_validation_failure_without_rewriting_config():
    text = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
    route = text.split('@app.get("/v1/me/aster/strategy2/config-health")', 1)[1].split(
        '@app.put("/v1/me/aster/strategy2/settings")', 1
    )[0]
    assert 'error_class = "CONFIG_VALIDATION_ERROR"' in route
    assert '"settingsValidation": error_class' in route
    assert '"readOnly": True' in route
    assert '"ordersSent": 0' in route
