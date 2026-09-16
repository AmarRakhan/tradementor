from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_profit_sweep_settings_are_registered_in_production_entrypoint():
    entrypoint = (ROOT / "withdraw_app.py").read_text(encoding="utf-8")
    assert "import profit_sweep_settings_extension" in entrypoint


def test_profit_sweep_settings_extension_is_config_only():
    source = (ROOT / "profit_sweep_settings_extension.py").read_text(encoding="utf-8")
    assert '@main.app.get("/v1/me/aster/profit-sweep-settings")' in source
    assert '@main.app.put("/v1/me/aster/profit-sweep-settings")' in source
    assert '"automaticTransferEnabled": False' in source
    assert '"mode": "CONFIG_ONLY"' in source
    assert '"principalIncluded": False' in source
    assert '"unrealizedPnlIncluded": False' in source
    assert "sapi.asterdex.com" not in source
    assert "fapi.asterdex.com" not in source
    assert "/transfer" not in source
    assert "/withdraw" not in source
    assert "submit_order" not in source
