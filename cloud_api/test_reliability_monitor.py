from datetime import datetime,timezone
from reliability_monitor import event_key,event_payload,counts,overall
NOW=datetime(2026,8,20,tzinfo=timezone.utc)
def test_dedup_key_and_scan_counter():
    key=event_key("u1","s2","contract","-5018"); assert key==event_key("u1","s2","contract","-5018")
    a=event_payload(uid="u1",component="s2",error_code="-5018",category="contract",cause="max",original_status="WAITING",recovery_action="skip",status="DETECTED",now=NOW)
    b=event_payload(uid="u1",component="s2",error_code="-5018",category="contract",cause="max",original_status="WAITING",recovery_action="skip",status="AUTO_RECOVERED",existing=a,now=NOW)
    assert b["affectedScans"]==2 and b["firstDetectedAt"]==a["firstDetectedAt"] and b["recoveredAt"]==NOW
def test_counters_and_safety_hold():
    rows=[{"status":"AUTO_RECOVERED"},{"status":"SOFTWARE_FIXED"},{"status":"OPEN"},{"status":"SAFETY_HOLD"}]
    assert counts(rows)=={"found":4,"autoRecovered":1,"softwareFixed":1,"open":1,"safetyHolds":1}; assert overall(rows)=="ACTION_REQUIRED"
def test_no_false_positive_recovery():
    row=event_payload(uid="u",component="queue",error_code="UNCERTAIN",category="order",cause="unknown",original_status="RECONCILING",recovery_action="reconcile",status="SAFETY_HOLD",now=NOW)
    assert row["recoveredAt"] is None and overall([row])=="ACTION_REQUIRED"
def test_account_isolation(): assert event_key("u1","s2","x")!=event_key("u2","s2","x")


def test_ui_polling_route_is_get_only_and_has_no_trading_write():
    from pathlib import Path
    route=(Path(__file__).parents[1]/"web/app/api/bot-health/route.ts").read_text()
    card=(Path(__file__).parents[1]/"web/components/bot-health-card.tsx").read_text()
    assert 'export async function GET' in route and 'POST' not in route and 'PUT' not in route
    compact=''.join(card.split())
    assert 'setInterval(load,12000)' in compact and 'method:' not in card
