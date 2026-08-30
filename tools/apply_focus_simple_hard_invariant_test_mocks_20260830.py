from pathlib import Path

P = Path('cloud_api/test_aster_strategy2_focus_trailing.py')
s = P.read_text(encoding='utf-8')


def replace_once(old: str, new: str, label: str) -> None:
    global s
    count = s.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly one match, got {count}')
    s = s.replace(old, new, 1)


# Happy-path start test: a mocked confirmed fill must also mutate fake Aster position truth.
replace_once(
'''    def execute(**kw):
        calls.append((kw["side"],kw["action"],kw["notional"]))
        return (kw["notional"]/kw["mark"],kw["mark"],f"cid-{len(calls)}",f"oid-{len(calls)}")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",execute)
    ref=_Ref(); client=_RuntimeClient(mark=100)
''',
'''    def execute(**kw):
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
''',
'start happy path mock')

# New hard invariant uses FOCUS_HEDGED after Aster confirms equality.
s = s.replace('assert saved["focusV2State"]["cycleStatus"]=="TRAILING_HEDGED"',
              'assert saved["focusV2State"]["cycleStatus"]=="FOCUS_HEDGED"', 1)

# Auto-restart happy-path mock must similarly expose both confirmed positions.
replace_once(
'''    def open_order(**kw):
        opens.append((kw["side"],kw["action"],kw["notional"]))
        return (kw["notional"]/kw["mark"],kw["mark"],f"cid-{len(opens)}",f"oid-{len(opens)}")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",open_order)
    ref2=_Ref(); client2=_RuntimeClient([],115)
''',
'''    def open_order(**kw):
        opens.append((kw["side"],kw["action"],kw["notional"]))
        qty=kw["notional"]/kw["mark"]
        if kw["side"]=="LONG" and kw["action"]=="OPEN":
            client2.positions=[_pos("LONG",qty,kw["mark"],kw["mark"])]
        elif kw["side"]=="SHORT" and kw["action"]=="OPEN":
            long_row=next(row for row in client2.positions if row["positionSide"]=="LONG")
            client2.positions=[long_row,_pos("SHORT",qty,kw["mark"],kw["mark"])]
        return (qty,kw["mark"],f"cid-{len(opens)}",f"oid-{len(opens)}")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",open_order)
    ref2=_Ref(); client2=_RuntimeClient([],115)
''',
'auto restart happy path mock')

# DCA happy-path mock must apply the SHORT fill to fake Aster truth before the final reread.
replace_once(
'''        if kw["side"]=="LONG" and kw["action"]=="OPEN":
            new_qty=long_qty+qty
            client.positions=[_pos("LONG",new_qty,99.92,mark),_pos("SHORT",short_qty,100,mark)]
        return (qty,kw["mark"],f"cid-{len(calls)}",f"oid-{len(calls)}")
''',
'''        if kw["side"]=="LONG" and kw["action"]=="OPEN":
            new_qty=long_qty+qty
            client.positions=[_pos("LONG",new_qty,99.92,mark),_pos("SHORT",short_qty,100,mark)]
        elif kw["side"]=="SHORT" and kw["action"]=="OPEN":
            long_row=next(row for row in client.positions if row["positionSide"]=="LONG")
            client.positions=[long_row,_pos("SHORT",short_qty+qty,100,mark)]
        return (qty,kw["mark"],f"cid-{len(calls)}",f"oid-{len(calls)}")
''',
'DCA happy path mock')

# Explicitly retain tests for the newly-required mismatch/pending behavior.
s += r'''


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
    result=engine.run_focus_v2_live_step(client=client,ref=_Ref(),raw_state=raw,settings=_v6_settings(),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"400","totalMaintMargin":"0"},positions=client.positions,timestamp_ms=101)
    assert result["action"]=="DCA_HEDGE_SYNC_PENDING"
    assert result["ordersSent"]==2
'''

P.write_text(s, encoding='utf-8')
print('Updated Focus V2 test mocks for exchange-truth invariants')
