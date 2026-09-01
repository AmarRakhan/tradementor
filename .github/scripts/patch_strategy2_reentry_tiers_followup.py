from pathlib import Path

# This script only updates validation expectations after the implementation patch
# has been applied in CI. It does not alter production bot code.

p = Path('cloud_api/test_aster_multi_bb.py')
text = p.read_text(encoding='utf-8')
marker = 'minimumLeverage=20,maximumPositions=1,longSlots=0,shortSlots=1'
pos = text.find(marker)
if pos >= 0:
    start = text.rfind('\ndef ', 0, pos)
    if start < 0 and text.startswith('def '):
        start = 0
    elif start >= 0:
        start += 1
    next_def = text.find('\ndef ', pos)
    next_mark = text.find('\n@pytest', pos)
    ends = [x for x in (next_def, next_mark) if x >= 0]
    end = min(ends) if ends else len(text)
    replacement = '''def test_manual_selection_exchange_max_overrides_configured_minimum_without_stopping():
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"1"}],prices={"AAAUSDT":100},leverage=10)
    settings=manual_cfg([{"symbol":"AAAUSDT","side":"SHORT"}],minimumLeverage=20,maximumPositions=1,longSlots=0,shortSlots=1)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=settings,uid="u",account={"availableBalance":"100"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    entry=next(x for x in r["actions"] if x["kind"]=="ENTRY")
    assert entry["leverage"]==10
    assert entry["forcedBelowConfiguredMinimum"] is True
    assert r["entryStatus"]=="ENTRY_PLANNED"

'''
    text = text[:start] + replacement + text[end+1:]
    p.write_text(text, encoding='utf-8')
else:
    print('legacy minimum-leverage test marker already absent; nothing to replace')

p = Path('cloud_api/test_strategy2_reentry_leverage_tiers.py')
text = p.read_text(encoding='utf-8')
old = 'resolve_dca(HYPE,"HYPEUSDT",current_notional=notional,current_leverage=leverage,dca_margin_usd=100,configured_minimum=300)'
new = 'resolve_dca(HYPE,"HYPEUSDT",current_notional=notional,current_leverage=leverage,dca_margin_usd=1,configured_minimum=300)'
if old in text:
    text = text.replace(old, new, 1)
p.write_text(text, encoding='utf-8')

print('Strategy 2 validation expectations updated')
