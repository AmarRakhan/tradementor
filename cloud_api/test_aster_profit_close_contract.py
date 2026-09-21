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


def test_multi_bb_runtime_ownership_is_included_in_safe_profit_close_scope():
    source = Path(__file__).with_name("main.py").read_text()
    helper_start = source.index("def _aster_strategy2_owned_keys")
    helper_end = source.index("def _sniper_live_gate_enabled", helper_start)
    helper = source[helper_start:helper_end]
    route = route_source()

    assert 'raw.get("multiBbPositions")' in helper
    assert 'str(raw_key).upper().split("|",1)' in helper
    assert 'side in {"LONG","SHORT"}' in helper
    assert "keys.add((symbol,side))" in helper
    assert "_aster_strategy2_owned_keys(uid)" in route
    assert "in owned_keys" in route
