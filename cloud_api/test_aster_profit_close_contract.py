from pathlib import Path


def route_source() -> str:
    source = Path(__file__).with_name("main.py").read_text()
    start = source.index('@app.post("/v1/me/aster/positions/close-profitable")')
    end = source.index('@app.post("/v1/me/aster/positions/{symbol}/close")')
    return source[start:end]


def test_bulk_close_is_confirmed_uid_scoped_and_idempotent():
    route = route_source()
    assert "if not request.confirm" in route
    assert 'uid = str(user["uid"])' in route
    assert "action_ref.create" in route
    assert "AlreadyExists" in route
    assert "duplicate" in route


def test_bulk_close_rechecks_each_leg_and_never_reverses_it():
    route = route_source()
    assert route.count("client.position_risk()") >= 3
    assert "current_profit < MINIMUM_PROFIT_USD" in route
    assert "PositionSide(side)" in route
    assert 'action="CLOSE"' in route
    assert "manual_loss_confirmation=True" in route
    assert "remaining is not None" in route


def test_bulk_close_supports_long_short_all_from_the_same_route():
    route = route_source()
    assert 'side: str = "ALL"' in route
    assert 'scope not in {"ALL", "LONG", "SHORT"}' in route
    assert 'candidate["side"] == scope' in route
    assert 'f"{uid}:{scope}:{request.idempotency_key}"' in route


def test_bulk_close_is_sequential_and_holds_strategy_queue_lease():
    route = route_source()
    assert "_acquire_strategy2_queue_lease" in route
    assert "_release_strategy2_queue_lease" in route
    assert "for index, candidate in enumerate(initial, 1)" in route
    assert "asyncio.gather" not in route
    assert "failed.append" in route
    assert "skipped.append" in route
    assert "BULK_PROFIT_CLOSE_COMPLETED" in route


def test_profit_preview_and_bulk_close_use_full_uid_scoped_aster_account_truth():
    source = Path(__file__).with_name("main.py").read_text()
    preview_start = source.index('@app.get("/v1/me/aster/positions/profitable-close-preview")')
    close_start = source.index('@app.post("/v1/me/aster/positions/close-profitable")')
    close_end = source.index('@app.post("/v1/me/aster/positions/{symbol}/close")')
    preview = source[preview_start:close_start]
    route = source[close_start:close_end]

    # Portfolio Snapshot and Tradecentrum must be driven by the same live Aster
    # account truth. Strategy ownership may not hide a real open position from
    # the explicitly confirmed profit-close workflow.
    assert "rows = client.position_risk()" in preview
    assert "_aster_strategy2_owned_keys" not in preview
    assert "initial = profitable_positions(client.position_risk())" in route
    assert "_aster_strategy2_owned_keys" not in route
