import pytest
from money_grabber_intents import DurableIntent,from_mapping,mark_submitting,mark_unknown,may_submit,prepare,reconcile,to_mapping

def intent(**kw):return DurableIntent("i","a","r","PROTECT","BTCUSDT","SHORT",10,**kw)

def test_persisted_intent_survives_restart_and_can_submit_only_once():
    value=from_mapping(to_mapping(prepare(None,intent())))
    assert may_submit(value)
    sent=mark_submitting(value,1)
    assert not may_submit(sent)
    with pytest.raises(RuntimeError):mark_submitting(sent,2)

def test_duplicate_scheduler_returns_same_existing_intent_without_second_send():
    existing=mark_submitting(intent(),1)
    assert prepare(existing,intent())==existing and not may_submit(existing)

def test_unknown_status_never_blindly_retries_and_requires_reconciliation():
    unknown=mark_unknown(mark_submitting(intent(),1),2)
    assert not may_submit(unknown)
    missing=reconcile(unknown,order_found=False,terminal_status="",now_ms=3)
    assert missing.status=="RECOVERY" and not may_submit(missing)

def test_reconciliation_confirms_real_fill_or_definite_rejection():
    unknown=mark_unknown(mark_submitting(intent(),1),2)
    filled=reconcile(unknown,order_found=True,terminal_status="FILLED",exchange_order_id="o",filled_notional=9.5,now_ms=3)
    assert filled.status=="CONFIRMED" and filled.filled_notional==9.5
    rejected=reconcile(unknown,order_found=True,terminal_status="REJECTED",exchange_order_id="o",now_ms=3)
    assert rejected.status=="REJECTED"

def test_same_id_cannot_change_account_round_symbol_direction_or_kind():
    base=intent()
    for changed in (DurableIntent("i","b","r","PROTECT","BTCUSDT","SHORT",10),
        DurableIntent("i","a","x","PROTECT","BTCUSDT","SHORT",10),
        DurableIntent("i","a","r","PROTECT","ETHUSDT","SHORT",10),
        DurableIntent("i","a","r","PROTECT","BTCUSDT","LONG",10),
        DurableIntent("i","a","r","CLOSE","BTCUSDT","SHORT",10)):
        with pytest.raises(ValueError):prepare(base,changed)
