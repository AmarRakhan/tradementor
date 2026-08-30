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


def test_runtime_source_contains_v6_start_hedge_full_tp_and_no_frozen_release_trigger():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    assert 'DCA_TRAILING = "TRAILING"' in src
    assert 'DCA_FROZEN = "FIXED_DURING_HEDGE"' in src
    assert '"lastDcaFillPrice"' in src
    assert '"hedgeReleasePrice"' in src
    assert "hedge_release_crossed(mark, release_price, primary_side)" in src
    assert "fresh_primary_qty * configured_hedge_ratio" in src
    assert "FOCUS_HEDGE_RELEASED_NET_GREEN" in src
    assert "FOCUS_V2_START_HEDGED" in src
    assert "FOCUS_V2_FULL_TP" in src
    assert "FOCUS_V2_TP_CLOSED_RESTART_PENDING" in src
    assert "initial_hedged_trailing" in src
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


def test_v6_source_guards_full_tp_until_hedge_is_flat_and_persists_restart_boundary():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    assert 'if hedge_qty <= 1e-12 and take_profit_reached' in src
    assert '"cycleStatus": "TP_EXECUTING"' in src
    assert 'confirmed_positions = client.position_risk(symbol)' in src
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
        return (kw["notional"]/kw["mark"],kw["mark"],f"cid-{len(calls)}",f"oid-{len(calls)}")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",execute)
    ref=_Ref(); client=_RuntimeClient(mark=100)
    result=engine.run_focus_v2_live_step(client=client,ref=ref,raw_state={},settings=_v6_settings(),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=[],timestamp_ms=1)
    assert result["action"]=="FOCUS_V2_START_HEDGED" and result["ordersSent"]==2
    assert calls==[("LONG","OPEN",7000.0),("SHORT","OPEN",7000.0)]
    saved=next(v for v in reversed(ref.values) if "focusV2History" in v)
    assert saved["focusV2State"]["cycleStatus"]=="TRAILING_HEDGED"
    assert saved["focusV2State"]["nextDcaPrice"]==pytest.approx(99.7)


def test_v6_first_dca_trails_up_even_with_start_hedge_active(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine,"_selected_symbol",lambda *_a,**_k:"BTCUSDT")
    raw={"focusV2State":{"cycleId":"c","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":0,
         "lastDcaFillPrice":0,"trailingHigh":100,"nextDcaPrice":99.7,"hedgeState":"ACTIVE","stateMachineVersion":6}}
    positions=[_pos("LONG",70,100,105),_pos("SHORT",70,100,105)]
    ref=_Ref(); result=engine.run_focus_v2_live_step(client=_RuntimeClient(positions,105),ref=ref,raw_state=raw,
        settings=_v6_settings(focusV2AmountsAreMargin=False),uid="u",account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=positions,timestamp_ms=2)
    assert result["action"]=="FOCUS_V2_TRAILING_HOLD"
    saved=ref.values[-1]["focusV2State"]
    assert saved["trailingHigh"]==pytest.approx(105)
    assert saved["nextDcaPrice"]==pytest.approx(104.685)
    assert saved["hedgeReleasePrice"]==0


def test_v6_full_tp_is_blocked_by_hedge_and_closes_when_flat(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine,"_selected_symbol",lambda *_a,**_k:"BTCUSDT")
    raw={"focusV2State":{"cycleId":"c","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":1,
         "lastDcaFillPrice":99,"dcaAnchorPrice":99,"trailingHigh":100,"hedgeState":"ACTIVE","stateMachineVersion":6}}
    hedged=[_pos("LONG",1,100,115,15),_pos("SHORT",1,99,115,-16)]
    ref=_Ref(); hold=engine.run_focus_v2_live_step(client=_RuntimeClient(hedged,115),ref=ref,raw_state=raw,
        settings=_v6_settings(focusV2AmountsAreMargin=False,focusV2HedgeReleaseRecoveryPct=.24),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=hedged,timestamp_ms=3)
    assert hold["action"]=="FOCUS_V2_TRAILING_HOLD"
    flat=[_pos("LONG",1,100,115,15)]
    client=_RuntimeClient(flat,115)
    def close(**kw): client.positions=[]; return (1.0,115.0,"tp-cid","tp-oid")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",close)
    ref2=_Ref(); closed=engine.run_focus_v2_live_step(client=client,ref=ref2,raw_state={"focusV2State":{**raw["focusV2State"],"hedgeState":"OFF"}},
        settings=_v6_settings(focusV2AmountsAreMargin=False),uid="u",account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=flat,timestamp_ms=4)
    assert closed["action"]=="FOCUS_V2_TP_CLOSED_RESTART_PENDING" and closed["autoRestart"] is True


def test_v6_auto_restart_boundary_is_persisted_and_next_tick_reopens_same_margin(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine,"_selected_symbol",lambda *_a,**_k:"BTCUSDT")
    monkeypatch.setattr(engine,"_resolved_leverage",lambda *_a,**_k:100)
    settings=_v6_settings()
    flat=[_pos("LONG",1,100,115,15)]
    client=_RuntimeClient(flat,115)
    close_calls=[]
    def close(**kw):
        close_calls.append((kw["side"],kw["action"],kw["notional"]))
        client.positions=[]
        return (1.0,115.0,"tp-cid","tp-oid")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",close)
    ref=_Ref(); raw={"focusV2State":{"cycleId":"old","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":0,
         "lastDcaFillPrice":0,"trailingHigh":115,"nextDcaPrice":114.655,"hedgeState":"OFF","stateMachineVersion":6}}
    result=engine.run_focus_v2_live_step(client=client,ref=ref,raw_state=raw,settings=settings,uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=flat,timestamp_ms=10)
    assert result["action"]=="FOCUS_V2_TP_CLOSED_RESTART_PENDING"
    boundary=ref.values[-1]["focusV2State"]
    assert boundary["cycleStatus"]=="RESTARTING" and boundary["restartPending"] is True and boundary["cycleId"]==""

    opens=[]
    def open_order(**kw):
        opens.append((kw["side"],kw["action"],kw["notional"]))
        return (kw["notional"]/kw["mark"],kw["mark"],f"cid-{len(opens)}",f"oid-{len(opens)}")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",open_order)
    ref2=_Ref(); client2=_RuntimeClient([],115)
    again=engine.run_focus_v2_live_step(client=client2,ref=ref2,raw_state={"focusV2State":boundary},settings=settings,uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=[],timestamp_ms=11)
    assert again["action"]=="FOCUS_V2_START_HEDGED"
    assert opens==[("LONG","OPEN",7000.0),("SHORT","OPEN",7000.0)]
    assert ref2.values[-1]["focusV2State"]["restartPending"] is False


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
        return (qty,kw["mark"],f"cid-{len(calls)}",f"oid-{len(calls)}")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",execute)
    raw={"focusV2State":{"cycleId":"c","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":0,
         "lastDcaFillPrice":0,"trailingHigh":100,"nextDcaPrice":99.7,"hedgeState":"ACTIVE","stateMachineVersion":6}}
    result=engine.run_focus_v2_live_step(client=client,ref=_Ref(),raw_state=raw,settings=_v6_settings(),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=client.positions,timestamp_ms=20)
    assert result["action"]=="FOCUS_V2_DCA_HEDGE_ACTIVE"
    assert calls[0]==("LONG","OPEN",2500.0)
    # Fresh confirmed LONG at the DCA mark is 9500 notional; existing SHORT is 7000, so only 2500 is missing.
    assert calls[1][0:2]==("SHORT","OPEN")
    assert calls[1][2]==pytest.approx(2500.0)
    assert result["hedgeTargetQty"]==pytest.approx((7000/100)+(2500/mark))
