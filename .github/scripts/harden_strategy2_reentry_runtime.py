from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'marker not found in {path}: {old[:120]!r}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')


# Emit the stale-state diagnostic after reconciliation has actually populated
# reconciled_closed. The state removal already worked; this fixes the runtime
# visibility and gives the re-entry path a directly testable audit action.
replace_once(
    'cloud_api/aster_multi_bb.py',
    '''    actions: list[dict[str, Any]] = []\n    for key in reconciled_closed:\n        actions.append({"kind": "REENTRY_STATE_CLEARED", "key": key, "reason": "exchange position is flat"})\n\n    # Exchange truth reconciles every already-managed leg; a manual add never resets/increments the automatic DCA counter.\n''',
    '''    actions: list[dict[str, Any]] = []\n\n    # Exchange truth reconciles every already-managed leg; a manual add never resets/increments the automatic DCA counter.\n''',
)
replace_once(
    'cloud_api/aster_multi_bb.py',
    '''        st.update({"lastKnownQty": qty, "lastKnownEntry": entry, "leverage": leverage, "updatedAtMs": timestamp_ms})\n        account_equity = _f(account.get("totalMarginBalance", account.get("marginBalance", account.get("equity", account.get("totalWalletBalance")))))\n        st.update(position_action_preview(row=row, state=st, settings=settings, account_equity=account_equity))\n        state[key] = st\n\n    # Management priority: full TP, then capped DCA.\n''',
    '''        st.update({"lastKnownQty": qty, "lastKnownEntry": entry, "leverage": leverage, "updatedAtMs": timestamp_ms})\n        account_equity = _f(account.get("totalMarginBalance", account.get("marginBalance", account.get("equity", account.get("totalWalletBalance")))))\n        st.update(position_action_preview(row=row, state=st, settings=settings, account_equity=account_equity))\n        state[key] = st\n\n    for key in reconciled_closed:\n        actions.append({"kind": "REENTRY_STATE_CLEARED", "key": key, "reason": "exchange position is flat"})\n\n    # Management priority: full TP, then capped DCA.\n''',
)

# Add runtime tests, not just source-contract tests.
p = Path('cloud_api/test_aster_multi_bb.py')
text = p.read_text(encoding='utf-8')
block = r'''


def test_manual_reentry_clears_flat_exchange_state_and_replans_same_coin():
    stale={"multiBbPositions":{"AAAUSDT|LONG":{"dcaCount":4,"lastBotFillPrice":95,"lastKnownQty":2,"lastKnownEntry":100,"cycleStartedAtMs":1,"botManaged":True}}}
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"100"}],prices={"AAAUSDT":100},leverage=100)
    settings=manual_cfg([{"symbol":"AAAUSDT","side":"LONG"}],maximumPositions=1,longSlots=1,shortSlots=0)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state=stale,settings=settings,uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert any(x["kind"]=="REENTRY_STATE_CLEARED" and x["key"]=="AAAUSDT|LONG" for x in r["actions"])
    entry=next(x for x in r["actions"] if x["kind"]=="ENTRY")
    assert entry["symbol"]=="AAAUSDT" and entry["side"]=="LONG"
    assert r["entryStatus"]=="ENTRY_PLANNED"


def test_manual_coin_a_to_b_to_a_never_keeps_old_symbol_as_a_strategy_seat():
    stale_a={"multiBbPositions":{"AAAUSDT|LONG":{"dcaCount":1,"lastBotFillPrice":100,"lastKnownQty":1,"lastKnownEntry":100,"cycleStartedAtMs":1,"botManaged":True}}}
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"100"},{"symbol":"BBBUSDT","quoteVolume":"90"}],prices={"AAAUSDT":100,"BBBUSDT":100},leverage=100)
    b=manual_cfg([{"symbol":"BBBUSDT","side":"LONG"}],maximumPositions=1,longSlots=1,shortSlots=0)
    rb=run_multi_bb_step(client=c,ref=Ref(),raw_state=stale_a,settings=b,uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert any(x["kind"]=="ENTRY" and x["symbol"]=="BBBUSDT" for x in rb["actions"])
    stale_b={"multiBbPositions":{"BBBUSDT|LONG":{"dcaCount":0,"lastBotFillPrice":100,"lastKnownQty":1,"lastKnownEntry":100,"cycleStartedAtMs":2,"botManaged":True}}}
    a=manual_cfg([{"symbol":"AAAUSDT","side":"LONG"}],maximumPositions=1,longSlots=1,shortSlots=0)
    ra=run_multi_bb_step(client=c,ref=Ref(),raw_state=stale_b,settings=a,uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000)+1,dry_run=True)
    assert any(x["kind"]=="ENTRY" and x["symbol"]=="AAAUSDT" for x in ra["actions"])
    assert ra["entryStatus"]=="ENTRY_PLANNED"


def test_tier_reduction_waits_for_margin_without_stopping_strategy():
    class TierClient(Client):
        def leverage_brackets(self, symbol=None):
            s=symbol or "AAAUSDT"
            return [{"symbol":s,"brackets":[
                {"notionalFloor":"0","notionalCap":"3000","initialLeverage":"300","maintMarginRatio":".004"},
                {"notionalFloor":"3000","notionalCap":"10000","initialLeverage":"75","maintMarginRatio":".01"},
                {"notionalFloor":"10000","notionalCap":"0","initialLeverage":"50","maintMarginRatio":".02"},
            ]}]
    pos={"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"29","entryPrice":"100","markPrice":"99","leverage":"300"}
    state={"multiBbPositions":{"AAAUSDT|LONG":{"dcaCount":0,"lastBotFillPrice":100,"lastKnownQty":29,"lastKnownEntry":100,"cycleStartedAtMs":1,"botManaged":True}}}
    c=TierClient(positions=[pos],tickers=[{"symbol":"AAAUSDT","quoteVolume":"100"}],prices={"AAAUSDT":99},leverage=300)
    settings=manual_cfg([{"symbol":"AAAUSDT","side":"LONG"}],minimumLeverage=300,entryMarginUsd=5,dcaMarginUsd=2,dcaDistance=.003,maximumPositions=1,longSlots=1,shortSlots=0)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state=state,settings=settings,uid="u",account={"availableBalance":"1"},positions=[pos],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    wait=next(x for x in r["actions"] if x["kind"]=="DCA_MARGIN_WAIT")
    assert wait["reason"]=="INSUFFICIENT_MARGIN_FOR_TIER_LEVERAGE_REDUCTION"
    assert wait["targetLeverage"]==75
    assert not any(x["kind"]=="DCA" for x in r["actions"])
    assert r["status"]=="simulated"
'''
if 'test_manual_reentry_clears_flat_exchange_state_and_replans_same_coin' not in text:
    p.write_text(text + block, encoding='utf-8')

print('Strategy 2 runtime re-entry hardening applied')
