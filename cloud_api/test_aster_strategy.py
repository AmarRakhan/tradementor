import pytest
from aster_strategy import *


def settings(**values):
    return AsterStrategySettings.from_mapping(values)


def account(ratio=.1, equity=120, start=120, used=0):
    return Account(equity, equity-used, ratio, start, used)


def test_defaults_capture_agreed_strategy():
    s = settings()
    assert (s.base_notional, s.maximum_pairs, s.universe_top_n) == (10, 5, 50)
    assert (s.long_dca_deviation, s.short_dca_deviation) == (.02, .05)
    assert (s.net_take_profit, s.momentum_reinvest_ratio) == (.005, .5)


def test_dca_levels_are_anchored_to_original_entry():
    s = settings()
    assert dca_trigger(s, Leg("LONG", 10, 100, 0), 98)
    assert not dca_trigger(s, Leg("LONG", 20, 100, 1), 97)
    assert dca_trigger(s, Leg("LONG", 20, 100, 1), 96)
    assert dca_trigger(s, Leg("SHORT", 10, 100, 0), 105)
    assert dca_trigger(s, Leg("SHORT", 20, 100, 1), 110)


def test_harvest_is_net_of_close_reopen_costs():
    s = settings()
    leg = Leg("LONG", 100, 100, unrealized_pnl=.60)
    assert harvest_due(s, leg, .04, .04)
    assert not harvest_due(s, Leg("LONG", 100, 100, unrealized_pnl=.55), .04, .04)


@pytest.mark.parametrize("ratio,mode",[(.49,"NORMAL"),(.50,"BLOCK"),(.70,"REDUCE"),(.80,"EMERGENCY")])
def test_margin_modes(ratio, mode): assert risk_mode(settings(), account(ratio)) == mode


def test_active_symbols_never_reenter_scanner():
    s = settings(enabled=True)
    pairs = [Pair("BTCUSDT", Leg("LONG",10,100), Leg("SHORT",10,100))]
    action = choose_next(s, account(), pairs, ["BTCUSDT","ETHUSDT"],
                         {"BTCUSDT":100,"ETHUSDT":10}, estimated_pair_margin={"BTCUSDT":1,"ETHUSDT":1})
    assert (action.kind, action.symbol) == ("OPEN_PAIR", "ETHUSDT")


def test_drawdown_pauses_new_pairs_but_not_strategy_state():
    action = choose_next(settings(enabled=True), account(equity=113, start=120), [], ["BTCUSDT"],
                         {"BTCUSDT":100}, estimated_pair_margin={"BTCUSDT":1})
    assert action.kind == "HOLD" and "drawdown" in action.reason


def test_pair_budget_prevents_one_pair_draining_bot():
    s = settings(enabled=True, maximumPairs=5, botMarginBudgetRatio=.5, pairBudgetTolerance=.05)
    assert pair_margin_cap(s, account(equity=100)) == pytest.approx(10.5)
    action = choose_next(s, account(equity=100), [], ["BTCUSDT"], {"BTCUSDT":100},
                         estimated_pair_margin={"BTCUSDT":11})
    assert action.kind == "HOLD"
