from pathlib import Path

path = Path('cloud_api/aster_strategy2_focus_trailing.py')
src = path.read_text(encoding='utf-8')

src = src.replace(
    '- the full hedge is mechanically released at the configured recovery from the last confirmed buy fill;',
    '- the full hedge may release only after the configured recovery AND when the exact hedge close is net profitable after conservative round-trip fees/slippage;'
)

old = '''    # v7 mechanical SHORT release. No green-PnL, break-even or protection-reserve gate.\n    # The configured +recovery from the last confirmed buy fill is the sole release trigger.\n    if hedge_qty > 1e-12:\n        last_dca = _finite(state.get("lastDcaFillPrice"))\n        release_price = _finite(state.get("hedgeReleasePrice")) or (release_price_from_last_dca(last_dca, primary_side, release_ratio) if last_dca > 0 else 0.0)\n        state["hedgeReleasePrice"] = release_price\n        price_release_ready = last_dca > 0 and hedge_release_crossed(mark, release_price, primary_side)\n        state["shortReleasePriceReady"] = bool(price_release_ready)\n        state["shortReleaseNetGreenReady"] = False\n        state["expectedNetShortClosePnl"] = 0.0\n        state["shortNetGreenReleasePrice"] = 0.0\n        if price_release_ready:\n'''
new = '''    # v7 protected SHORT release. The configured recovery is only the earliest point\n    # at which a release may be considered. The exact hedge being reduced/closed must\n    # also be net profitable after the existing conservative round-trip fee/slippage\n    # model, and account equity may not be below the persisted cycle baseline.\n    # This makes a red hedge close server-side impossible in simple portfolio-cycle mode.\n    if hedge_qty > 1e-12:\n        last_dca = _finite(state.get("lastDcaFillPrice"))\n        release_price = _finite(state.get("hedgeReleasePrice")) or (release_price_from_last_dca(last_dca, primary_side, release_ratio) if last_dca > 0 else 0.0)\n        state["hedgeReleasePrice"] = release_price\n        price_release_ready = last_dca > 0 and hedge_release_crossed(mark, release_price, primary_side)\n        expected_net_close_pnl, executable_close_price, gross_close_pnl, estimated_close_fees, estimated_slippage = expected_net_hedge_close_pnl(\n            client, symbol, hedge_side, hedge_row, mark\n        )\n        net_green_ready = expected_net_close_pnl > 0.0\n        equity_release_ready = cycle_start_equity <= 0 or current_equity + 1e-9 >= cycle_start_equity\n        state["shortReleasePriceReady"] = bool(price_release_ready)\n        state["shortReleaseNetGreenReady"] = bool(net_green_ready)\n        state["expectedNetShortClosePnl"] = expected_net_close_pnl\n        state["shortNetGreenReleasePrice"] = net_green_hedge_release_price(hedge_row, hedge_side)\n        if price_release_ready and net_green_ready and equity_release_ready:\n'''
assert old in src, 'mechanical release anchor not found'
src = src.replace(old, new, 1)

src = src.replace(
    '"lastReason": "mechanische reduce-only release verzonden; Aster bevestigt nog resterende SHORT",',
    '"lastReason": "net-groene reduce-only release verzonden; Aster bevestigt nog resterende SHORT",',
    1,
)
src = src.replace(
    '"lastAction": "HEDGE_RELEASED_MECHANICAL",\n                "lastReason": "release-afstand geraakt; volledige SHORT gesloten en re-hedge op laatste gevulde terugvalkoop gewapend",',
    '"lastAction": "HEDGE_RELEASED_NET_GREEN",\n                "lastReason": "release-afstand geraakt en SHORT netto groen na kostenbuffer; volledige SHORT gesloten en re-hedge gewapend",',
    1,
)
src = src.replace(
    '_audit(ref, "FOCUS_HEDGE_RELEASED_MECHANICAL", cycleId=state["cycleId"], symbol=symbol,\n                lastDcaFill=last_dca, releasePrice=release_price, closeQty=cq, closePrice=cp, reHedgePrice=state.get("reHedgePrice"))',
    '_audit(ref, "FOCUS_HEDGE_RELEASED_NET_GREEN", cycleId=state["cycleId"], symbol=symbol,\n                lastDcaFill=last_dca, releasePrice=release_price, closeQty=cq, closePrice=cp,\n                executableClosePrice=executable_close_price, grossClosePnl=gross_close_pnl, estimatedCloseFees=estimated_close_fees,\n                estimatedSlippage=estimated_slippage, expectedNetShortClosePnl=expected_net_close_pnl, reHedgePrice=state.get("reHedgePrice"))',
    1,
)
src = src.replace(
    '"status": "executed", "action": "FOCUS_HEDGE_RELEASED_MECHANICAL", "symbol": symbol,',
    '"status": "executed", "action": "FOCUS_HEDGE_RELEASED_NET_GREEN", "symbol": symbol,',
    1,
)
src = src.replace(
    '"cycleStatus": "HEDGED", "lastAction": "HEDGE_HOLD_UNTIL_RELEASE_PRICE",\n                "lastReason": "mechanische releaseprijs vanaf laatste gevulde terugvalkoop nog niet geraakt",',
    '"cycleStatus": "HEDGED", "lastAction": "HEDGE_HOLD_PROTECTED_RELEASE",\n                "lastReason": ("releaseprijs nog niet geraakt" if not price_release_ready else\n                    ("SHORT nog niet netto groen na kostenbuffer" if not net_green_ready else\n                     "equity onder cycleStartEquity; hedge mag niet worden verlaagd")),',
    1,
)
path.write_text(src, encoding='utf-8')

# Migrate stale tests that intentionally encoded the now-dangerous mechanical-only contract.
p = Path('cloud_api/test_focus_v7_emergency_equity_lock.py')
t = p.read_text(encoding='utf-8').replace('# v7 mechanical SHORT release', '# v7 protected SHORT release')
t = t.replace('FOCUS_HEDGE_RELEASED_MECHANICAL', 'FOCUS_HEDGE_RELEASED_NET_GREEN')
p.write_text(t, encoding='utf-8')

p = Path('cloud_api/test_focus_simple_deterministic_flow.py')
t = p.read_text(encoding='utf-8')
t = t.replace('def test_simple_flow_contract_is_mechanical_release_plus_full_rehedge():', 'def test_simple_flow_contract_is_protected_release_plus_full_rehedge():')
t = t.replace("source.split('# v7 mechanical SHORT release.', 1)[1]", "source.split('# v7 protected SHORT release.', 1)[1]")
t = t.replace("assert 'net_green_ready' not in release", "assert 'net_green_ready' in release")
t = t.replace("assert 'FOCUS_HEDGE_RELEASED_MECHANICAL' in release", "assert 'FOCUS_HEDGE_RELEASED_NET_GREEN' in release")
p.write_text(t, encoding='utf-8')

p = Path('cloud_api/test_aster_strategy2_focus_trailing.py')
t = p.read_text(encoding='utf-8')
t = t.replace('def test_runtime_source_contains_v7_portfolio_cycle_and_mechanical_release():', 'def test_runtime_source_contains_v7_portfolio_cycle_and_protected_release():')
t = t.replace('assert "FOCUS_HEDGE_RELEASED_MECHANICAL" in src', 'assert "FOCUS_HEDGE_RELEASED_NET_GREEN" in src', 1)
t = t.replace('def test_v7_short_release_requires_only_last_buy_plus_point15():', 'def test_v7_short_release_requires_price_plus_net_green_plus_equity():')
t = t.replace("mechanical = src.index('if price_release_ready:', gate)\n    end = src.index('# Legacy non-simple Focus TP only.', mechanical)\n    section = src[gate:end]\n    assert mechanical > gate\n    assert 'net_green_ready' not in section\n    assert 'protectionReserveReady' not in section\n    assert 'FOCUS_HEDGE_RELEASED_MECHANICAL' in section", "protected = src.index('if price_release_ready and net_green_ready and equity_release_ready:', gate)\n    end = src.index('# Legacy non-simple Focus TP only.', protected)\n    section = src[gate:end]\n    assert protected > gate\n    assert 'expected_net_hedge_close_pnl' in section\n    assert 'net_green_ready' in section\n    assert 'equity_release_ready' in section\n    assert 'FOCUS_HEDGE_RELEASED_NET_GREEN' in section")
t = t.replace('assert result["action"]=="FOCUS_HEDGE_RELEASED_MECHANICAL"', 'assert result["action"]=="FOCUS_HEDGE_RELEASED_NET_GREEN"')
p.write_text(t, encoding='utf-8')

# Focused contract tests.
test = Path('cloud_api/test_focus_v7_net_green_release.py')
test.write_text('''from pathlib import Path\n\n\ndef block():\n    src = Path("aster_strategy2_focus_trailing.py").read_text(encoding="utf-8")\n    a = src.index("# v7 protected SHORT release")\n    b = src.index("# Legacy non-simple Focus TP only")\n    return src[a:b]\n\n\ndef test_release_requires_price_net_green_and_equity():\n    s=block()\n    assert "price_release_ready and net_green_ready and equity_release_ready" in s\n    assert "expected_net_hedge_close_pnl(" in s\n    assert "expected_net_close_pnl > 0.0" in s\n\n\ndef test_red_short_cannot_reach_close_executor():\n    s=block()\n    gate=s.index("if price_release_ready and net_green_ready and equity_release_ready:")\n    close=s.index('action="CLOSE"')\n    assert gate < close\n\n\ndef test_release_block_exposes_diagnostics():\n    s=block()\n    for token in ("shortReleasePriceReady","shortReleaseNetGreenReady","expectedNetShortClosePnl","FOCUS_HEDGE_RELEASED_NET_GREEN"):\n        assert token in s\n''', encoding='utf-8')
print('patched net-green protected release and migrated stale release-contract tests')
