from pathlib import Path

path = Path('cloud_api/aster_strategy2_focus_trailing.py')
text = path.read_text()
old = '''        equity_release_ready = cycle_start_equity <= 0 or current_equity + 1e-9 >= cycle_start_equity\n        state["shortReleasePriceReady"] = bool(price_release_ready)\n'''
new = '''        state["shortReleasePriceReady"] = bool(price_release_ready)\n'''
if old not in text:
    raise SystemExit('equity release gate assignment not found')
text = text.replace(old, new, 1)
old2 = '''        if price_release_ready and net_green_ready and equity_release_ready:\n'''
new2 = '''        if price_release_ready and net_green_ready:\n'''
if old2 not in text:
    raise SystemExit('equity release gate condition not found')
text = text.replace(old2, new2, 1)
old3 = '''    # v7 equity protection: below the persisted cycle baseline, never reduce protection.\n    # SHORT release is blocked separately by equity_release_ready, but normal trailing\n'''
new3 = '''    # v7 equity protection may repair missing protection below the cycle baseline, but\n    # it must not block a valid hedge release; normal trailing\n'''
if old3 in text:
    text = text.replace(old3, new3, 1)
path.write_text(text)
print('Removed cycleStartEquity gate from hedge release; release now requires price + net-green only.')
