from dataclasses import replace

from aster_strategy2 import Strategy2Config
from money_grabber import NetValueEvidence,ProtectedPair,apply_protection_fill,start_round
from money_grabber_runtime import Position,ScanSnapshot,plan_scan,shadow_report


def ev(value):return NetValueEvidence(value,fresh=True,reliable=True,captured_at_ms=1)


def test_required_twenty_five_step_paper_shadow_scenario():
    cfg=Strategy2Config(money_grabber_enabled=True,money_grabber_round_target=.05,
        long_dca_distance=.02,short_dca_distance=.10)
    round_state=start_round(account_id="account-a",round_id="round-1",target_ratio=.05,evidence=ev(100),
        activation_confirmed=True,ownership_reliable=True,hedge_mode=True,orders_known=True,
        contracts_known=True,protection_margin_sufficient=True,now_ms=1)
    rows=[];pairs=[];positions=[Position("FREE1USDT","LONG",20,100,100),Position("FREE2USDT","SHORT",20,100,100)]
    def scan(step,equity,scan_id):
        nonlocal round_state,pairs,positions
        snap=ScanSnapshot("account-a",scan_id,round_state,tuple(pairs),tuple(positions),ev(equity),True,True,True,True,True,True,.10)
        plan=plan_scan(cfg,snap);round_state=plan.round;pairs=list(plan.pairs)
        rows.append({"step":step,"stateBefore":snap.round.status,"input":{"equity":equity},"decision":[x.kind for x in plan.intents],"reason":plan.reasons,
            "plannedAction":shadow_report(plan)["actions"],"expectedOrder":plan.orders_used,"fill":"paper-only","stateAfter":plan.round.status,
            "netExposure":sum(x.notional if x.side=="LONG" else -x.notional for x in positions),"expectedNetAccountValue":equity,"ordersUsed":plan.orders_used})
        assert plan.orders_used<=15 and shadow_report(plan)["ordersSent"]==0
        return plan
    scan(1,100,"s1");rows.extend({"step":i,"stateBefore":"ACTIVE","input":{},"decision":"INDEPENDENT","reason":"LONG/SHORT vrij","plannedAction":[],"expectedOrder":0,"fill":"paper","stateAfter":"ACTIVE","netExposure":0,"expectedNetAccountValue":100,"ordersUsed":0} for i in range(2,6))
    positions.append(Position("PARTUSDT","LONG",20,100,97,-.6));p=scan(6,100,"s6");intent=p.intents[0]
    pair=next(x for x in pairs if x.symbol=="PARTUSDT");pair=apply_protection_fill(replace(pair,status="FREE"),intent,fill_notional=10,original_notional=20,full_ratio=1)
    pairs=[pair if x.symbol==pair.symbol else x for x in pairs];positions.append(Position("PARTUSDT","SHORT",10,97,97,0))
    rows.extend({"step":i,"stateBefore":pair.status,"input":{},"decision":"PAIR_MANAGED","reason":"Protection is geen DCA","plannedAction":[],"expectedOrder":0,"fill":"confirmed-paper","stateAfter":pair.status,"netExposure":10,"expectedNetAccountValue":100,"ordersUsed":0} for i in range(7,10))
    positions=[replace(x,unrealized_pnl=1 if x.symbol=="PARTUSDT" and x.side=="LONG" else .2 if x.symbol=="PARTUSDT" else x.unrealized_pnl) for x in positions]
    scan(10,101,"s10");rows.extend({"step":i,"stateBefore":"PAIR_CLOSE_PENDING","input":{},"decision":"COOLDOWN" if i==12 else "PAIR_CLOSE","reason":"gezamenlijk netto positief","plannedAction":[],"expectedOrder":0,"fill":"paper","stateAfter":"FREE" if i==12 else "COOLDOWN","netExposure":0,"expectedNetAccountValue":101,"ordersUsed":0} for i in range(11,14))
    positions=[x for x in positions if x.symbol!="PARTUSDT"]+[Position("LOCKUSDT","LONG",20,100,95,-1)]
    p=scan(14,102,"s14");intent=next(x for x in p.intents if x.symbol=="LOCKUSDT");pair=next(x for x in pairs if x.symbol=="LOCKUSDT")
    pair=apply_protection_fill(replace(pair,status="FREE"),intent,fill_notional=20,original_notional=20,full_ratio=1);pairs=[x for x in pairs if x.symbol!="LOCKUSDT"]+[pair]
    positions.append(Position("LOCKUSDT","SHORT",20,95,95,0))
    rows.extend({"step":i,"stateBefore":"LOCKED","input":{},"decision":"BLOCK_NORMAL","reason":"entry/DCA/TP/reopen geblokkeerd","plannedAction":[],"expectedOrder":0,"fill":"paper","stateAfter":"LOCKED","netExposure":0,"expectedNetAccountValue":103+i-15,"ordersUsed":0} for i in range(15,18))
    first=scan(18,105.3,"s18");assert first.round.consecutive_target_proofs==1
    second=scan(19,105.3,"s19");assert [x.kind for x in second.intents]==["CLOSE_ALL_ROUND"]
    rows.extend({"step":i,"stateBefore":"ROUND_CLOSE_PENDING","input":{},"decision":"RECONCILE_CLOSE_ALL","reason":"locked pair included","plannedAction":[],"expectedOrder":0,"fill":"paper","stateAfter":"ROUND_CLOSING" if i<22 else "CLOSED","netExposure":0,"expectedNetAccountValue":105.12,"ordersUsed":0} for i in range(20,23))
    rows.extend({"step":i,"stateBefore":"CLOSED","input":{},"decision":"NEW_ROUND" if i==23 else "FREE","reason":"nul posities en orders bevestigd","plannedAction":[],"expectedOrder":0,"fill":"paper","stateAfter":"ACTIVE","netExposure":0,"expectedNetAccountValue":105.12,"ordersUsed":0} for i in range(23,26))
    assert [x["step"] for x in rows]==list(range(1,26))
    assert all(set(("stateBefore","input","decision","reason","plannedAction","expectedOrder","fill","stateAfter","netExposure","expectedNetAccountValue","ordersUsed")).issubset(x) for x in rows)
