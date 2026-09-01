from pathlib import Path

# This script only updates validation expectations after the implementation patch
# has been applied in CI. It does not alter production bot code.

p = Path('cloud_api/test_aster_multi_bb.py')
text = p.read_text(encoding='utf-8')
name = 'def test_manual_selection_keeps_minimum_leverage_guard():'
start = text.find(name)
if start < 0:
    raise SystemExit('minimum-leverage test not found')
next_def = text.find('\ndef ', start + len(name))
next_mark = text.find('\n@pytest', start + len(name))
ends = [x for x in (next_def, next_mark) if x >= 0]
end = min(ends) if ends else len(text)
replacement = '''def test_manual_selection_exchange_max_overrides_configured_minimum_without_stopping():
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"1"}],prices={"AAAUSDT":100},leverage=10)
    settings=manual_cfg([{"symbol":"AAAUSDT","side":"SHORT"}],minimumLeverage=20,maximumPositions=1,longSlots=0,shortSlots=1)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=settings,uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    entry=next(x for x in r["actions"] if x["kind"]=="ENTRY")
    assert entry["leverage"]==10
    assert entry["exchangeTierForced"] is True
    assert r["entryStatus"]=="ENTRY_PLANNED"

'''
p.write_text(text[:start] + replacement + text[end+1:], encoding='utf-8')

p = Path('cloud_api/test_strategy2_reentry_leverage_tiers.py')
text = p.read_text(encoding='utf-8')
old = 'resolve_dca(HYPE,"HYPEUSDT",current_notional=notional,current_leverage=leverage,dca_margin_usd=100,configured_minimum=300)'
new = 'resolve_dca(HYPE,"HYPEUSDT",current_notional=notional,current_leverage=leverage,dca_margin_usd=1,configured_minimum=300)'
if old not in text:
    raise SystemExit('multi-tier validation marker not found')
p.write_text(text.replace(old, new, 1), encoding='utf-8')

print('Strategy 2 validation expectations updated')
