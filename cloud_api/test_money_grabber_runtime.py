from aster_strategy2 import Strategy2Config
from money_grabber import NetValueEvidence, ProtectedPair, start_round
from money_grabber_runtime import Position,ScanSnapshot,plan_scan,shadow_report


def evidence(equity=100):return NetValueEvidence(equity,fresh=True,reliable=True,captured_at_ms=1)
def round_():return start_round(account_id="a",round_id="r",target_ratio=.05,evidence=evidence(),
    activation_confirmed=True,ownership_reliable=True,hedge_mode=True,orders_known=True,
    contracts_known=True,protection_margin_sufficient=True,now_ms=1)
def snapshot(*,positions=(),pairs=(),equity=100,scan="s"):
    return ScanSnapshot("a",scan,round_(),tuple(pairs),tuple(positions),evidence(equity),True,True,True,True,True,True)


def test_off_has_exactly_no_money_grabber_decisions_or_blocks():
    plan=plan_scan(Strategy2Config(),snapshot(positions=[Position("BTCUSDT","LONG",20,100,95)]))
    assert plan.intents==() and plan.blocked_symbols==frozenset()


def test_first_protection_has_top_priority_and_blocks_symbol():
    cfg=Strategy2Config(money_grabber_enabled=True)
    plan=plan_scan(cfg,snapshot(positions=[Position("BTCUSDT","LONG",20,100,97)]))
    assert plan.intents[0].kind=="PAIR_PROTECTION_RISK_REDUCING"
    assert plan.intents[0].side=="SHORT" and plan.intents[0].target_notional==10
    assert "BTCUSDT" in plan.blocked_symbols


def test_losing_short_protects_with_long():
    cfg=Strategy2Config(money_grabber_enabled=True)
    plan=plan_scan(cfg,snapshot(positions=[Position("ETHUSDT","SHORT",20,100,103)]))
    assert plan.intents[0].side=="LONG"


def test_stale_or_unproven_snapshot_fails_closed_without_intent():
    s=snapshot(positions=[Position("BTCUSDT","LONG",20,100,95)])
    s=ScanSnapshot(**{**s.__dict__,"ownership_reliable":False})
    assert plan_scan(Strategy2Config(money_grabber_enabled=True),s).intents==()


def test_pair_close_is_after_protection_and_uses_joint_net_result():
    cfg=Strategy2Config(money_grabber_enabled=True)
    locked=ProtectedPair("a","r","ETHUSDT","LONG","LOCKED",20,20)
    positions=[Position("BTCUSDT","LONG",20,100,97),
        Position("ETHUSDT","LONG",20,100,90,-2,paid_fees=.1,expected_exit_fees=.05),
        Position("ETHUSDT","SHORT",20,100,90,3,paid_fees=.1,expected_exit_fees=.05)]
    plan=plan_scan(cfg,snapshot(positions=positions,pairs=[locked]))
    assert [x.kind for x in plan.intents]==["PAIR_PROTECTION_RISK_REDUCING","CLOSE_PROTECTED_PAIR"]


def test_double_target_proof_yields_exactly_one_close_all_and_blocks_every_symbol():
    cfg=Strategy2Config(money_grabber_enabled=True)
    s=snapshot(positions=[Position("BTCUSDT","LONG",20,100,101)],equity=106)
    first=plan_scan(cfg,s)
    assert not first.intents and first.round.consecutive_target_proofs==1
    s=ScanSnapshot(**{**s.__dict__,"round":first.round,"scan_id":"s2"})
    second=plan_scan(cfg,s)
    assert len(second.intents)==1 and second.intents[0].kind=="CLOSE_ALL_ROUND"
    assert second.blocked_symbols==frozenset({"BTCUSDT"})


def test_scan_never_plans_more_than_fifteen_orders():
    cfg=Strategy2Config(money_grabber_enabled=True)
    positions=[Position(f"C{i}USDT","LONG",20,100,95) for i in range(30)]
    plan=plan_scan(cfg,snapshot(positions=positions))
    assert plan.orders_used==15 and plan.orders_remaining==0
    assert shadow_report(plan)["ordersSent"]==0
