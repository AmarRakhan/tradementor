from pathlib import Path


ROOT=Path(__file__).resolve().parent


def test_money_grabber_routes_are_distinct_from_legacy_protection_and_require_preview():
    source=(ROOT/"main.py").read_text()
    assert '"/v1/me/aster/strategy2/money-grabber/activation-preview"' in source
    assert '"/v1/me/aster/strategy2/money-grabber/start-round"' in source
    assert '"/v1/me/aster/strategy2/money-grabber/shadow"' in source
    assert "preview_fingerprint" in source
    assert "fresh[\"fingerprint\"]!=request.preview_fingerprint" in source
    assert '"ordersSent":0' in source


def test_default_registration_never_activates_money_grabber():
    source=(ROOT/"main.py").read_text()
    registration=source[source.index("def ensure_aster_strategy2_control"):source.index("def _record_aster_order_attribution")]
    assert '"settings":Strategy2Config().public_dict()' in registration
    assert '"enabled":False' in registration
    assert "moneyGrabberActivated" not in registration


def test_start_round_persists_separate_round_and_pair_state():
    source=(ROOT/"main.py").read_text()
    route=source[source.index("def start_money_grabber("):source.index("@app.put",source.index("def start_money_grabber("))]
    assert '"moneyGrabberRound":stored' in route
    assert '"moneyGrabberPairs":[]' in route
    assert '"moneyGrabberActivated":True' in route
    assert "protectionEnabled" not in route


def test_shadow_uses_read_only_client_and_reports_zero_sent_orders():
    source=(ROOT/"main.py").read_text();start=source.index("def money_grabber_shadow(")
    route=source[start:source.index("@app.put",start)]
    assert "live_authorized=False" in route
    assert "money_grabber_shadow_report" in route
    assert "submit_order" not in route and "execute_" not in route


def test_scheduler_hook_is_shadow_only_and_execution_gate_is_false():
    source=(ROOT/"main.py").read_text();start=source.index("# Money Grabber scheduler integration starts")
    hook=source[start:source.index("blocked_dca_raw",start)]
    assert '"moneyGrabberSchedulerShadow"' in hook
    assert '"moneyGrabberExecutionEnabled":False' in hook
    assert "execute_protection" not in hook and "execute_round_close" not in hook
    assert "settings.money_grabber_enabled" in hook and 'raw.get("moneyGrabberActivated")' in hook
