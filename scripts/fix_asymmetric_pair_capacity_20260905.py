from pathlib import Path

p = Path('cloud_api/aster_multi_bb.py')
s = p.read_text()

old = '''    active_symbols = {k.split("|", 1)[0] for k in active}
    account_position_count = len(active)
    account_remaining_capacity = max(0, settings.maximum_positions - account_position_count)
    strategy_active_keys = {key for key in active if key in state or (settings.manual_symbol_selection_enabled and key in selected_keys)}
    long_count = sum(1 for k in strategy_active_keys if k.endswith("|LONG")); short_count = sum(1 for k in strategy_active_keys if k.endswith("|SHORT"))
    long_need = max(0, settings.long_slots - long_count); short_need = max(0, settings.short_slots - short_count)
'''
new = '''    active_symbols = {k.split("|", 1)[0] for k in active}
    account_position_count = len(active)
    strategy_active_keys = {key for key in active if key in state or (settings.manual_symbol_selection_enabled and key in selected_keys)}
    long_count = sum(1 for k in strategy_active_keys if k.endswith("|LONG")); short_count = sum(1 for k in strategy_active_keys if k.endswith("|SHORT"))
    active_pair_count = sum(1 for key, row in state.items() if key.endswith("|LONG") and row.get("asymmetricHedge") and key in active and (row.get("pairedShortPending") or str(row.get("pairedShortKey") or "") in active))
    if settings.asymmetric_hedge_enabled:
        # Gekoppelde-parencapaciteit geldt uitsluitend voor NIEUWE asymmetrische cycli.
        # Bestaande Strategy-2 posities blijven intact en mogen de nieuwe pair allocator niet blokkeren.
        pair_need = max(0, settings.long_slots - active_pair_count)
        long_need = pair_need; short_need = pair_need
        account_remaining_capacity = max(0, 50 - account_position_count)
    else:
        pair_need = 0
        long_need = max(0, settings.long_slots - long_count); short_need = max(0, settings.short_slots - short_count)
        account_remaining_capacity = max(0, settings.maximum_positions - account_position_count)
'''
assert old in s, 'capacity block not found'
s = s.replace(old, new, 1)

old = '''        account_position_count += consumed
        account_remaining_capacity = max(0, settings.maximum_positions - account_position_count)
        if side == "LONG":
            long_count += 1; long_need = max(0, settings.long_slots - long_count)
            if consumed == 2: short_count += 1; short_need = max(0, settings.short_slots - short_count)
        else:
            short_count += 1; short_need = max(0, settings.short_slots - short_count)
'''
new = '''        account_position_count += consumed
        if settings.asymmetric_hedge_enabled:
            account_remaining_capacity = max(0, 50 - account_position_count)
            active_pair_count += 1
            pair_need = max(0, settings.long_slots - active_pair_count)
            long_need = pair_need; short_need = pair_need
            long_count += 1
            if consumed == 2: short_count += 1
        else:
            account_remaining_capacity = max(0, settings.maximum_positions - account_position_count)
            if side == "LONG":
                long_count += 1; long_need = max(0, settings.long_slots - long_count)
            else:
                short_count += 1; short_need = max(0, settings.short_slots - short_count)
'''
assert old in s, 'post-entry capacity block not found'
s = s.replace(old, new, 1)

old = '''    remaining_slots = long_need + short_need
    next_required_margin = min(minimum_margin_rejections, default=None)
    if entry_rows and remaining_slots > 0:
        entry_status = "PARTIAL_FILL_PLANNED" if dry_run else "PARTIAL_FILL_SUBMITTED"
        entry_reason = f"{len(entry_rows)} nieuwe positie(s) verwerkt; nog {remaining_slots} botslots vrij"
'''
new = '''    remaining_slots = pair_need if settings.asymmetric_hedge_enabled else long_need + short_need
    next_required_margin = min(minimum_margin_rejections, default=None)
    if entry_rows and remaining_slots > 0:
        entry_status = "PARTIAL_FILL_PLANNED" if dry_run else "PARTIAL_FILL_SUBMITTED"
        entry_reason = (f"{len(entry_rows)} nieuwe gekoppelde cycli verwerkt; nog {remaining_slots} paar/paaren vrij" if settings.asymmetric_hedge_enabled else f"{len(entry_rows)} nieuwe positie(s) verwerkt; nog {remaining_slots} botslots vrij")
'''
assert old in s, 'entry reason block not found'
s = s.replace(old, new, 1)

old = '''    elif long_need <= 0 and short_need <= 0: entry_status = "WAITING_CAPACITY"; entry_reason = "Strategy 2 slots zijn gevuld"
    elif account_remaining_capacity <= 0:
        entry_status = "WAITING_ACCOUNT_CAP"
        entry_reason = f"account heeft {account_position_count} actieve Aster-posities; ingestelde limiet is {settings.maximum_positions}"
'''
new = '''    elif long_need <= 0 and short_need <= 0:
        entry_status = "WAITING_CAPACITY"; entry_reason = "Gekoppelde-parencapaciteit is gevuld" if settings.asymmetric_hedge_enabled else "Strategy 2 slots zijn gevuld"
    elif account_remaining_capacity < (2 if settings.asymmetric_hedge_enabled else 1):
        entry_status = "WAITING_ACCOUNT_CAP"
        entry_reason = (f"account heeft {account_position_count} actieve Aster-posities; er zijn twee vrije posities nodig voor één volledig LONG+SHORT-paar" if settings.asymmetric_hedge_enabled else f"account heeft {account_position_count} actieve Aster-posities; ingestelde limiet is {settings.maximum_positions}")
'''
assert old in s, 'account status block not found'
s = s.replace(old, new, 1)

old = '''              "asymmetricHedgeModeEnabled": settings.asymmetric_hedge_enabled, "shortStartMultiplier": settings.short_start_multiplier,
              "asymmetricHedgeActivePairs": sum(1 for key, row in state.items() if key.endswith("|LONG") and row.get("asymmetricHedge") and (row.get("pairedShortPending") or str(row.get("pairedShortKey") or "") in active)),
              "activeLong": settings.long_slots - long_need, "activeShort": settings.short_slots - short_need,
              "remainingLong": long_need, "remainingShort": short_need,
'''
new = '''              "asymmetricHedgeModeEnabled": settings.asymmetric_hedge_enabled, "shortStartMultiplier": settings.short_start_multiplier,
              "asymmetricHedgeActivePairs": active_pair_count, "remainingPairs": pair_need if settings.asymmetric_hedge_enabled else None,
              "legacyPositionsDuringAsymmetric": max(0, len(strategy_active_keys) - active_pair_count * 2) if settings.asymmetric_hedge_enabled else 0,
              "activeLong": long_count, "activeShort": short_count,
              "remainingLong": long_need, "remainingShort": short_need,
'''
assert old in s, 'report block not found'
s = s.replace(old, new, 1)

p.write_text(s)

# Add regression tests to the existing asymmetric suite.
t = Path('cloud_api/test_asymmetric_hedge_20260904.py')
ts = t.read_text()
marker = 'def test_asymmetric_entry_allocator_only_plans_same_symbol_pairs():'
assert marker in ts
extra = r'''

def test_legacy_positions_do_not_consume_new_pair_capacity():
    from test_aster_multi_bb import Client, Ref
    import time
    from aster_multi_bb import run_multi_bb_step
    positions=[]; state={}
    for i in range(7):
        symbol=f"OLDL{i}USDT"; positions.append({"symbol":symbol,"positionSide":"LONG","positionAmt":"1","entryPrice":"100","markPrice":"100","leverage":"100"})
        state[f"{symbol}|LONG"]={"dcaCount":0,"lastBotFillPrice":100,"lastKnownQty":1,"lastKnownEntry":100,"cycleStartedAtMs":1,"botManaged":True}
    for i in range(4):
        symbol=f"OLDS{i}USDT"; positions.append({"symbol":symbol,"positionSide":"SHORT","positionAmt":"-1","entryPrice":"100","markPrice":"100","leverage":"100"})
        state[f"{symbol}|SHORT"]={"dcaCount":0,"lastBotFillPrice":100,"lastKnownQty":1,"lastKnownEntry":100,"cycleStartedAtMs":1,"botManaged":True}
    tickers=[{"symbol":"NEWUSDT","quoteVolume":"999999"}]
    prices={"NEWUSDT":100, **{p["symbol"]:100 for p in positions}}
    c=Client(positions=positions,tickers=tickers,prices=prices,leverage=100)
    settings=cfg(maximumPositions=14,longSlots=7,shortSlots=7,universeTopN=50,entryMarginUsd=.1,shortStartMultiplier=5)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={"multiBbPositions":state},settings=settings,uid="u",account={"availableBalance":"100"},positions=positions,open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    entries=[x for x in r["actions"] if x["kind"] in {"ENTRY","ASYM_SHORT_ENTRY"}]
    assert {(x["symbol"],x["side"]) for x in entries} == {("NEWUSDT","LONG"),("NEWUSDT","SHORT")}
    assert r["asymmetricHedgeActivePairs"] == 1
    assert r["remainingPairs"] == 6
    assert r["legacyPositionsDuringAsymmetric"] == 11


def test_existing_asymmetric_pairs_do_consume_pair_capacity():
    from test_aster_multi_bb import Client, Ref
    import time
    from aster_multi_bb import run_multi_bb_step
    long={"symbol":"PAIRUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100","markPrice":"100","leverage":"100"}
    short={"symbol":"PAIRUSDT","positionSide":"SHORT","positionAmt":"-5","entryPrice":"100","markPrice":"100","leverage":"100"}
    state={"PAIRUSDT|LONG":{"asymmetricHedge":True,"pairedShortKey":"PAIRUSDT|SHORT","pairedShortPending":False,"botManaged":True,"dcaCount":0,"lastBotFillPrice":100},"PAIRUSDT|SHORT":{"asymmetricHedge":True,"pairedLongKey":"PAIRUSDT|LONG","botManaged":True,"dcaCount":0,"lastBotFillPrice":100}}
    c=Client(positions=[long,short],tickers=[{"symbol":"NEWUSDT","quoteVolume":"1000"}],prices={"PAIRUSDT":100,"NEWUSDT":100},leverage=100)
    settings=cfg(maximumPositions=2,longSlots=1,shortSlots=1,universeTopN=50,entryMarginUsd=.1)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={"multiBbPositions":state},settings=settings,uid="u",account={"availableBalance":"100"},positions=[long,short],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert r["asymmetricHedgeActivePairs"] == 1 and r["remainingPairs"] == 0
    assert not any(x["kind"]=="ENTRY" for x in r["actions"])
'''
if 'test_legacy_positions_do_not_consume_new_pair_capacity' not in ts:
    ts += extra
    t.write_text(ts)
