import pytest

from aster_strategy2 import Strategy2Config, LegState, PortfolioState, apply_fill, dca_due
from money_grabber import (NetValueEvidence, ProtectedPair, apply_protection_fill,
    complete_round, normal_action_allowed, observe_round_target, plan_pair_close,
    plan_protection, start_round)


def evidence(equity=100, **overrides):
    values={"visible_equity":equity,"fresh":True,"reliable":True,"captured_at_ms":1}
    values.update(overrides)
    return NetValueEvidence(**values)


def active_round(target=.05):
    return start_round(account_id="a",round_id="r",target_ratio=target,evidence=evidence(),
        activation_confirmed=True,ownership_reliable=True,hedge_mode=True,orders_known=True,
        contracts_known=True,protection_margin_sufficient=True,now_ms=1)


def pair(side="LONG", status="FREE"):
    return ProtectedPair("a","r","BTCUSDT",side,status)


def protection(p, *, entry=100, mark=97, intent="p1"):
    return plan_protection(pair=p,original_notional=20,weighted_entry=entry,mark_price=mark,
        first_threshold=.02,first_ratio=.5,full_threshold=.04,full_ratio=1,
        hedge_mode=True,ownership_reliable=True,exchange_reliable=True,orders_known=True,
        contract_known=True,margin_sufficient=True,intent_id=intent)


def test_feature_defaults_off_and_round_defaults_safe():
    cfg=Strategy2Config()
    assert cfg.money_grabber_enabled is False
    assert cfg.money_grabber_round_target == .05
    assert cfg.public_dict()["moneyGrabberEnabled"] is False


@pytest.mark.parametrize("raw",[
    {"moneyGrabberRoundTarget":0},
    {"moneyGrabberFullThreshold":.01,"moneyGrabberFirstThreshold":.02},
    {"moneyGrabberFirstRatio":.75,"moneyGrabberFullRatio":.5},
    {"moneyGrabberRoundTarget":float("inf")},
])
def test_invalid_money_grabber_configuration_is_rejected(raw):
    with pytest.raises(ValueError): Strategy2Config.from_mapping(raw)


def test_activation_requires_explicit_preview_and_all_safety_proofs():
    args=dict(account_id="a",round_id="r",target_ratio=.05,evidence=evidence(),
        activation_confirmed=False,ownership_reliable=True,hedge_mode=True,orders_known=True,
        contracts_known=True,protection_margin_sufficient=True,now_ms=1)
    with pytest.raises(ValueError): start_round(**args)
    args.update(activation_confirmed=True,hedge_mode=False)
    with pytest.raises(ValueError): start_round(**args)


def test_round_target_uses_expected_net_after_costs_and_debounces():
    r=active_round()
    r,intent=observe_round_target(r,evidence(105.30,expected_exit_fees=.20,slippage_buffer=.20),close_buffer=0,intent_id="c")
    assert intent is None and r.consecutive_target_proofs == 0
    r,intent=observe_round_target(r,evidence(105.70,expected_exit_fees=.25,slippage_buffer=.20),close_buffer=.20,intent_id="c")
    assert intent is None and r.consecutive_target_proofs == 1
    r,intent=observe_round_target(r,evidence(105.70,expected_exit_fees=.25,slippage_buffer=.20),close_buffer=.20,intent_id="c")
    assert intent is not None and intent.kind == "CLOSE_ALL_ROUND"


def test_visible_105_with_costs_does_not_close():
    r=active_round()
    for _ in range(3):
        r,intent=observe_round_target(r,evidence(105,expected_exit_fees=.1),close_buffer=0,intent_id="c")
        assert intent is None


def test_losing_long_opens_short_and_losing_short_opens_long_same_symbol():
    assert protection(pair("LONG")).side == "SHORT"
    assert protection(pair("SHORT"),mark=103).side == "LONG"


def test_first_fill_partial_full_fill_locked_and_blocks_all_normal_actions():
    p=pair(); intent=protection(p)
    p=apply_protection_fill(p,intent,fill_notional=10,original_notional=20,full_ratio=1)
    assert p.status == "PARTIAL_PROTECTION" and p.residual_notional == 10
    next_intent=protection(p,mark=95,intent="p2")
    p=apply_protection_fill(p,next_intent,fill_notional=10,original_notional=20,full_ratio=1)
    assert p.status == "LOCKED" and p.residual_notional == 0
    assert all(not normal_action_allowed(p,x) for x in ("ENTRY","DCA","TAKE_PROFIT","AUTO_REOPEN"))


def test_protection_fill_is_not_dca_and_directional_dca_remains_independent():
    cfg=Strategy2Config(long_dca_distance=.02,short_dca_distance=.10)
    portfolio=PortfolioState(100,100,0,0,0,0)
    long=LegState("LONG","l",20,100,98,dca_count=0)
    short=LegState("SHORT","s",20,100,109,dca_count=0)
    assert dca_due(cfg,long) is True and dca_due(cfg,short) is False
    long=apply_fill(long,fill_notional=10,fill_price=98)
    assert long.dca_count == 1 and short.dca_count == 0 and portfolio.exchange_reliable
    p=pair(); p=apply_protection_fill(p,protection(p),fill_notional=10,original_notional=20,full_ratio=1)
    assert p.protection_notional == 10 and short.dca_count == 0


def test_wrong_symbol_direction_account_or_round_fill_is_rejected():
    p=pair(); intent=protection(p)
    for changed in (intent.__class__(**{**intent.__dict__,"symbol":"ETHUSDT"}),
                    intent.__class__(**{**intent.__dict__,"side":"LONG"}),
                    intent.__class__(**{**intent.__dict__,"account_id":"b"}),
                    intent.__class__(**{**intent.__dict__,"round_id":"x"})):
        with pytest.raises(ValueError): apply_protection_fill(p,changed,fill_notional=10,original_notional=20,full_ratio=1)


def test_pair_close_requires_net_profit_after_all_costs():
    p=ProtectedPair("a","r","BTCUSDT","LONG","LOCKED",20,20)
    common=dict(pair=p,original_pnl=-20,protection_pnl=20.5,funding=0,paid_fees=.2,
        expected_exit_fees=.2,slippage_buffer=.2,other_costs=0,minimum_buffer=.01,
        reliable=True,intent_id="close")
    assert plan_pair_close(**common) is None
    common["protection_pnl"]=21
    assert plan_pair_close(**common).reduce_only is True


def test_round_cannot_close_until_positions_and_orders_are_zero():
    r=active_round()
    r,_=observe_round_target(r,evidence(106),close_buffer=0,intent_id="c")
    r,_=observe_round_target(r,evidence(106),close_buffer=0,intent_id="c")
    with pytest.raises(ValueError): complete_round(r,positions_zero=False,orders_zero=True,final_evidence=evidence(105.12))
    closed,end=complete_round(r,positions_zero=True,orders_zero=True,final_evidence=evidence(105.12))
    assert closed.status == "CLOSED" and end == 105.12


def test_stale_data_never_opens_or_closes_exposure():
    assert plan_protection(pair=pair(),original_notional=20,weighted_entry=100,mark_price=95,
        first_threshold=.02,first_ratio=.5,full_threshold=.04,full_ratio=1,hedge_mode=True,
        ownership_reliable=True,exchange_reliable=False,orders_known=True,contract_known=True,
        margin_sufficient=True,intent_id="x") is None
    with pytest.raises(ValueError): observe_round_target(active_round(),evidence(106,fresh=False),close_buffer=0,intent_id="c")
