import random
from pathlib import Path

from aster_strategy2_focus_trailing import (
    next_dca_from_anchor, release_price_from_last_dca, hedge_release_crossed, portfolio_target_reached
)
from aster_strategy2 import Strategy2Config


def _settings(mode='usdt', value=10.0):
    return Strategy2Config(
        trading_mode='focus', focus_v2_enabled=True, focus_v2_simple_mode_enabled=True,
        focus_v2_take_profit_mode=mode, focus_v2_take_profit_value=value,
    )


def test_portfolio_target_is_equity_based_not_position_pnl():
    s = _settings('usdt', 10.0)
    assert not portfolio_target_reached(s, 109.99, 100.0)
    assert portfolio_target_reached(s, 110.0, 100.0)
    p = _settings('percent', 0.10)
    assert not portfolio_target_reached(p, 109.99, 100.0)
    assert portfolio_target_reached(p, 110.0, 100.0)


def test_release_price_is_exactly_from_last_filled_buy():
    last = 100.0
    release = release_price_from_last_dca(last, 'LONG', 0.0015)
    assert abs(release - 100.15) < 1e-9
    assert not hedge_release_crossed(100.149999, release, 'LONG')
    assert hedge_release_crossed(100.15, release, 'LONG')


def test_10000_randomized_trailing_paths_never_put_next_buy_above_high_or_farther_than_config():
    rng = random.Random(20260830)
    distance = 0.003
    for _ in range(10_000):
        price = rng.uniform(0.01, 100_000.0)
        high = price
        for _tick in range(rng.randint(5, 40)):
            price *= 1.0 + rng.uniform(-0.004, 0.006)
            high = max(high, price)
            trigger = next_dca_from_anchor(high, 'LONG', distance)
            assert trigger < high
            assert abs((high - trigger) / high - distance) < 1e-12
            if price >= trigger:
                shown = max(0.0, min(distance, (price - trigger) / price))
                assert 0.0 <= shown <= distance


def test_simple_flow_release_requires_price_net_green_and_keeps_rehedge_priority_exit():
    src = Path('aster_strategy2_focus_trailing.py').read_text(encoding='utf-8')
    section = src.split('# v7 protected SHORT release.', 1)[1].split('# Legacy non-simple Focus TP only.', 1)[0]
    assert 'price_release_ready and net_green_ready and rehedge_funding_ready:' in section
    assert 'expected_net_hedge_close_pnl(' in section
    assert 'expected_net_close_pnl > 0.0' in section
    assert 'reHedgeArmed' in section
    assert 'FOCUS_HEDGE_RELEASED_NET_GREEN' in section
    priority = src.index('target_now = bool(simple_flow')
    dca = src.index('# Hard invariant: a confirmed LONG DCA')
    assert priority < dca


def test_equity_protection_keeps_dca_active_and_does_not_backfill_missed_orders():
    src = Path('aster_strategy2_focus_trailing.py').read_text(encoding='utf-8')
    section = src.split('# v7 equity protection may repair missing protection below the cycle baseline, but', 1)[1].split('# v7 post-release re-hedge:', 1)[0]
    assert 'normal trailing\n    # DCA remains active' in section
    assert 'Intentionally continue into normal DCA evaluation below.' in section
    assert 'equityDcaRearmedAfterLock' in section
    assert 'Do NOT backfill missed historical DCA orders' in section
    assert 'next_dca_from_anchor(mark, primary_side, dca_ratio)' in section
    assert 'dcaTriggerPending": False' in section  # only one-time legacy re-arm, not steady-state hold
    release = src.split('# v7 protected SHORT release.', 1)[1].split('# Legacy non-simple Focus TP only.', 1)[0]
    assert 'equity_release_ready' not in release
    assert 'price_release_ready and net_green_ready and rehedge_funding_ready:' in release
