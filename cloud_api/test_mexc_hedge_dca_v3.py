from dataclasses import replace

from mexc_hedge_dca_v3 import (
    SideCycle, V3Account, V3Market, V3Settings, V3State,
    V3Action, apply_paper_action, decide_v3, enforce_protective_only,
    protective_monitor_is_complete, reconcile_state,
)


def account(**changes):
    values = dict(
        wallet_balance=125.0, equity=125.0, available_margin=124.0,
        used_margin=1.0, maintenance_margin=.2, margin_ratio=.01,
        liquidation_distance=.90,
    )
    values.update(changes)
    return V3Account(**values)


def market(price=100.0, timestamp=1_000):
    return V3Market(timestamp, price)


def active_state():
    return V3State(
        long=SideCycle("long", quantity=.7, average_entry=100, total_notional=70,
                       next_dca_price=99.5, take_profit_price=100.5),
        short=SideCycle("short", quantity=.7, average_entry=100, total_notional=70,
                        next_dca_price=100.5, take_profit_price=99.5),
    )


def active_account(**changes):
    values = dict(
        long_quantity=.7, long_average=100, long_notional=70,
        short_quantity=.7, short_average=100, short_notional=70,
    )
    values.update(changes)
    return account(**values)


def test_preset_and_notional_meaning():
    settings = V3Settings()
    assert settings.initial_order_notional == 70
    assert settings.leverage == 200
    assert settings.initial_order_notional / settings.leverage == .35
    assert settings.mode == "paper"


def test_a_long_tp_closes_only_long_then_restarts_it():
    settings, state = V3Settings(), active_state()
    action = decide_v3(settings, state, active_account(), market(100.5))
    assert (action.kind, action.side) == ("CLOSE_SIDE", "long")
    closed = apply_paper_action(settings, state, active_account(), market(100.5), action)
    assert closed.long.quantity == 0 and closed.short.quantity == .7
    restart = decide_v3(settings, closed, active_account(long_quantity=0, long_notional=0), market(100.5))
    assert (restart.kind, restart.side, restart.target_notional) == ("OPEN_SIDE", "long", 70)


def test_b_short_tp_closes_only_short_then_restarts_it():
    settings, state = V3Settings(), active_state()
    action = decide_v3(settings, state, active_account(), market(99.5))
    assert (action.kind, action.side) == ("CLOSE_SIDE", "short")
    closed = apply_paper_action(settings, state, active_account(), market(99.5), action)
    assert closed.short.quantity == 0 and closed.long.quantity == .7


def test_c_long_dca_changes_only_long_counter():
    settings, state = V3Settings(), active_state()
    action = decide_v3(settings, state, active_account(short_average=90), market(99.4))
    assert (action.kind, action.side) == ("ADD_DCA", "long")
    updated = apply_paper_action(settings, state, active_account(), market(99.4), action)
    assert updated.long.dca_level == 1 and updated.short.dca_level == 0


def test_d_short_dca_changes_only_short_counter():
    settings, state = V3Settings(), active_state()
    action = decide_v3(settings, state, active_account(long_average=110), market(100.6))
    assert (action.kind, action.side) == ("ADD_DCA", "short")
    updated = apply_paper_action(settings, state, active_account(), market(100.6), action)
    assert updated.short.dca_level == 1 and updated.long.dca_level == 0


def test_e_emergency_cancels_pending_then_equalizes_quantity_then_freezes():
    settings = V3Settings(emergency_equity_trigger=95)
    state = active_state()
    pending = account(equity=94, long_quantity=.03, long_average=100, long_notional=3,
                      short_quantity=.011, short_average=100, short_notional=1.1,
                      open_order_ids=("dca-1",))
    assert decide_v3(settings, state, pending, market()).kind == "CANCEL_PENDING"
    no_pending = replace(pending, open_order_ids=())
    hedge = decide_v3(settings, state, no_pending, market())
    assert hedge.kind == "EMERGENCY_HEDGE" and hedge.side == "short"
    assert abs(hedge.target_quantity - .019) < 1e-9
    equal = replace(no_pending, short_quantity=.03, short_notional=3)
    assert decide_v3(settings, state, equal, market()).kind == "FREEZE"


def test_f_frozen_never_closes_red_position():
    frozen = replace(active_state(), state="FROZEN_HEDGE", frozen=object())
    action = decide_v3(V3Settings(rescue_enabled=False), frozen, active_account(equity=90), market(80))
    assert action.kind == "HOLD"
    assert action.kind not in {"CLOSE_SIDE", "CLOSE_ALL"}


def test_g_frozen_has_no_unlock_relock_algorithm():
    frozen = replace(active_state(), state="FROZEN_HEDGE", frozen=object())
    for price in (80, 90, 100, 110, 120):
        action = decide_v3(V3Settings(rescue_enabled=False), frozen, active_account(equity=90), market(price))
        assert action.kind == "HOLD"


def test_h_rescue_is_separate_and_live_requires_independent_environment():
    frozen = replace(active_state(), state="FROZEN_HEDGE", frozen=object())
    blocked = decide_v3(V3Settings(), frozen, active_account(equity=100), market())
    assert blocked.kind == "RESCUE_WAIT"
    allowed = decide_v3(V3Settings(), frozen,
                        active_account(equity=100, independent_rescue_account=True), market())
    assert (allowed.kind, allowed.side, allowed.target_notional) == ("OPEN_RESCUE", "long", 10)


def test_i_insufficient_margin_blocks_rescue_and_normal_orders():
    frozen = replace(active_state(), state="FROZEN_HEDGE", frozen=object())
    unsafe = active_account(equity=100, available_margin=5, independent_rescue_account=True)
    assert decide_v3(V3Settings(), frozen, unsafe, market()).kind == "RESCUE_WAIT"
    flat = account(available_margin=5)
    assert decide_v3(V3Settings(), V3State(), flat, market()).kind == "SAFE_WAIT"


def test_j_restart_reconstructs_exchange_sides_without_merging_them():
    state = active_state()
    rebuilt = reconcile_state(V3Settings(), state, active_account(
        long_quantity=.8, long_average=95, long_notional=76,
        short_quantity=.4, short_average=105, short_notional=42,
    ))
    assert rebuilt.long.quantity == .8 and rebuilt.long.average_entry == 95
    assert rebuilt.short.quantity == .4 and rebuilt.short.average_entry == 105


def test_k_same_snapshot_emits_same_single_action_for_idempotent_journal():
    settings, state, snapshot, tick = V3Settings(), active_state(), active_account(short_average=90), market(99.4)
    first = decide_v3(settings, state, snapshot, tick)
    second = decide_v3(settings, state, snapshot, tick)
    assert first == second and first.kind == "ADD_DCA"


def test_l_emergency_uses_equity_not_wallet_balance():
    snapshot = active_account(wallet_balance=137, equity=94)
    action = decide_v3(V3Settings(emergency_equity_trigger=95), active_state(), snapshot, market())
    assert action.kind in {"EMERGENCY_HEDGE", "FREEZE"}


def test_dca_limit_and_opposite_side_are_independent():
    state = active_state()
    state = replace(state, long=replace(state.long, dca_level=40))
    action = decide_v3(V3Settings(), state, active_account(short_average=90), market(99.4))
    assert action.kind == "HOLD"


def test_invalid_or_live_unsafe_settings_fail_closed():
    bad = V3Settings(leverage=500)
    assert decide_v3(bad, V3State(), account(), market()).kind == "API_ERROR"


def test_m_user_stop_blocks_every_risk_increasing_v3_action():
    for kind in ("OPEN_SIDE", "ADD_DCA", "EMERGENCY_HEDGE", "OPEN_RESCUE"):
        blocked = enforce_protective_only(V3Action(kind, side="long", target_notional=70), True)
        assert blocked.kind == "HOLD"
        assert blocked.safety is True
        assert blocked.target_notional == 0


def test_n_user_stop_keeps_risk_reducing_actions_available():
    for kind in ("CLOSE_SIDE", "CANCEL_PENDING", "HOLD"):
        original = V3Action(kind, side="long")
        assert enforce_protective_only(original, True) == original


def test_o_stopped_monitor_finishes_only_after_exchange_is_flat():
    flat = account(long_quantity=0, short_quantity=0, open_order_ids=())
    assert protective_monitor_is_complete(protective_only=True, enabled=False, account=flat)
    assert not protective_monitor_is_complete(
        protective_only=True,
        enabled=False,
        account=account(long_quantity=.01),
    )
    assert not protective_monitor_is_complete(
        protective_only=True,
        enabled=False,
        account=account(open_order_ids=("pending",)),
    )
    assert not protective_monitor_is_complete(protective_only=False, enabled=True, account=flat)
