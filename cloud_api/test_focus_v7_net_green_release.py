from pathlib import Path


def block():
    src = Path("aster_strategy2_focus_trailing.py").read_text(encoding="utf-8")
    a = src.index("# v7 protected SHORT release")
    b = src.index("# Legacy non-simple Focus TP only")
    return src[a:b]


def test_release_requires_price_net_green_and_equity():
    s=block()
    assert "price_release_ready and net_green_ready and equity_release_ready" in s
    assert "expected_net_hedge_close_pnl(" in s
    assert "expected_net_close_pnl > 0.0" in s


def test_red_short_cannot_reach_close_executor():
    s=block()
    gate=s.index("if price_release_ready and net_green_ready and equity_release_ready:")
    close=s.index('action="CLOSE"')
    assert gate < close


def test_release_block_exposes_diagnostics():
    s=block()
    for token in ("shortReleasePriceReady","shortReleaseNetGreenReady","expectedNetShortClosePnl","FOCUS_HEDGE_RELEASED_NET_GREEN"):
        assert token in s
