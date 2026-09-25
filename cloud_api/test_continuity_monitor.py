from pathlib import Path

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")


def test_continuity_routes_are_owner_gated():
    assert 'def require_continuity_owner' in SOURCE
    assert '@app.get("/v1/me/continuity")' in SOURCE
    assert '@app.post("/v1/me/continuity/refresh")' in SOURCE
    assert '@app.post("/v1/me/continuity/bybit/test")' in SOURCE
    assert '@app.put("/v1/me/continuity/bybit")' in SOURCE
    assert 'require_continuity_owner(user)' in SOURCE
    assert 'ownerUid' in SOURCE


def test_continuity_bybit_has_a_dedicated_secret_namespace():
    assert 'tradementor-bybit-continuity-' in SOURCE
    assert '"apiKey": credentials.api_key' in SOURCE
    assert '"apiSecret": credentials.api_secret' in SOURCE
    assert '"secretRef": secret_name' in SOURCE


def test_google_billing_is_fail_closed_not_guessed_green():
    assert 'cloudbilling.googleapis.com/v1/projects/' in SOURCE
    assert '"billingEnabled": None' in SOURCE
    assert '"status": "WARNING"' in SOURCE
    assert '"status": "ACTIVE" if enabled else "CRITICAL"' in SOURCE
    assert 'Google Cloud billing is niet actief. Productie kan uitvallen.' in SOURCE


def test_continuity_snapshot_never_includes_bybit_secret_values():
    public_builder = SOURCE[SOURCE.index("def _build_continuity_snapshot"):SOURCE.index("def _cached_continuity_snapshot")]
    assert "apiSecret" not in public_builder
    assert "api_key" not in public_builder
    assert "api_secret" not in public_builder


def test_continuity_module_does_not_touch_trading_settings():
    routes = SOURCE[SOURCE.index('@app.get("/v1/me/continuity")'):SOURCE.index('@app.get("/v1/admin/releases")')]
    forbidden = ("place_order", "close_position", "dca", "take_profit", "leverage", "longSlots", "shortSlots")
    for value in forbidden:
        assert value not in routes


def test_bybit_base_currency_reserve_uses_the_parsed_balance_value():
    block = SOURCE[SOURCE.index("def _continuity_bybit_service"):SOURCE.index("def _continuity_future_service")]
    assert "comparable += balance" in block
    assert "reserve_balance" not in block
