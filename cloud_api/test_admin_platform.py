from datetime import datetime,timedelta,timezone
from admin_platform import classify_bot_health,safe_recovery_plan,incident_key

NOW=datetime(2026,8,11,12,tzinfo=timezone.utc)

def test_waiting_bot_is_healthy_not_stuck():
    result=classify_bot_health({"enabled":True,"monitor":True,"phase":"WAITING","lastTickAt":NOW-timedelta(seconds=40),"lastReason":"Wacht op marktvoorwaarde"},now=NOW)
    assert result.status=="healthy" and result.category=="normal"

def test_risk_block_is_safety_status_not_technical_failure():
    result=classify_bot_health({"enabled":True,"monitor":True,"phase":"DATA_HOLD","lastTickAt":NOW,"lastReason":"Portfolio Risk Engine blokkeert deze order"},now=NOW)
    assert result.status=="safety_blocked" and not result.can_auto_heal

def test_stale_scheduler_only_gets_idempotent_recovery_actions():
    state={"enabled":True,"monitor":True,"phase":"RUNNING","lastTickAt":NOW-timedelta(hours=1),"leaseUntil":NOW-timedelta(minutes=10)}
    health=classify_bot_health(state,now=NOW)
    assert safe_recovery_plan(state,health,now=NOW)==["release_stale_lease","request_reconciliation"]

def test_unknown_ownership_is_never_auto_claimed():
    state={"enabled":True,"monitor":True,"phase":"RECONCILING","lastTickAt":NOW,"lastReason":"BTCUSDT LONG: exchange-exposure heeft geen bewezen Strategy-2-ownership"}
    health=classify_bot_health(state,now=NOW)
    assert health.status=="action_required" and safe_recovery_plan(state,health,now=NOW)==[]

def test_incident_key_is_stable_and_path_safe():
    assert incident_key("abc/123","strategy2","late_scheduler")=="abc-123-strategy2-late_scheduler"
