from pathlib import Path

path = Path('cloud_api/aster_strategy2_focus_trailing.py')
src = path.read_text(encoding='utf-8')

src = src.replace(
    '- the full hedge is mechanically released at the configured recovery from the last confirmed buy fill;',
    '- the full hedge may release only after the configured recovery AND when the exact hedge close is net profitable after a conservative fee/slippage buffer;'
)

old = '''    # v7 mechanical SHORT release. No green-PnL, break-even or protection-reserve gate.\n    # The configured +recovery from the last confirmed buy fill is the sole release trigger.\n    if hedge_qty > 1e-12:\n        last_dca = _finite(state.get("lastDcaFillPrice"))\n        release_price = _finite(state.get("hedgeReleasePrice")) or (release_price_from_last_dca(last_dca, primary_side, release_ratio) if last_dca > 0 else 0.0)\n        state["hedgeReleasePrice"] = release_price\n        price_release_ready = last_dca > 0 and hedge_release_crossed(mark, release_price, primary_side)\n        state["shortReleasePriceReady"] = bool(price_release_ready)\n        state["shortReleaseNetGreenReady"] = False\n        state["expectedNetShortClosePnl"] = 0.0\n        state["shortNetGreenReleasePrice"] = 0.0\n        if price_release_ready:\n'''
new = '''    # v7 protected SHORT release. The configured recovery is only the earliest point\n    # at which a release may be considered. The exact hedge being reduced/closed must\n    # also be net profitable after a conservative taker-fee + slippage buffer, and\n    # account equity may not be below the persisted cycle baseline. This makes a red\n    # hedge close server-side impossible in the simple portfolio-cycle flow.\n    if hedge_qty > 1e-12:\n        last_dca = _finite(state.get("lastDcaFillPrice"))\n        release_price = _finite(state.get("hedgeReleasePrice")) or (release_price_from_last_dca(last_dca, primary_side, release_ratio) if last_dca > 0 else 0.0)\n        state["hedgeReleasePrice"] = release_price\n        price_release_ready = last_dca > 0 and hedge_release_crossed(mark, release_price, primary_side)\n        hedge_unrealized_pnl = _finite((hedge_row or {}).get("unRealizedProfit"), _finite((hedge_row or {}).get("unrealizedProfit"), hedge_pnl))\n        exact_close_notional = hedge_qty * mark\n        # 7 bps is deliberately conservative: it covers a taker close plus a\n        # small execution/slippage reserve. A close is allowed only if profit remains.\n        close_cost_buffer = exact_close_notional * 0.0007\n        expected_net_close_pnl = hedge_unrealized_pnl - close_cost_buffer\n        net_green_ready = expected_net_close_pnl > 0.0\n        equity_release_ready = cycle_start_equity <= 0 or current_equity + 1e-9 >= cycle_start_equity\n        state["shortReleasePriceReady"] = bool(price_release_ready)\n        state["shortReleaseNetGreenReady"] = bool(net_green_ready)\n        state["expectedNetShortClosePnl"] = expected_net_close_pnl\n        state["shortNetGreenReleasePrice"] = mark if net_green_ready else 0.0\n        if price_release_ready and net_green_ready and equity_release_ready:\n'''
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
    '_audit(ref, "FOCUS_HEDGE_RELEASED_NET_GREEN", cycleId=state["cycleId"], symbol=symbol,\n                lastDcaFill=last_dca, releasePrice=release_price, closeQty=cq, closePrice=cp,\n                expectedNetShortClosePnl=expected_net_close_pnl, reHedgePrice=state.get("reHedgePrice"))',
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

test = Path('cloud_api/test_focus_v7_net_green_release.py')
test.write_text('''from pathlib import Path\n\n\ndef block():\n    src = Path("aster_strategy2_focus_trailing.py").read_text(encoding="utf-8")\n    a = src.index("# v7 protected SHORT release")\n    b = src.index("# Legacy non-simple Focus TP only")\n    return src[a:b]\n\n\ndef test_release_requires_price_net_green_and_equity():\n    s=block()\n    assert "price_release_ready and net_green_ready and equity_release_ready" in s\n    assert "expected_net_close_pnl = hedge_unrealized_pnl - close_cost_buffer" in s\n    assert "close_cost_buffer = exact_close_notional * 0.0007" in s\n\n\ndef test_red_short_cannot_reach_close_executor():\n    s=block()\n    gate=s.index("if price_release_ready and net_green_ready and equity_release_ready:")\n    close=s.index('action="CLOSE"')\n    assert gate < close\n\n\ndef test_release_block_exposes_diagnostics():\n    s=block()\n    for token in ("shortReleasePriceReady","shortReleaseNetGreenReady","expectedNetShortClosePnl","FOCUS_HEDGE_RELEASED_NET_GREEN"):\n        assert token in s\n''', encoding='utf-8')
print('patched net-green protected release')
