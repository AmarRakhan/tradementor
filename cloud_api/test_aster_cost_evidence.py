from datetime import datetime, timezone

import pytest

from aster_cost_evidence import bounded_history_symbols, cost_refresh_symbols, paged_income_history, paged_user_trades, refresh_owned_costs
from aster_strategy2_state import OwnedLeg
from aster_strategy2_runtime import cost_evidence_max_age_seconds


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


def test_profitable_positions_cannot_bypass_real_aster_request_budget():
    owned=[OwnedLeg("s3","strategy3",f"S{i:02d}USDT","LONG",str(i),1,1,100,
        costs_updated_at_ms=i) for i in range(20)]
    positions=[{"symbol":leg.symbol,"positionSide":"LONG","quantity":1,"entryPrice":100,
        "unrealizedPnl":1} for leg in owned]
    selected=cost_refresh_symbols(owned,positions,maximum_background=4,maximum_total=6)
    assert selected==[f"S{i:02d}USDT" for i in range(6)]


def test_dashboard_history_scan_is_bounded_and_rotates_background_symbols():
    background=[f"S{i:02d}USDT" for i in range(30)]
    first=bounded_history_symbols(["EXITUSDT"],background,maximum_symbols=8,rotation_slot=0)
    second=bounded_history_symbols(["EXITUSDT"],background,maximum_symbols=8,rotation_slot=1)
    assert len(first)==len(second)==8
    assert first[0]==second[0]=="EXITUSDT"
    assert set(first[1:]).isdisjoint(set(second[1:]))


def test_dashboard_history_scan_keeps_newest_priority_and_rotates_priority_backlog():
    priority=[f"P{i:02d}USDT" for i in range(20)]
    first=bounded_history_symbols(priority,[],maximum_symbols=8,rotation_slot=0)
    second=bounded_history_symbols(priority,[],maximum_symbols=8,rotation_slot=1)
    assert first[:4] == second[:4] == priority[:4]
    assert first[4:] == priority[4:8]
    assert second[4:] == priority[8:12]


def test_strategy3_ownership_recovers_only_from_explicit_s3_audit_and_fill():
    from aster_strategy2_runtime import recover_audited_ownership
    stamp=datetime(2026,8,14,12,tzinfo=timezone.utc)
    positions=[{"symbol":"CCUSDT","positionSide":"LONG","positionAmt":"2","entryPrice":"5"}]
    audit=[{"event":"INITIAL_OPEN_LEG","strategyId":"aster-strategy-3","symbol":"CCUSDT","side":"LONG","cycleId":"s3c","timestamp":stamp}]
    fills=[{"id":1,"symbol":"CCUSDT","positionSide":"LONG","time":int(stamp.timestamp()*1000)}]
    owned,recovered=recover_audited_ownership(persisted=[],positions=positions,audit_events=audit,fills=fills,
        strategy_id="aster-strategy-3",engine_type="strategy3",require_event_strategy=True)
    assert recovered and owned[0].strategy_id=="aster-strategy-3" and owned[0].engine_type=="strategy3"


def _scaled_legs(symbol_count):
    result=[]
    for index in range(symbol_count):
        symbol=f"S{index:02d}USDT"
        result.append(OwnedLeg("aster-strategy-2","strategy2",symbol,"LONG",f"l{index}",1,1,100,
            costs_updated_at_ms=0))
        result.append(OwnedLeg("aster-strategy-2","strategy2",symbol,"SHORT",f"s{index}",1,1,100,
            costs_updated_at_ms=0))
    return result


@pytest.mark.parametrize(("leg_count","symbol_count"),[(68,34),(100,50)])
def test_cost_rotation_scales_without_structural_five_minute_data_hold(leg_count,symbol_count):
    owned=_scaled_legs(symbol_count)
    assert len(owned)==leg_count
    positions=[{"symbol":leg.symbol,"positionSide":leg.side,"quantity":1,"entryPrice":100,
        "unrealizedPnl":-1} for leg in owned]
    minute_ms=60_000
    for minute in range((symbol_count+5)//6):
        selected=set(cost_refresh_symbols(owned,positions,maximum_background=4,maximum_total=6))
        checked_at=(minute+1)*minute_ms
        owned=[OwnedLeg(**{**leg.__dict__,"costs_updated_at_ms":checked_at}) if leg.symbol in selected else leg
            for leg in owned]
    now_ms=((symbol_count+5)//6+2)*minute_ms
    limit_ms=cost_evidence_max_age_seconds(owned)*1000
    assert all(leg.costs_updated_at_ms>0 and now_ms-leg.costs_updated_at_ms<=limit_ms for leg in owned)
    assert limit_ms>300_000


def test_migrated_leg_falls_back_to_full_history_without_importing_old_cycle_costs():
    class Migrated:
        def __init__(self):self.calls=[]
        def user_trades(self,symbol,**kwargs):
            self.calls.append(("trades",kwargs))
            if kwargs.get("start_time") is not None:return []
            return [{"id":7,"symbol":symbol,"positionSide":"LONG","time":100,
                "commission":".25","realizedPnl":"9"}]
        def income_history(self,**kwargs):
            self.calls.append(("income",kwargs))
            return []
    client=Migrated()
    leg=OwnedLeg("aster-strategy-2","strategy2","BRKBUSDT","LONG","migrated",1,1,50,
        fees=.04,funding=-.01,created_at_ms=1_000)
    refreshed,failures=refresh_owned_costs(client,[leg],{"BRKBUSDT"},checked_at_ms=2_000)
    assert not failures
    assert refreshed[0].costs_updated_at_ms==2_000
    assert refreshed[0].fees==.04 and refreshed[0].funding==-.01
    assert [call[0] for call in client.calls].count("trades")==2
    assert client.calls[-1][1]["start_time"]==1_000

def test_fill_evidence_recovery_is_explicitly_opt_in_and_quantity_proven():
    class History:
        def user_trades(self,symbol,**kwargs):
            return [{"id":"open","symbol":symbol,"positionSide":"LONG","side":"BUY",
                "qty":"2","price":"50","time":100}]
        def income_history(self,**kwargs):return []
    leg=OwnedLeg("aster-strategy-2","strategy2","BTCUSDT","LONG","cycle",1,2,50)
    unchanged,failures=refresh_owned_costs(History(),[leg],{"BTCUSDT"},checked_at_ms=1_000)
    recovered,failures2=refresh_owned_costs(History(),[leg],{"BTCUSDT"},checked_at_ms=1_000,
        recover_fill_ids=True)
    assert not failures and not failures2
    assert unchanged[0].fill_ids==()
    assert recovered[0].fill_ids==("open",)

def test_fill_evidence_recovery_preserves_guard_when_history_does_not_match_quantity():
    class Incomplete:
        def user_trades(self,symbol,**kwargs):
            return [{"id":"partial","symbol":symbol,"positionSide":"LONG","side":"BUY",
                "qty":"1","price":"50","time":100}]
        def income_history(self,**kwargs):return []
    leg=OwnedLeg("aster-strategy-2","strategy2","BTCUSDT","LONG","cycle",1,2,50)
    recovered,failures=refresh_owned_costs(Incomplete(),[leg],{"BTCUSDT"},checked_at_ms=1_000,
        recover_fill_ids=True)
    assert not failures
    assert recovered[0].fill_ids==()

def test_fill_recovery_reads_complete_history_after_ownership_transfer():
    class Transferred:
        def __init__(self):self.trade_calls=[]
        def user_trades(self,symbol,**kwargs):
            self.trade_calls.append(kwargs)
            return [
                {"id":"open","symbol":symbol,"positionSide":"LONG","side":"BUY",
                    "qty":"1","price":"50","time":100},
                {"id":"dca","symbol":symbol,"positionSide":"LONG","side":"BUY",
                    "qty":"1","price":"40","time":200},
            ]
        def income_history(self,**kwargs):return []
    client=Transferred()
    leg=OwnedLeg("aster-strategy-2","strategy2","BTCUSDT","LONG","transferred",1,2,45,
        created_at_ms=150)
    recovered,failures=refresh_owned_costs(client,[leg],{"BTCUSDT"},checked_at_ms=1_000,
        recover_fill_ids=True)
    assert not failures and recovered[0].fill_ids==("open","dca")
    assert client.trade_calls==[{"start_time":None,"limit":1000}]
