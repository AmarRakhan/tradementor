from datetime import datetime, timezone

import pytest

from aster_cost_evidence import cost_refresh_symbols, paged_income_history, paged_user_trades, refresh_owned_costs
from aster_strategy2_state import OwnedLeg


class ReadOnlyClient:
    def __init__(self):
        self.funding = "-.01"
        self.calls = []

    def user_trades(self, symbol, **kwargs):
        self.calls.append(("trades", symbol, kwargs))
        return [{"id":1,"symbol":symbol,"positionSide":"LONG","time":100,"commission":".02","realizedPnl":"0"}]

    def income_history(self, **kwargs):
        self.calls.append(("income", kwargs["symbol"], kwargs))
        return [{"tranId":1,"symbol":kwargs["symbol"],"positionSide":"LONG","time":101,
            "incomeType":"FUNDING_FEE","income":self.funding}]


def test_funding_refreshes_when_quantity_and_entry_are_unchanged_and_never_orders():
    client=ReadOnlyClient();leg=OwnedLeg("aster-strategy-3","strategy3","BTCUSDT","LONG","c",1,1,100,created_at_ms=100)
    first,failures=refresh_owned_costs(client,[leg],{"BTCUSDT"},checked_at_ms=1_000)
    client.funding="-.03"
    second,failures2=refresh_owned_costs(client,first,{"BTCUSDT"},checked_at_ms=2_000)
    assert not failures and not failures2
    assert first[0].funding==-.01 and second[0].funding==-.03
    assert second[0].quantity==1 and second[0].weighted_entry==100 and second[0].costs_updated_at_ms==2_000
    assert {call[0] for call in client.calls}=={"trades","income"}


def test_full_fill_and_income_pages_are_paginated():
    class Paged:
        def user_trades(self, symbol, **kwargs):
            return ([{"id":1,"symbol":symbol},{"id":2,"symbol":symbol}] if "from_id" not in kwargs
                else [{"id":3,"symbol":symbol}])
        def income_history(self, **kwargs):
            return ([{"tranId":1,"time":10},{"tranId":2,"time":11}] if kwargs.get("start_time")==1
                else [{"tranId":3,"time":12}])
    client=Paged()
    assert [row["id"] for row in paged_user_trades(client,"BTCUSDT",start_time=1,page_size=2)]==[1,2,3]
    assert [row["tranId"] for row in paged_income_history(client,symbol="BTCUSDT",start_time=1,page_size=2)]==[1,2,3]


def test_full_page_without_cursor_fails_closed():
    class Broken:
        def user_trades(self, symbol, **kwargs):return [{"symbol":symbol},{"symbol":symbol}]
    with pytest.raises(ValueError,match="vervolgcursor"):
        paged_user_trades(Broken(),"BTCUSDT",page_size=2)


def test_profitable_and_changed_positions_precede_background_refresh():
    owned=[OwnedLeg("s3","strategy3","WINUSDT","LONG","w",1,1,100,costs_updated_at_ms=9),
        OwnedLeg("s3","strategy3","CHANGEDUSDT","LONG","c",1,1,100,costs_updated_at_ms=8),
        OwnedLeg("s3","strategy3","OLDUSDT","LONG","o",1,1,100,costs_updated_at_ms=1)]
    positions=[{"symbol":"WINUSDT","positionSide":"LONG","quantity":1,"entryPrice":100,"unrealizedPnl":1},
        {"symbol":"CHANGEDUSDT","positionSide":"LONG","quantity":2,"entryPrice":100,"unrealizedPnl":-1},
        {"symbol":"OLDUSDT","positionSide":"LONG","quantity":1,"entryPrice":100,"unrealizedPnl":-1}]
    selected=cost_refresh_symbols(owned,positions,maximum_background=1)
    assert set(selected)=={"WINUSDT","CHANGEDUSDT","OLDUSDT"}


def test_strategy3_ownership_recovers_only_from_explicit_s3_audit_and_fill():
    from aster_strategy2_runtime import recover_audited_ownership
    stamp=datetime(2026,8,14,12,tzinfo=timezone.utc)
    positions=[{"symbol":"CCUSDT","positionSide":"LONG","positionAmt":"2","entryPrice":"5"}]
    audit=[{"event":"INITIAL_OPEN_LEG","strategyId":"aster-strategy-3","symbol":"CCUSDT","side":"LONG","cycleId":"s3c","timestamp":stamp}]
    fills=[{"id":1,"symbol":"CCUSDT","positionSide":"LONG","time":int(stamp.timestamp()*1000)}]
    owned,recovered=recover_audited_ownership(persisted=[],positions=positions,audit_events=audit,fills=fills,
        strategy_id="aster-strategy-3",engine_type="strategy3",require_event_strategy=True)
    assert recovered and owned[0].strategy_id=="aster-strategy-3" and owned[0].engine_type=="strategy3"
