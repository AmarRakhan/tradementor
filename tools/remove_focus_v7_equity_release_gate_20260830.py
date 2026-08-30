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

test_path = Path('cloud_api/test_aster_strategy2_focus_trailing.py')
test = test_path.read_text()
old_test = '''def test_v7_short_release_requires_price_plus_net_green_plus_equity():\n    from pathlib import Path\n    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()\n    gate = src.index('price_release_ready = last_dca > 0 and hedge_release_crossed')\n    protected = src.index('if price_release_ready and net_green_ready and equity_release_ready:', gate)\n    end = src.index('# Legacy non-simple Focus TP only.', protected)\n    section = src[gate:end]\n    assert protected > gate\n    assert 'expected_net_hedge_close_pnl' in section\n    assert 'net_green_ready' in section\n    assert 'equity_release_ready' in section\n    assert 'FOCUS_HEDGE_RELEASED_NET_GREEN' in section\n'''
new_test = '''def test_v7_short_release_requires_price_plus_net_green_only():\n    from pathlib import Path\n    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()\n    gate = src.index('price_release_ready = last_dca > 0 and hedge_release_crossed')\n    protected = src.index('if price_release_ready and net_green_ready:', gate)\n    end = src.index('# Legacy non-simple Focus TP only.', protected)\n    section = src[gate:end]\n    assert protected > gate\n    assert 'expected_net_hedge_close_pnl' in section\n    assert 'net_green_ready' in section\n    assert 'equity_release_ready' not in section\n    assert 'FOCUS_HEDGE_RELEASED_NET_GREEN' in section\n'''
if old_test not in test:
    raise SystemExit('stale equity-gate test not found')
test_path.write_text(test.replace(old_test, new_test, 1))
print('Removed cycleStartEquity gate from hedge release and migrated regression test.')
