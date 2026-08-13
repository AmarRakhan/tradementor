from mexc_automation import (
    AccountSnapshot, AutoSettings, AutoState, MarketSignal, decide,
    AutoAction, initial_notional, maximum_long, plan_order_legs, signal_from_candles,
)


def signal(**changes):
    values = dict(timestamp=1_000, price=100.0, atr_percent=.01, lower_low=False, risk_score=10, recovery_score=10)
    values.update(changes)
    return MarketSignal(**values)


def account(**changes):
    values = dict(current_equity=125.0, available_equity=120.0)
    values.update(changes)
    return AccountSnapshot(**values)


def test_wallet_ratios_and_fixed_strategy_cap():
    settings = AutoSettings()
    assert initial_notional(settings, 400) == 25.0
    assert maximum_long(settings, 400) == 2_500.0
    assert initial_notional(settings, 125) == 7.8125


def test_empty_account_opens_first_long_and_orphan_short_is_closed():
    state = AutoState(125)
    action = decide(AutoSettings(), state, account(), signal())
    assert action.kind == "OPEN_LONG" and action.target_notional == 7.8125
    orphan = decide(AutoSettings(), state, account(short_notional=10), signal())
    assert orphan.kind == "CLOSE_SHORT" and orphan.safety


def test_dca_requires_lower_low_spacing_and_cooldown():
    state = AutoState(125, last_dca_price=100, last_order_time=900)
    active = account(long_notional=7.8125, weighted_long_entry=100)
    assert decide(AutoSettings(), state, active, signal(price=98, lower_low=True)).kind == "HOLD"
    ready = decide(AutoSettings(), state, active, signal(timestamp=1_200, price=98, lower_low=True))
    assert ready.kind == "ADD_LONG" and ready.target_notional == 9.375


def test_hedge_opens_rehedges_and_unwinds_in_steps():
    settings = AutoSettings()
    state = AutoState(125, last_dca_price=100)
    long = account(current_equity=115, long_notional=100, weighted_long_entry=100)
    protect = decide(settings, state, long, signal(risk_score=90))
    assert protect.kind == "SET_HEDGE" and protect.target_notional == 50
    hedged = account(current_equity=120, long_notional=100, short_notional=50, weighted_long_entry=100)
    unwind = decide(settings, state, hedged, signal(recovery_score=70))
    assert unwind.kind == "SET_HEDGE" and unwind.target_notional == 12.5
    rehedge = decide(settings, state, account(current_equity=115, long_notional=100, short_notional=25, weighted_long_entry=100), signal(risk_score=90))
    assert rehedge.kind == "SET_HEDGE" and rehedge.target_notional == 50


def test_hedge_hysteresis_blocks_order_churn_inside_cooldown():
    settings = AutoSettings(cooldown_seconds=180)
    state = AutoState(125, last_order_time=900)
    active = account(long_notional=100, short_notional=25, weighted_long_entry=100)
    action = decide(settings, state, active, signal(timestamp=1_000, risk_score=90))
    assert action.kind == "HOLD"


def test_take_profit_requires_price_and_net_profit():
    settings = AutoSettings()
    state = AutoState(125)
    active = account(long_notional=100, weighted_long_entry=100, net_session_pnl=.30)
    assert decide(settings, state, active, signal(price=100.5)).kind == "CLOSE_ALL"
    no_net = account(long_notional=100, weighted_long_entry=100, net_session_pnl=.10)
    assert decide(settings, state, no_net, signal(price=100.5)).kind == "HOLD"


def test_absolute_safety_overrides_strategy():
    state = AutoState(125)
    active = dict(long_notional=100, weighted_long_entry=100)
    assert decide(AutoSettings(), state, account(**active, margin_ratio=.75), signal()).kind == "CLOSE_ALL"
    assert decide(AutoSettings(), state, account(**active, liquidation_distance=.05), signal()).kind == "CLOSE_ALL"
    assert decide(AutoSettings(), state, account(**active, current_equity=90), signal()).kind == "CLOSE_ALL"
    assert decide(AutoSettings(), state, account(**active, margin_used=50), signal()).kind == "CLOSE_ALL"


def test_signal_engine_has_bounded_scores():
    candles = []
    for index in range(60):
        close = 100 - index * .1
        candles.append({"time": index * 60, "open": close + .05, "high": close + .2, "low": close - .2, "close": close, "volume": 100 + index})
    result = signal_from_candles(candles, candles)
    assert 0 <= result.risk_score <= 100
    assert 0 <= result.recovery_score <= 100
    assert result.risk_score > result.recovery_score


def test_invalid_settings_fail_closed():
    action = decide(AutoSettings(max_long_ratio=50), AutoState(125), account(), signal())
    assert action.kind == "PAUSE" and action.safety


def test_every_user_controlled_safety_value_is_validated():
    invalid = (
        AutoSettings(minimum_spacing=-.01), AutoSettings(atr_multiplier=-1),
        AutoSettings(cooldown_seconds=-1), AutoSettings(take_profit=0),
        AutoSettings(minimum_net_profit=-.1), AutoSettings(hedge_drawdown_trigger=0),
        AutoSettings(risk_trigger=101), AutoSettings(recovery_steps=(40, 55, 70, 101)),
        AutoSettings(minimum_liquidation_distance=0),
    )
    assert all(item.validate() for item in invalid)


def test_open_and_dca_never_use_more_than_buffered_free_cross_margin():
    settings = AutoSettings()
    state = AutoState(125)
    first = decide(settings, state, account(available_equity=.01), signal())
    assert first.kind == "OPEN_LONG" and first.target_notional == 1.8
    active = account(
        available_equity=.01, long_notional=7.8125,
        weighted_long_entry=100,
    )
    dca = decide(settings, AutoState(125, last_dca_price=100), active, signal(timestamp=1_200, price=98, lower_low=True))
    assert dca.kind == "ADD_LONG" and dca.target_notional == 1.8


def test_unfundable_required_hedge_closes_instead_of_adding_unprotected_risk():
    active = account(available_equity=0, current_equity=115, long_notional=100, weighted_long_entry=100)
    action = decide(AutoSettings(), AutoState(125), active, signal(risk_score=90))
    assert action.kind == "CLOSE_ALL" and action.safety


def test_order_plan_uses_documented_hedge_mode_side_codes_and_exact_close_volume():
    contract = {"contractSize": .0001, "minVol": 1, "volUnit": 1}
    positions = [
        {"side": "long", "notionalUsd": 100, "volume": 15, "positionId": "11"},
        {"side": "short", "notionalUsd": 50, "volume": 8, "positionId": "22"},
    ]
    assert plan_order_legs(AutoAction("OPEN_LONG", 8.5), [], contract, 65_000)[0].side_code == 1
    assert plan_order_legs(AutoAction("SET_HEDGE", 75), positions, contract, 65_000)[0].side_code == 3
    reduce = plan_order_legs(AutoAction("SET_HEDGE", 0), positions, contract, 65_000)[0]
    assert (reduce.side_code, reduce.volume, reduce.position_id) == (2, 8, 22)
    close = plan_order_legs(AutoAction("CLOSE_ALL"), positions, contract, 65_000)
    assert [(item.side_code, item.volume) for item in close] == [(2, 8), (4, 15)]


def test_order_plan_never_rounds_a_small_ratio_up_to_exchange_minimum():
    contract = {"contractSize": .0001, "minVol": 1, "volUnit": 1}
    try:
        plan_order_legs(AutoAction("OPEN_LONG", 2), [], contract, 65_000)
        assert False, "undersized order must be blocked"
    except ValueError as exc:
        assert "BELOW EXCHANGE MINIMUM" in str(exc)
