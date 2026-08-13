from aster_strategy2_state import *
import pytest

def owned(q=1,e=100):return OwnedLeg("s2","strategy2","BTCUSDT","LONG","c1",2,q,e)

def test_partial_fills_use_actual_quantity_and_are_idempotent():
    leg=owned(0,0);fill=Fill("f1","i1",.25,100,1)
    first=apply_confirmed_fill(leg,fill,is_dca=False);second=apply_confirmed_fill(first,fill,is_dca=False)
    assert first.quantity==.25 and first.weighted_entry==100 and second==first

def test_recovery_blocks_unowned_exchange_position():
    r=reconcile_owned_legs(persisted=[],positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100"}],open_orders=[],fills=[],exchange_reliable=True)
    assert not r.allow_risk_increase and "ownership" in r.reasons[0]

def test_recovery_blocks_unknown_exchange():
    assert not reconcile_owned_legs(persisted=[owned()],positions=[],open_orders=[],fills=[],exchange_reliable=False).allow_risk_increase

def test_recovery_accepts_owned_matching_position():
    r=reconcile_owned_legs(persisted=[owned()],positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100"}],open_orders=[],fills=[],exchange_reliable=True)
    assert r.allow_risk_increase and len(r.legs)==1

def test_recovery_preserves_latest_confirmed_purchase_time():
    r=reconcile_owned_legs(persisted=[owned()],positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100"}],open_orders=[],fills=[{"symbol":"BTCUSDT","positionSide":"LONG","time":1723456789000}],exchange_reliable=True)
    assert r.legs[0].last_order_at_ms==1723456789000

def test_confirmed_flat_does_not_recreate_position():
    r=reconcile_owned_legs(persisted=[owned()],positions=[],open_orders=[],fills=[],exchange_reliable=True)
    assert r.allow_risk_increase and not r.legs and r.audit[0]["event"]=="CONFIRMED_FLAT"

def test_funding_fees_and_realized_are_rebuilt_without_counting_transfer_as_profit():
    result=funding_and_costs(trades=[{"commission":"0.2","realizedPnl":"3"}],income=[
        {"incomeType":"FUNDING_FEE","income":"-0.1"},{"incomeType":"TRANSFER","income":"100"}])
    assert result["fees"]==.2 and result["realizedPnl"]==3.0 and result["funding"]==-.1
    assert result["externalCashflow"]==100.0 and result["netTradingResult"]==pytest.approx(2.7)
