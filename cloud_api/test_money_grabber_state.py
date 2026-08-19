from money_grabber import ProtectedPair,start_round,NetValueEvidence
from money_grabber_state import pair_from_mapping,pair_to_mapping,reconcile_pairs,round_from_mapping,round_to_mapping


def test_round_and_pair_persistence_survive_restart_exactly():
    r=start_round(account_id="a",round_id="r",target_ratio=.05,evidence=NetValueEvidence(100,fresh=True,reliable=True,captured_at_ms=1),activation_confirmed=True,ownership_reliable=True,hedge_mode=True,orders_known=True,contracts_known=True,protection_margin_sufficient=True,now_ms=1)
    p=ProtectedPair("a","r","BTCUSDT","LONG","PARTIAL_PROTECTION",20,10,10,"i")
    assert round_from_mapping(round_to_mapping(r))==r
    assert pair_from_mapping(pair_to_mapping(p))==p


def test_restart_recovers_actual_partial_and_full_fills_from_exchange():
    partial=ProtectedPair("a","r","BTCUSDT","LONG","PROTECTION_PENDING",20,0)
    rows=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"2"},{"symbol":"BTCUSDT","positionSide":"SHORT","positionAmt":"1"}]
    result,reasons=reconcile_pairs(account_id="a",round_id="r",pairs=[partial],positions=rows,open_orders=[],exchange_reliable=True)
    assert result[0].status=="PARTIAL_PROTECTION" and result[0].residual_notional==1 and not reasons
    rows[1]["positionAmt"]="2"
    result,_=reconcile_pairs(account_id="a",round_id="r",pairs=[partial],positions=rows,open_orders=[],exchange_reliable=True)
    assert result[0].status=="LOCKED"


def test_one_remaining_side_enters_recovery_and_never_free():
    pair=ProtectedPair("a","r","BTCUSDT","LONG","PAIR_CLOSING",2,2)
    result,reasons=reconcile_pairs(account_id="a",round_id="r",pairs=[pair],positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"2"}],open_orders=[],exchange_reliable=True)
    assert result[0].status=="RECOVERY" and reasons


def test_flat_pair_waits_one_full_scan_before_free():
    pair=ProtectedPair("a","r","BTCUSDT","LONG","PAIR_CLOSING",2,2)
    result,_=reconcile_pairs(account_id="a",round_id="r",pairs=[pair],positions=[],open_orders=[],exchange_reliable=True)
    assert result[0].status=="COOLDOWN"
    result,_=reconcile_pairs(account_id="a",round_id="r",pairs=result,positions=[],open_orders=[],exchange_reliable=True)
    assert result[0].status=="COOLDOWN" and result[0].cooldown_scans==1
    result,_=reconcile_pairs(account_id="a",round_id="r",pairs=result,positions=[],open_orders=[],exchange_reliable=True)
    assert result[0].status=="FREE"
