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


def test_bulk_close_is_sequential_and_holds_strategy_queue_lease():
    route = route_source()
    assert "_acquire_strategy2_queue_lease" in route
    assert "_release_strategy2_queue_lease" in route
    assert "for index, candidate in enumerate(initial, 1)" in route
    assert "asyncio.gather" not in route
    assert "failed.append" in route
    assert "skipped.append" in route
    assert "BULK_PROFIT_CLOSE_COMPLETED" in route
