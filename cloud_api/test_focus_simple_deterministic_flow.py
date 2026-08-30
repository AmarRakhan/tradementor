from pathlib import Path

import aster_strategy2_focus_trailing as focus


class BookClient:
    def __init__(self, bid='99.8', ask='100.2'):
        self.bid = bid
        self.ask = ask

    def _public_get(self, *args, **kwargs):
        return {'bidPrice': self.bid, 'askPrice': self.ask}


def test_long_dca_cross_is_downward():
    assert focus.dca_crossed(99.0, 100.0, 'LONG') is True
    assert focus.dca_crossed(101.0, 100.0, 'LONG') is False


def test_short_red_is_not_net_green_after_costs():
    row = {'positionAmt': '-10', 'entryPrice': '100'}
    net, close, gross, fees, slippage = focus.expected_net_hedge_close_pnl(BookClient(ask='100.2'), 'X', 'SHORT', row, 100.2)
    assert close == 100.2
    assert gross < 0
    assert net < 0
    assert fees > 0
    assert slippage > 0


def test_short_must_be_meaningfully_green_after_round_trip_costs():
    row = {'positionAmt': '-10', 'entryPrice': '100'}
    net, close, gross, fees, slippage = focus.expected_net_hedge_close_pnl(BookClient(ask='99.0'), 'X', 'SHORT', row, 99.0)
    assert gross > 0
    assert net > 0


def test_simple_flow_contract_has_no_fixed_release_gate():
    source = Path(focus.__file__).read_text(encoding='utf-8')
    assert 'release_allowed = expected_net > 0.0 if simple_flow' in source
    assert 'cycleStatus": "DCA_HEDGE_SYNC_PENDING"' in source
    assert 'target_qty_after = fresh_primary_qty * configured_hedge_ratio' in source
    assert 'fresh_hedge_qty' in source
    assert 'FOCUS_DCA_BLOCKED' in source
    assert 'FOCUS_HEDGE_RELEASED_NET_GREEN' in source


def test_start_and_dca_require_post_fill_exchange_truth():
    source = Path(focus.__file__).read_text(encoding='utf-8')
    assert 'START_HEDGE_SYNC_PENDING' in source
    assert 'confirmed_positions = client.position_risk(symbol)' in source
    assert 'post_sync_positions = client.position_risk(symbol)' in source
    assert 'abs(post_primary_qty - post_hedge_qty) > post_tolerance' in source
