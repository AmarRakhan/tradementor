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


def test_manual_profit_close_is_account_wide_not_strategy2_ownership_scoped():
    source = Path(__file__).with_name("main.py").read_text()
    preview_start = source.index('@app.get("/v1/me/aster/positions/profitable-close-preview")')
    preview_end = source.index('@app.post("/v1/me/aster/positions/close-profitable")', preview_start)
    preview = source[preview_start:preview_end]
    route = route_source()

    assert "rows = list(client.position_risk())" in preview
    assert "_profitable_aster_close_candidates(uid, rows)" in preview
    assert "_aster_strategy2_owned_keys" not in preview
    assert "_aster_strategy2_owned_keys" not in route
    assert "initial_rows = list(client.position_risk())" in route
    assert "_profitable_aster_close_candidates(uid, initial_rows)" in route


def test_preview_and_submit_share_exact_same_profit_candidate_selector():
    source = Path(__file__).with_name("main.py").read_text()
    helper_start = source.index("def _profitable_aster_close_candidates")
    helper_end = source.index("_MANUAL_AUTO_HEDGE_RELEASE_STATUSES", helper_start)
    helper = source[helper_start:helper_end]
    preview_start = source.index('@app.get("/v1/me/aster/positions/profitable-close-preview")')
    preview_end = source.index('@app.post("/v1/me/aster/positions/close-profitable")', preview_start)
    preview = source[preview_start:preview_end]
    route = route_source()

    assert "raw_candidates = profitable_positions(rows)" in helper
    assert "_exclude_auto_hedge_managed_profit_candidates(uid, raw_candidates)" in helper
    assert "_profitable_aster_close_candidates(uid, rows)" in preview
    assert "_profitable_aster_close_candidates(uid, initial_rows)" in route


def test_bulk_profit_keeps_auto_hedge_recovery_pair_fail_closed():
    source = Path(__file__).with_name("main.py").read_text()
    helper_start = source.index("def _exclude_auto_hedge_managed_profit_candidates")
    helper_end = source.index("_MANUAL_AUTO_HEDGE_RELEASE_STATUSES", helper_start)
    helper = source[helper_start:helper_end]
    route = route_source()

    assert "auto_hedge_symbol_managed(account_uid=uid, symbol=symbol)" in helper
    assert "protected_candidates" in source
    assert "protected_excluded" in route
    assert "Auto Hedge-pair beschermd" in route
    assert "auto_hedge_symbol_managed(account_uid=uid, symbol=symbol)" in route


def test_manual_profit_close_does_not_touch_automatic_strategy_tp_planner():
    source = Path(__file__).with_name("main.py").read_text()
    helper_start = source.index("def _profitable_aster_close_candidates")
    route = route_source()

    assert "next_management_decision" not in route
    assert "FULL_TP" not in route
    assert "PARTIAL_TP" not in route
    assert helper_start > source.index("def _aster_strategy2_owned_keys")
