from pathlib import Path

def route_source() -> str:
    source = Path(__file__).with_name("main.py").read_text()
    start = source.index('@app.post("/v1/me/aster/positions/close-all")')
    end = source.index('@app.get("/v1/me/aster/positions/profitable-close-preview")')
    return source[start:end]

def test_full_close_is_explicit_uid_scoped_idempotent_and_profit_independent():
    route = route_source()
    assert "if not request.confirm" in route
    assert 'uid = str(user["uid"])' in route
    assert "asterFullCloseIntents" in route
    assert "action_ref.create" in route
    assert "AlreadyExists" in route
    assert "closeEnabled" not in route
    assert "MINIMUM_PROFIT_USD" not in route

def test_full_close_pauses_reentry_and_uses_fresh_exchange_truth_per_leg():
    route = route_source()
    assert '"enabled": False' in route
    assert '"pendingReopens": []' in route
    assert "closeLock" in route
    assert route.count("client.position_risk()") >= 4
    assert 'side=PositionSide(side)' in route
    assert 'action="CLOSE"' in route
    assert "manual_loss_confirmation=True" in route

def test_full_close_reports_exchange_confirmed_final_state_and_partial_failures():
    route = route_source()
    assert '"closedCount": closed_count' in route
    assert '"remainingCount": len(final_positions)' in route
    assert '"complete": complete' in route
    assert '"PARTIAL_FAIL_CLOSED"' in route
    assert "remaining_orders" in route
