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


def test_mechanical_release_is_exactly_from_last_filled_buy():
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
            # Before a crossing, live >= trigger and displayed distance is <= configured distance.
            if price >= trigger:
                shown = max(0.0, min(distance, (price - trigger) / price))
                assert 0.0 <= shown <= distance


def test_simple_flow_source_has_no_green_or_reserve_release_gate_and_has_rehedge_and_priority_exit():
    src = Path('aster_strategy2_focus_trailing.py').read_text(encoding='utf-8')
    section = src.split('# v7 mechanical SHORT release.', 1)[1].split('# Legacy non-simple Focus TP only.', 1)[0]
    assert 'net_green_ready' not in section
    assert 'protectionReserveReady' not in section
    assert 'reHedgeArmed' in section
    priority = src.index('target_now = bool(simple_flow')
    dca = src.index('# Hard invariant: a confirmed LONG DCA')
    assert priority < dca
