import pytest

from strategy2_handoff import build_handoff_proof, proof_public


def scenario(count: int, long_count: int):
    positions=[];fills=[]
    for index in range(count):
        side="LONG" if index<long_count else "SHORT"
        symbol=f"S{index:03d}USDT"
        positions.append({"symbol":symbol,"positionSide":side,"positionAmt":"1","entryPrice":"100"})
        fills.append({"id":str(index+1),"symbol":symbol,"positionSide":side,
            "side":"BUY" if side=="LONG" else "SELL","qty":"1","price":"100","time":1000+index})
    return positions,fills


@pytest.mark.parametrize(("count","long_count","short_count"),[(0,0,0),(37,19,18),(68,34,34),(100,50,50)])
def test_dynamic_leg_counts_are_proven_exactly(count,long_count,short_count):
    positions,fills=scenario(count,long_count)
    proof=build_handoff_proof(positions=positions,open_orders=[],fills=fills,config_version=4,captured_at_ms=2000)
    public=proof_public(proof)
    assert proof.complete
    assert public["activeLegs"]==public["provenLegs"]==count
    assert public["longLegs"]==long_count and public["shortLegs"]==short_count


def test_missing_opening_fill_fails_closed():
    positions,fills=scenario(37,19)
    proof=build_handoff_proof(positions=positions,open_orders=[],fills=fills[:-1],config_version=1,captured_at_ms=1)
    assert not proof.complete and len(proof.missing_keys)==1


def test_open_order_blocks_handoff():
    positions,fills=scenario(1,1)
    proof=build_handoff_proof(positions=positions,open_orders=[{"orderId":"pending"}],fills=fills,config_version=1,captured_at_ms=1)
    assert not proof.complete and proof.open_order_count==1


def test_old_closed_cycle_cannot_prove_current_leg():
    positions=[{"symbol":"OLDUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100"}]
    fills=[
        {"id":"1","symbol":"OLDUSDT","positionSide":"LONG","side":"BUY","qty":"1","price":"90","time":1},
        {"id":"2","symbol":"OLDUSDT","positionSide":"LONG","side":"SELL","qty":"1","price":"95","time":2},
    ]
    proof=build_handoff_proof(positions=positions,open_orders=[],fills=fills,config_version=1,captured_at_ms=3)
    assert not proof.complete and proof.missing_keys==(("OLDUSDT","LONG"),)


def test_partial_close_reconstructs_the_current_open_quantity():
    positions=[{"symbol":"PARTUSDT","positionSide":"SHORT","positionAmt":"-1","entryPrice":"100"}]
    fills=[
        {"id":"1","symbol":"PARTUSDT","positionSide":"SHORT","side":"SELL","qty":"2","price":"100","time":1},
        {"id":"2","symbol":"PARTUSDT","positionSide":"SHORT","side":"BUY","qty":"1","price":"90","time":2},
    ]
    proof=build_handoff_proof(positions=positions,open_orders=[],fills=fills,config_version=1,captured_at_ms=3)
    assert proof.complete and len(proof.owned_legs)==1


def test_snapshot_fingerprint_changes_when_exchange_snapshot_changes():
    positions,fills=scenario(1,1)
    before=build_handoff_proof(positions=positions,open_orders=[],fills=fills,config_version=1,captured_at_ms=1)
    positions[0]["positionAmt"]="2"
    after=build_handoff_proof(positions=positions,open_orders=[],fills=fills,config_version=1,captured_at_ms=2)
    assert before.snapshot_fingerprint!=after.snapshot_fingerprint


def test_snapshot_fingerprint_ignores_unrelated_historical_fill_growth():
    positions,fills=scenario(1,1)
    before=build_handoff_proof(positions=positions,open_orders=[],fills=fills,config_version=1,captured_at_ms=1)
    fills.extend([
        {"id":"old-open","symbol":"OLDUSDT","positionSide":"LONG","side":"BUY","qty":"1","price":"90","time":1},
        {"id":"old-close","symbol":"OLDUSDT","positionSide":"LONG","side":"SELL","qty":"1","price":"95","time":2},
    ])
    after=build_handoff_proof(positions=positions,open_orders=[],fills=fills,config_version=1,captured_at_ms=2)
    assert before.complete and after.complete
    assert before.snapshot_fingerprint==after.snapshot_fingerprint


def test_duplicate_paginated_fill_is_counted_once_and_fingerprint_is_stable():
    positions,fills=scenario(1,1)
    before=build_handoff_proof(positions=positions,open_orders=[],fills=fills,config_version=1,captured_at_ms=1)
    after=build_handoff_proof(positions=positions,open_orders=[],fills=[fills[0],dict(fills[0])],config_version=1,captured_at_ms=2)
    assert before.complete and after.complete
    assert before.snapshot_fingerprint==after.snapshot_fingerprint


def test_equivalent_current_fill_aggregation_keeps_account_fingerprint_stable():
    positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100"}]
    aggregated=[{"id":"a","symbol":"BTCUSDT","positionSide":"LONG","side":"BUY","qty":"1","price":"100","time":1}]
    split=[
        {"id":"b","symbol":"BTCUSDT","positionSide":"LONG","side":"BUY","qty":"0.4","price":"99","time":1},
        {"id":"c","symbol":"BTCUSDT","positionSide":"LONG","side":"BUY","qty":"0.6","price":"101","time":2},
    ]
    before=build_handoff_proof(positions=positions,open_orders=[],fills=aggregated,config_version=1,captured_at_ms=1)
    positions[0]["entryPrice"]="100.00000000"
    after=build_handoff_proof(positions=positions,open_orders=[],fills=split,config_version=1,captured_at_ms=2)
    assert before.complete and after.complete
    assert before.snapshot_fingerprint==after.snapshot_fingerprint


def test_accounts_are_isolated_and_produce_independent_proofs():
    a_positions,a_fills=scenario(37,19);b_positions,b_fills=scenario(68,34)
    a=build_handoff_proof(positions=a_positions,open_orders=[],fills=a_fills,config_version=1,captured_at_ms=1)
    b=build_handoff_proof(positions=b_positions,open_orders=[],fills=b_fills,config_version=1,captured_at_ms=1)
    assert len(a.active_keys)==37 and len(b.active_keys)==68
    assert a.snapshot_fingerprint!=b.snapshot_fingerprint
