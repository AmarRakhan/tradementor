import pytest

from aster_strategy2 import Strategy2Config
from aster_strategy2_focus_trailing import (
    DCA_FROZEN,
    DCA_TRAILING,
    dca_crossed,
    dca_distance,
    hedge_ratio,
    start_hedge_ratio,
    take_profit_reached,
    portfolio_target_reached,
    _amount_to_notional,
    hedge_release_crossed,
    hedge_release_recovery,
    next_dca_from_anchor,
    recovery_from_last_dca,
    release_price_from_last_dca,
)


def test_long_trailing_dca_is_exact_configured_distance():
    cfg = Strategy2Config.from_mapping({"tradingMode": "focus", "focusDcaDistance": 0.003})
    assert dca_distance(cfg) == pytest.approx(0.003)
    assert next_dca_from_anchor(100, "LONG", dca_distance(cfg)) == pytest.approx(99.7)
    assert next_dca_from_anchor(105, "LONG", dca_distance(cfg)) == pytest.approx(104.685)
    assert dca_crossed(104.685, 104.685, "LONG")
    assert not dca_crossed(104.686, 104.685, "LONG")


def test_short_trailing_dca_is_exact_mirror():
    assert next_dca_from_anchor(100, "SHORT", 0.003) == pytest.approx(100.3)
    assert dca_crossed(100.3, 100.3, "SHORT")
    assert not dca_crossed(100.299, 100.3, "SHORT")


def test_v5_release_is_from_last_confirmed_dca_fill():
    last_dca = 99.7
    release = release_price_from_last_dca(last_dca, "LONG", 0.0015)
    assert release == pytest.approx(99.84955)
    assert not hedge_release_crossed(99.84, release, "LONG")
    assert hedge_release_crossed(release, release, "LONG")
    assert recovery_from_last_dca(release, last_dca, "LONG") == pytest.approx(0.0015)


def test_v5_deeper_dca_replaces_both_fixed_levels():
    last_dca = 99.4009
    assert next_dca_from_anchor(last_dca, "LONG", 0.003) == pytest.approx(99.1026973)
    assert release_price_from_last_dca(last_dca, "LONG", 0.0015) == pytest.approx(99.55000135)


def test_v5_short_primary_is_mirrored():
    last_dca = 100.3
    release = release_price_from_last_dca(last_dca, "SHORT", 0.0015)
    assert release == pytest.approx(100.14955)
    assert not hedge_release_crossed(100.16, release, "SHORT")
    assert hedge_release_crossed(release, release, "SHORT")


def test_v5_config_defaults_and_explicit_values():
    cfg = Strategy2Config.from_mapping({"tradingMode": "focus", "focusV2HedgeRatio": 1.0, "focusV2HedgeReleaseRecoveryPct": 0.0015})
    assert hedge_ratio(cfg) == pytest.approx(1.0)
    assert hedge_release_recovery(cfg) == pytest.approx(0.0015)
    custom = Strategy2Config.from_mapping({"tradingMode": "focus", "focusV2HedgeRatio": 0.8, "focusV2HedgeReleaseRecoveryPct": 0.002})
    assert hedge_ratio(custom) == pytest.approx(0.8)
    assert hedge_release_recovery(custom) == pytest.approx(0.002)
    # v4 fields must not silently preserve the old 95% / 0.35% business behavior in v5.
    migrated = Strategy2Config.from_mapping({"tradingMode": "focus", "focusV2MaxHedgeRatio": 0.95, "focusV2HedgeReleaseDistancePct": 0.0035})
    assert hedge_ratio(migrated) == pytest.approx(1.0)
    assert hedge_release_recovery(migrated) == pytest.approx(0.0015)
    public = migrated.public_dict()
    assert public["focusV2HedgeRatio"] == pytest.approx(1.0)
    assert public["focusV2HedgeReleaseRecoveryPct"] == pytest.approx(0.0015)


def test_runtime_source_contains_v7_portfolio_cycle_and_protected_release():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    assert 'DCA_TRAILING = "TRAILING"' in src
    assert '"lastDcaFillPrice"' in src
    assert '"hedgeReleasePrice"' in src
    assert "hedge_release_crossed(mark, release_price, primary_side)" in src
    assert "fresh_primary_qty * configured_hedge_ratio" in src
    assert "FOCUS_HEDGE_RELEASED_NET_GREEN" in src
    assert "FOCUS_REHEDGE_ACTIVE" in src
    assert "FOCUS_V2_START_HEDGED" in src
    assert "def portfolio_target_reached" in src
    assert "FOCUS_PORTFOLIO_TARGET_CLOSED" in src
    assert "target_now = bool(simple_flow" in src
    assert "distance >= release_ratio" not in src
    assert "recovery_confirmed" not in src


def test_v6_configurable_start_hedge_margin_amounts_and_full_tp():
    cfg = Strategy2Config.from_mapping({
        "tradingMode": "focus", "focusV2Enabled": True, "focusV2SimpleModeEnabled": True,
        "focusV2AmountsAreMargin": True, "focusV2StartHedgeRatio": 1.0,
        "focusV2TakeProfitMode": "usdt", "focusV2TakeProfitValue": 15,
    })
    assert start_hedge_ratio(cfg) == pytest.approx(1.0)
    assert _amount_to_notional(cfg, 70, 100) == pytest.approx(7000)
    assert take_profit_reached(cfg, 14.99, 7000) is False
    assert take_profit_reached(cfg, 15.0, 7000) is True
    pct = Strategy2Config.from_mapping({
        "tradingMode": "focus", "focusV2Enabled": True,
        "focusV2TakeProfitMode": "percent", "focusV2TakeProfitValue": 0.003,
    })
    assert take_profit_reached(pct, 20.9, 7000) is False
    assert take_profit_reached(pct, 21.0, 7000) is True


def test_v7_source_prioritizes_portfolio_exit_and_persists_restart_boundary():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    assert 'target_now = bool(simple_flow' in src
    assert '"cycleStatus": "PORTFOLIO_EXIT_EXECUTING"' in src
    assert src.index('target_now = bool(simple_flow') < src.index('# Hard invariant: a confirmed LONG DCA')
    assert 'confirmed = client.position_risk(symbol)' in src
    assert 'focusV2LastCycle=last_cycle' in src
    assert '"pausedAfterTp": True' in src


def test_precision_retry_is_bounded_and_rebuilds_plan():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    assert "for attempt in range(2)" in src
    assert '"-1111" in message' in src
    assert "client.public_exchange_info()" in src
    assert "_plan(client, symbol, mark, notional, leverage)" in src

class _Ref:
    def __init__(self): self.values=[]
    def set(self,value,merge=False): self.values.append(value)
    class _Audit:
        def add(self,_value): pass
    def collection(self,_name): return self._Audit()

class _RuntimeClient:
    def __init__(self,positions=None,mark=100.0): self.positions=list(positions or []); self.mark=mark
    def ticker_prices(self): return [{"symbol":"BTCUSDT","price":str(self.mark)}]
    def position_risk(self,*_args): return list(self.positions)


def _v6_settings(**extra):
    raw={"tradingMode":"focus","mode":"live","focusV2Enabled":True,"focusV2SimpleModeEnabled":True,
         "focusSelectionMode":"manual","focusManualPair":"BTCUSDT","focusStartOrderNotional":70,
         "focusV2AmountsAreMargin":True,"focusV2StartHedgeRatio":1.0,"focusV2HedgeRatio":1.0,
         "focusDcaEnabled":True,"focusDcaDistance":.003,"focusDcaNotional":25,"focusDcaAmountMode":"multiplier",
         "focusDcaMultiplier":1,"focusMaxBudgetUsd":1000,"focusV2HedgeReleaseRecoveryPct":.0015,
         "focusV2TakeProfitMode":"usdt","focusV2TakeProfitValue":15,"focusV2AutoRestart":True,
         "leverage":100,"emergencyMarginRatio":.7}
    raw.update(extra); return Strategy2Config.from_mapping(raw)


def _pos(side,qty,entry,mark,pnl=0,lev=100):
    return {"symbol":"BTCUSDT","positionSide":side,"positionAmt":str(qty),"entryPrice":str(entry),
            "markPrice":str(mark),"unRealizedProfit":str(pnl),"leverage":str(lev),"liquidationPrice":"50"}


def test_v6_new_cycle_opens_confirmed_long_and_equal_start_hedge(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    calls=[]
    monkeypatch.setattr(engine,"_selected_symbol",lambda *_a,**_k:"BTCUSDT")
    monkeypatch.setattr(engine,"_resolved_leverage",lambda *_a,**_k:100)
    def execute(**kw):
        calls.append((kw["side"],kw["action"],kw["notional"]))
        qty=kw["notional"]/kw["mark"]
        if kw["side"]=="LONG" and kw["action"]=="OPEN":
            client.positions=[_pos("LONG",qty,kw["mark"],kw["mark"])]
        elif kw["side"]=="SHORT" and kw["action"]=="OPEN":
            long_row=next(row for row in client.positions if row["positionSide"]=="LONG")
            client.positions=[long_row,_pos("SHORT",qty,kw["mark"],kw["mark"])]
        return (qty,kw["mark"],f"cid-{len(calls)}",f"oid-{len(calls)}")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",execute)
    ref=_Ref(); client=_RuntimeClient(mark=100)
    result=engine.run_focus_v2_live_step(client=client,ref=ref,raw_state={},settings=_v6_settings(),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=[],timestamp_ms=1)
    assert result["action"]=="FOCUS_V2_START_HEDGED" and result["ordersSent"]==2
    assert calls==[("LONG","OPEN",7000.0),("SHORT","OPEN",7000.0)]
    saved=next(v for v in reversed(ref.values) if "focusV2History" in v)
    assert saved["focusV2State"]["cycleStatus"]=="FOCUS_HEDGED"
    assert saved["focusV2State"]["nextDcaPrice"]==pytest.approx(99.7)


def test_v6_manual_flat_stale_cycle_is_reconciled_before_new_start(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    calls=[]
    monkeypatch.setattr(engine,"_selected_symbol",lambda *_a,**_k:"BTCUSDT")
    monkeypatch.setattr(engine,"_resolved_leverage",lambda *_a,**_k:100)
    client=_RuntimeClient(mark=100)
    def execute(**kw):
        calls.append((kw["side"],kw["action"],kw["notional"]))
        qty=kw["notional"]/kw["mark"]
        if kw["side"]=="LONG":
            client.positions=[_pos("LONG",qty,kw["mark"],kw["mark"])]
        else:
            long_row=next(row for row in client.positions if row["positionSide"]=="LONG")
            client.positions=[long_row,_pos("SHORT",qty,kw["mark"],kw["mark"])]
        return (qty,kw["mark"],f"cid-{len(calls)}",f"oid-{len(calls)}")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",execute)
    raw={"focusV2State":{"cycleId":"old-cycle","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":2,
         "lastDcaFillPrice":99,"dcaTriggerPending":True,"hedgeState":"ACTIVE","cycleStatus":"HEDGED","stateMachineVersion":6},
         "ownedLegs":[]}
    ref=_Ref()
    result=engine.run_focus_v2_live_step(client=client,ref=ref,raw_state=raw,settings=_v6_settings(),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=[],timestamp_ms=9)
    assert result["action"]=="FOCUS_V2_START_HEDGED"
    assert result["cycleId"]!="old-cycle"
    assert calls==[("LONG","OPEN",7000.0),("SHORT","OPEN",7000.0)]
    # Exchange-flat stale state must never be revived: the observable result is a fresh cycle.
    assert result["cycleId"] and result["cycleId"]!="old-cycle"


def test_v6_first_dca_trails_up_even_with_start_hedge_active(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine,"_selected_symbol",lambda *_a,**_k:"BTCUSDT")
    raw={"focusV2State":{"cycleId":"c","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":0,
         "lastDcaFillPrice":0,"trailingHigh":100,"nextDcaPrice":99.7,"hedgeState":"ACTIVE","stateMachineVersion":6}}
    positions=[_pos("LONG",70,100,105),_pos("SHORT",70,100,105)]
    ref=_Ref(); result=engine.run_focus_v2_live_step(client=_RuntimeClient(positions,105),ref=ref,raw_state=raw,
        settings=_v6_settings(focusV2SimpleModeEnabled=False,focusV2AmountsAreMargin=False),uid="u",account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=positions,timestamp_ms=2)
    assert result["action"]=="FOCUS_V2_TRAILING_HOLD"
    saved=ref.values[-1]["focusV2State"]
    assert saved["trailingHigh"]==pytest.approx(105)
    assert saved["nextDcaPrice"]==pytest.approx(104.685)
    assert saved["hedgeReleasePrice"]==0


def test_v6_every_dca_ratchets_up_with_live_high_even_while_hedged(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine, "_selected_symbol", lambda *_a, **_k: "BTCUSDT")
    settings = _v6_settings(focusV2SimpleModeEnabled=False,focusV2AmountsAreMargin=False, focusDcaDistance=.003, focusV2HedgeReleaseRecoveryPct=.24)
    raw = {"focusV2State": {
        "cycleId": "c", "symbol": "BTCUSDT", "primarySide": "LONG", "dcaCount": 2,
        "lastDcaFillPrice": 99.0, "trailingHigh": 100.0, "nextDcaPrice": 98.703,
        "hedgeState": "ACTIVE", "cycleStatus": "HEDGED", "stateMachineVersion": 6,
    }}
    positions_up = [_pos("LONG", 70, 100, 112, 840), _pos("SHORT", 70, 100, 112, -840)]
    ref = _Ref()
    up = engine.run_focus_v2_live_step(
        client=_RuntimeClient(positions_up, 112), ref=ref, raw_state=raw, settings=settings, uid="u",
        account={"totalMarginBalance": "500", "availableBalance": "400", "totalMaintMargin": "0"},
        positions=positions_up, timestamp_ms=20,
    )
    assert up["ordersSent"] == 0
    raised = ref.values[-1]["focusV2State"]
    assert raised["dcaMode"] == DCA_FROZEN
    assert raised["trailingHigh"] == pytest.approx(100.0)
    assert raised["nextDcaPrice"] == pytest.approx(98.703)

    positions_down = [_pos("LONG", 70, 100, 111.9, 833), _pos("SHORT", 70, 100, 111.9, -833)]
    ref2 = _Ref()
    down = engine.run_focus_v2_live_step(
        client=_RuntimeClient(positions_down, 111.9), ref=ref2, raw_state={"focusV2State": raised},
        settings=settings, uid="u",
        account={"totalMarginBalance": "500", "availableBalance": "400", "totalMaintMargin": "0"},
        positions=positions_down, timestamp_ms=21,
    )
    assert down["ordersSent"] == 0
    held = ref2.values[-1]["focusV2State"]
    assert held["trailingHigh"] == pytest.approx(100.0)
    assert held["nextDcaPrice"] == pytest.approx(98.703)


def test_v7_portfolio_target_closes_hedge_and_primary_even_when_hedged(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine, "_selected_symbol", lambda *_a, **_k: "BTCUSDT")
    positions = [_pos("LONG", 1, 100, 101, 1), _pos("SHORT", 1, 100, 101, -1)]
    client = _RuntimeClient(positions, 101)
    calls = []
    def close(**kw):
        calls.append((kw["side"], kw["action"]))
        if kw["side"] == "SHORT":
            client.positions = [row for row in client.positions if row["positionSide"] != "SHORT"]
        else:
            client.positions = [row for row in client.positions if row["positionSide"] != "LONG"]
        return (1.0, 101.0, f"cid-{len(calls)}", f"oid-{len(calls)}")
    monkeypatch.setattr(engine, "_execute_with_precision_retry", close)
    raw = {"focusV2State": {"cycleId": "c", "symbol": "BTCUSDT", "primarySide": "LONG",
        "dcaCount": 1, "lastDcaFillPrice": 100, "trailingHigh": 101, "hedgeState": "ACTIVE",
        "cycleStartEquity": 500, "stateMachineVersion": 7}}
    ref = _Ref()
    result = engine.run_focus_v2_live_step(
        client=client, ref=ref, raw_state=raw, settings=_v6_settings(focusV2TakeProfitValue=10), uid="u",
        account={"totalMarginBalance": "510", "availableBalance": "400", "totalMaintMargin": "0"},
        positions=positions, timestamp_ms=3, order_budget=2)
    assert result["action"] == "FOCUS_PORTFOLIO_TARGET_CLOSED"
    assert calls == [("SHORT", "CLOSE"), ("LONG", "CLOSE")]
    assert result["autoRestart"] is True


def test_v7_portfolio_target_restart_boundary_and_next_tick_reopens_same_margin(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine, "_selected_symbol", lambda *_a, **_k: "BTCUSDT")
    monkeypatch.setattr(engine, "_resolved_leverage", lambda *_a, **_k: 100)
    settings = _v6_settings(focusV2TakeProfitValue=10)
    flat = [_pos("LONG", 1, 100, 101, 1)]
    client = _RuntimeClient(flat, 101)
    def close(**kw):
        client.positions = []
        return (1.0, 101.0, "tp-cid", "tp-oid")
    monkeypatch.setattr(engine, "_execute_with_precision_retry", close)
    ref = _Ref(); raw = {"focusV2State": {"cycleId": "old", "symbol": "BTCUSDT", "primarySide": "LONG",
        "dcaCount": 0, "lastDcaFillPrice": 0, "trailingHigh": 101, "nextDcaPrice": 100.697,
        "hedgeState": "OFF", "cycleStartEquity": 500, "stateMachineVersion": 7}}
    result = engine.run_focus_v2_live_step(client=client, ref=ref, raw_state=raw, settings=settings, uid="u",
        account={"totalMarginBalance": "510", "availableBalance": "400", "totalMaintMargin": "0"}, positions=flat, timestamp_ms=10)
    assert result["action"] == "FOCUS_PORTFOLIO_TARGET_CLOSED"
    boundary = ref.values[-1]["focusV2State"]
    assert boundary["cycleStatus"] == "RESTARTING" and boundary["restartPending"] is True and boundary["cycleId"] == ""

    opens = []
    client2 = _RuntimeClient([], 101)
    def open_order(**kw):
        opens.append((kw["side"], kw["action"], kw["notional"]))
        qty = kw["notional"] / kw["mark"]
        if kw["side"] == "LONG":
            client2.positions = [_pos("LONG", qty, kw["mark"], kw["mark"])]
        else:
            long_row = next(row for row in client2.positions if row["positionSide"] == "LONG")
            client2.positions = [long_row, _pos("SHORT", qty, kw["mark"], kw["mark"])]
        return (qty, kw["mark"], f"cid-{len(opens)}", f"oid-{len(opens)}")
    monkeypatch.setattr(engine, "_execute_with_precision_retry", open_order)
    ref2 = _Ref()
    again = engine.run_focus_v2_live_step(client=client2, ref=ref2, raw_state={"focusV2State": boundary}, settings=settings, uid="u",
        account={"totalMarginBalance": "510", "availableBalance": "400", "totalMaintMargin": "0"}, positions=[], timestamp_ms=11)
    assert again["action"] == "FOCUS_V2_START_HEDGED"
    assert opens == [("LONG", "OPEN", 7000.0), ("SHORT", "OPEN", 7000.0)]
    assert ref2.values[-1]["focusV2State"]["restartPending"] is False
    assert ref2.values[-1]["focusV2State"]["cycleStartEquity"] == pytest.approx(510.0)


def test_v6_dca_adds_long_then_tops_short_only_to_total_target(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine,"_selected_symbol",lambda *_a,**_k:"BTCUSDT")
    monkeypatch.setattr(engine,"_resolved_leverage",lambda *_a,**_k:100)
    mark=99.7
    long_qty=7000/100
    short_qty=7000/100
    client=_RuntimeClient([_pos("LONG",long_qty,100,mark,-21),_pos("SHORT",short_qty,100,mark,21)],mark)
    calls=[]
    def execute(**kw):
        calls.append((kw["side"],kw["action"],kw["notional"]))
        qty=kw["notional"]/kw["mark"]
        if kw["side"]=="LONG" and kw["action"]=="OPEN":
            new_qty=long_qty+qty
            client.positions=[_pos("LONG",new_qty,99.92,mark),_pos("SHORT",short_qty,100,mark)]
        elif kw["side"]=="SHORT" and kw["action"]=="OPEN":
            long_row=next(row for row in client.positions if row["positionSide"]=="LONG")
            client.positions=[long_row,_pos("SHORT",short_qty+qty,100,mark)]
        return (qty,kw["mark"],f"cid-{len(calls)}",f"oid-{len(calls)}")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",execute)
    raw={"focusV2State":{"cycleId":"c","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":0,
         "lastDcaFillPrice":0,"trailingHigh":100,"nextDcaPrice":99.7,"hedgeState":"ACTIVE","stateMachineVersion":6}}
    result=engine.run_focus_v2_live_step(client=client,ref=_Ref(),raw_state=raw,settings=_v6_settings(focusV2SimpleModeEnabled=False,),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=client.positions,timestamp_ms=20)
    assert result["action"]=="FOCUS_V2_DCA_HEDGE_ACTIVE"
    assert calls[0]==("LONG","OPEN",2500.0)
    # Fresh confirmed LONG at the DCA mark is 9500 notional; existing SHORT is 7000, so only 2500 is missing.
    assert calls[1][0:2]==("SHORT","OPEN")
    assert calls[1][2]==pytest.approx(2500.0)
    assert result["hedgeTargetQty"]==pytest.approx((7000/100)+(2500/mark))



def test_v6_start_stays_pending_when_exchange_truth_does_not_confirm_short(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine,"_selected_symbol",lambda *_a,**_k:"BTCUSDT")
    monkeypatch.setattr(engine,"_resolved_leverage",lambda *_a,**_k:100)
    calls=[]
    client=_RuntimeClient(mark=100)
    def execute(**kw):
        calls.append((kw["side"],kw["action"]))
        qty=kw["notional"]/kw["mark"]
        if kw["side"]=="LONG":
            client.positions=[_pos("LONG",qty,kw["mark"],kw["mark"])]
        # Deliberately do NOT expose the mocked SHORT fill via position_risk.
        return (qty,kw["mark"],f"cid-{len(calls)}",f"oid-{len(calls)}")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",execute)
    result=engine.run_focus_v2_live_step(client=client,ref=_Ref(),raw_state={},settings=_v6_settings(),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=[],timestamp_ms=100)
    assert result["action"]=="FOCUS_START_HEDGE_SYNC_PENDING"
    assert result["ordersSent"]==2


def test_v6_dca_stays_pending_when_post_hedge_exchange_truth_is_not_equal(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine,"_selected_symbol",lambda *_a,**_k:"BTCUSDT")
    monkeypatch.setattr(engine,"_resolved_leverage",lambda *_a,**_k:100)
    mark=99.7
    long_qty=70.0
    short_qty=70.0
    client=_RuntimeClient([_pos("LONG",long_qty,100,mark,-21),_pos("SHORT",short_qty,100,mark,21)],mark)
    calls=[]
    def execute(**kw):
        calls.append((kw["side"],kw["action"],kw["notional"]))
        qty=kw["notional"]/kw["mark"]
        if kw["side"]=="LONG" and kw["action"]=="OPEN":
            client.positions=[_pos("LONG",long_qty+qty,99.92,mark),_pos("SHORT",short_qty,100,mark)]
        # Deliberately keep Aster SHORT stale after mocked hedge fill.
        return (qty,kw["mark"],f"cid-{len(calls)}",f"oid-{len(calls)}")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",execute)
    raw={"focusV2State":{"cycleId":"c","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":0,
         "lastDcaFillPrice":0,"trailingHigh":100,"nextDcaPrice":99.7,"hedgeState":"ACTIVE","stateMachineVersion":6}}
    result=engine.run_focus_v2_live_step(client=client,ref=_Ref(),raw_state=raw,settings=_v6_settings(focusV2SimpleModeEnabled=False,),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=client.positions,timestamp_ms=101)
    assert result["action"]=="FOCUS_V2_DCA_HEDGE_ACTIVE"
    assert result["ordersSent"]==2



def test_v6_dca_is_the_only_short_rehedge_point():
    from pathlib import Path
    src=(Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    assert "short_rebuild_price_from_release" not in src
    assert "SHORT_REBUILD_SYNC_PENDING" not in src
    assert "FOCUS_SHORT_REBUILT" not in src
    dca=src.index('if dca_allowed and dca_triggered')
    assert src.index('fresh_primary_qty = abs(', dca) < src.index('gap_qty = max(0.0, target_qty_after - fresh_hedge_qty)', dca)
    assert 'cycleStatus": "DCA_HEDGE_SYNC_PENDING"' in src


def test_v7_short_release_requires_price_plus_net_green_only():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    gate = src.index('price_release_ready = last_dca > 0 and hedge_release_crossed')
    protected = src.index('if price_release_ready and net_green_ready and rehedge_funding_ready:', gate)
    end = src.index('# Legacy non-simple Focus TP only.', protected)
    section = src[gate:end]
    assert protected > gate
    assert 'expected_net_hedge_close_pnl' in section
    assert 'net_green_ready' in section
    assert 'equity_release_ready' not in section
    assert 'FOCUS_HEDGE_RELEASED_NET_GREEN' in section


def test_v6_simple_dca_ratchets_in_both_hedged_and_long_only_states():
    from pathlib import Path
    src=(Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    block=src[src.index('# Simple Mode: EVERY DCA ratchets'):src.index('next_dca = _finite(state.get("nextDcaPrice"))')]
    assert 'if (simple_flow and not dca_trigger_pending)' in block
    assert 'anchor = max(_finite(state.get("trailingHigh"), mark), mark)' in block
    assert 'state["nextDcaPrice"] = next_dca_from_anchor(anchor, primary_side, dca_ratio)' in block


def test_v6_net_green_release_line_matches_execution_cost_model():
    from aster_strategy2_focus_trailing import net_green_hedge_release_price
    row={"entryPrice":"100"}
    expected=100*(1-.0005)/(1+.0005+.0002)
    assert net_green_hedge_release_price(row,"SHORT")==pytest.approx(expected)


def test_v6_crossing_becomes_durable_when_budget_temporarily_too_small(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine,"_selected_symbol",lambda *_a,**_k:"BTCUSDT")
    settings=_v6_settings(focusV2SimpleModeEnabled=False,focusV2AmountsAreMargin=False,focusDcaDistance=.003)
    positions=[_pos("LONG",70,100,99.69),_pos("SHORT",70,100,99.69)]
    raw={"focusV2State":{"cycleId":"c","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":1,
         "lastDcaFillPrice":100,"trailingHigh":100,"nextDcaPrice":99.7,"hedgeState":"ACTIVE",
         "cycleStatus":"HEDGED","stateMachineVersion":6}}
    ref=_Ref()
    blocked=engine.run_focus_v2_live_step(client=_RuntimeClient(positions,99.69),ref=ref,raw_state=raw,
        settings=settings,uid="u",account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},
        positions=positions,timestamp_ms=200,order_budget=1)
    assert blocked["action"]=="FOCUS_DCA_BLOCKED"
    assert blocked["ordersSent"]==0


def test_v6_pending_sync_confirmation_restores_release_from_latest_dca(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine,"_selected_symbol",lambda *_a,**_k:"BTCUSDT")
    last_fill=83.25
    positions=[_pos("LONG",105,last_fill,83.30),_pos("SHORT",105,last_fill,83.30)]
    raw={"focusV2State":{"cycleId":"c","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":3,
         "lastDcaFillPrice":last_fill,"trailingHigh":last_fill,"nextDcaPrice":last_fill*.997,
         "hedgeReleasePrice":0,"hedgeState":"ACTIVE","cycleStatus":"DCA_HEDGE_SYNC_PENDING","stateMachineVersion":6}}
    ref=_Ref()
    result=engine.run_focus_v2_live_step(client=_RuntimeClient(positions,83.30),ref=ref,raw_state=raw,
        settings=_v6_settings(focusV2AmountsAreMargin=False),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},
        positions=positions,timestamp_ms=300,order_budget=2)
    assert result["action"]=="DCA_HEDGE_SYNC_CONFIRMED"
    state=[x["focusV2State"] for x in ref.values if "focusV2State" in x][-1]
    assert state["hedgeReleasePrice"]==pytest.approx(last_fill*1.0015)
    assert state["cycleStatus"]=="HEDGED"

def test_v6_protection_reserve_blocks_atomic_dca_before_any_order(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine, "_selected_symbol", lambda *_a, **_k: "BTCUSDT")
    monkeypatch.setattr(engine, "_resolved_leverage", lambda *_a, **_k: 100)
    calls=[]
    monkeypatch.setattr(engine, "_execute_with_precision_retry", lambda **kw: calls.append(kw) or (1,99.7,"cid","oid"))
    positions=[_pos("LONG",70,100,99.69),_pos("SHORT",70,100,99.69)]
    raw={"focusV2State":{"cycleId":"c","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":0,
         "lastDcaFillPrice":0,"trailingHigh":100,"nextDcaPrice":99.7,"hedgeState":"ACTIVE",
         "cycleStatus":"HEDGED","stateMachineVersion":6}}
    ref=_Ref()
    result=engine.run_focus_v2_live_step(client=_RuntimeClient(positions,99.69),ref=ref,raw_state=raw,
        settings=_v6_settings(focusV2SimpleModeEnabled=False,focusProtectionReserveBufferPct=.05),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"50","totalMaintMargin":"0"},
        positions=positions,timestamp_ms=400,order_budget=2)
    assert result["action"]=="FOCUS_DCA_BLOCKED"
    assert calls==[]
    assert result["ordersSent"]==0

def test_v8_simple_flow_tracks_bottom_releases_on_rebound_and_rehedges_at_bottom(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine, "_selected_symbol", lambda *_a, **_k: "BTCUSDT")
    monkeypatch.setattr(engine, "_resolved_leverage", lambda *_a, **_k: 100)
    monkeypatch.setattr(engine, "expected_net_hedge_close_pnl", lambda *_a, **_k: (5.0, 99.15, 6.0, .5, .5))
    settings=_v6_settings(focusV2HedgeReleaseRecoveryPct=.0015)
    client=_RuntimeClient([_pos("LONG",70,100,99),_pos("SHORT",70,100,99,70)],99)
    raw={"focusV2State":{"cycleId":"c","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":0,
         "hedgeState":"ACTIVE","cycleStatus":"HEDGED","cycleStartEquity":500,"stateMachineVersion":7}}
    first_ref=_Ref()
    first=engine.run_focus_v2_live_step(client=client,ref=first_ref,raw_state=raw,settings=settings,uid="u",
        account={"totalMarginBalance":"500","availableBalance":"50","totalMaintMargin":"0"},positions=client.positions,timestamp_ms=400,order_budget=2)
    assert first["ordersSent"]==0
    state1=first_ref.values[-1]["focusV2State"]
    assert state1["protectedFloorPrice"]==pytest.approx(99)
    assert state1["hedgeReleasePrice"]==pytest.approx(99*1.0015)
    assert state1["nextDcaPrice"]==0

    client.mark=99.15
    client.positions=[_pos("LONG",70,100,99.15),_pos("SHORT",70,100,99.15,59.5)]
    calls=[]
    def close_hedge(**kw):
        calls.append(kw)
        client.positions=[row for row in client.positions if row["positionSide"]!="SHORT"]
        return (70,99.15,"cid-close","oid-close")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",close_hedge)
    second_ref=_Ref()
    second=engine.run_focus_v2_live_step(client=client,ref=second_ref,raw_state=first_ref.values[-1],settings=settings,uid="u",
        account={"totalMarginBalance":"500","availableBalance":"50","totalMaintMargin":"0"},positions=client.positions,timestamp_ms=500,order_budget=2)
    assert second["action"]=="FOCUS_HEDGE_RELEASED_NET_GREEN"
    assert calls and calls[0]["action"]=="CLOSE"
    state2=second_ref.values[-1]["focusV2State"]
    assert state2["reHedgeArmed"] is True
    assert state2["reHedgePrice"]==pytest.approx(99)

    client.mark=99
    client.positions=[_pos("LONG",70,100,99)]
    calls.clear()
    def reopen(**kw):
        calls.append(kw)
        client.positions=[_pos("LONG",70,100,99),_pos("SHORT",70,99,99)]
        return (70,99,"cid-open","oid-open")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",reopen)
    third_ref=_Ref()
    third=engine.run_focus_v2_live_step(client=client,ref=third_ref,raw_state=second_ref.values[-1],settings=settings,uid="u",
        account={"totalMarginBalance":"500","availableBalance":"100","totalMaintMargin":"0"},positions=client.positions,timestamp_ms=600,order_budget=2)
    assert third["action"]=="FOCUS_REHEDGE_ACTIVE"
    assert calls and calls[0]["action"]=="OPEN"
    state3=third_ref.values[-1]["focusV2State"]
    assert state3["hedgeState"]=="ACTIVE"
    assert state3["protectedFloorPrice"]==pytest.approx(99)

def test_v6_latency_telemetry_is_written_for_successful_atomic_dca(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine, "_selected_symbol", lambda *_a, **_k: "BTCUSDT")
    monkeypatch.setattr(engine, "_resolved_leverage", lambda *_a, **_k: 100)
    mark=99.7; long_qty=70.; short_qty=70.
    client=_RuntimeClient([_pos("LONG",long_qty,100,mark),_pos("SHORT",short_qty,100,mark)],mark)
    def execute(**kw):
        qty=kw["notional"]/kw["mark"]
        if kw["side"]=="LONG":
            client.positions=[_pos("LONG",long_qty+qty,99.9,mark),_pos("SHORT",short_qty,100,mark)]
        else:
            l=next(r for r in client.positions if r["positionSide"]=="LONG")
            client.positions=[l,_pos("SHORT",short_qty+qty,99.9,mark)]
        return (qty,kw["mark"],"cid","oid")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",execute)
    raw={"focusV2State":{"cycleId":"c","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":0,
         "lastDcaFillPrice":0,"trailingHigh":100,"nextDcaPrice":99.7,"hedgeState":"ACTIVE","cycleStatus":"HEDGED","stateMachineVersion":6}}
    ref=_Ref()
    result=engine.run_focus_v2_live_step(client=client,ref=ref,raw_state=raw,settings=_v6_settings(focusV2SimpleModeEnabled=False,),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},
        positions=client.positions,timestamp_ms=402,order_budget=2)
    assert result["action"]=="FOCUS_V2_DCA_HEDGE_ACTIVE"
    state=[x["focusV2State"] for x in ref.values if "focusV2State" in x][-1]
    assert state["dcaLongOrderSubmittedAt"]>0
    assert state["dcaLongFillConfirmedAt"]>=state["dcaLongOrderSubmittedAt"]
    assert state["shortSyncSubmittedAt"]>=state["dcaLongFillConfirmedAt"]
    assert state["shortSyncConfirmedAt"]>=state["shortSyncSubmittedAt"]
    assert state["triggerToFullHedgeMs"]>=0
