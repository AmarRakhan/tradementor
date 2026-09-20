from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent


def test_profit_sweep_extensions_are_registered_in_production_entrypoint():
    entrypoint = (ROOT / "withdraw_app.py").read_text(encoding="utf-8")
    assert "import profit_sweep_settings_extension" in entrypoint
    assert "import profit_sweep_live_extension" in entrypoint


def test_settings_route_keeps_user_control_separate_from_global_live_gate():
    source = (ROOT / "profit_sweep_settings_extension.py").read_text(encoding="utf-8")
    assert '@main.app.get("/v1/me/aster/profit-sweep-settings")' in source
    assert '@main.app.put("/v1/me/aster/profit-sweep-settings")' in source
    assert '"enabled": bool(request.enabled)' in source
    assert "live_enabled()" in source
    assert '"automaticTransferEnabled": automatic' in source
    assert '"mode": "LIVE_AUTO_TRANSFER"' in source
    assert '"principalIncluded": False' in source
    assert '"unrealizedPnlIncluded": False' in source
    assert "return False, float(DEFAULT_SWEEP_PERCENT)" in source
    # Configuration routes themselves still cannot move money.
    assert "signed_request" not in source
    assert "/asset/wallet/transfer" not in source
    assert "/withdraw" not in source


def test_live_engine_uses_only_internal_future_to_spot_transfer_and_no_withdrawal():
    source = (ROOT / "profit_sweep_live.py").read_text(encoding="utf-8")
    assert 'TRANSFER_PATH = "/api/v3/asset/wallet/transfer"' in source
    assert 'TRANSFER_KIND = "FUTURE_SPOT"' in source
    assert 'TRANSFER_ASSET = "USDT"' in source
    assert '"clientTranId": prepared.client_tran_id' in source
    assert 'client.signed_spot_request("POST", TRANSFER_PATH' in source
    assert 'str(payload.get("status", "")).upper() != "SUCCESS"' in source
    assert 'payload.get("tranId")' in source
    assert 'except AsterSubmissionUncertain' in source
    assert "/withdraw" not in source
    assert "SPOT_FUTURE" not in source


def test_production_deploy_is_the_only_global_activation_gate():
    workflow = (REPO / ".github" / "workflows" / "deploy-cloud-production.yml").read_text(encoding="utf-8")
    assert "ASTER_PROFIT_SWEEP_LIVE_ENABLED=true" in workflow
    assert '"ASTER_PROFIT_SWEEP_LIVE_ENABLED":"true"' in workflow
    assert "DEPLOY_PRODUCTION_BACKEND" in workflow
