"""Privacy-safe health classification and bounded self-healing for TradeMentor."""
from __future__ import annotations
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
from typing import Any

NORMAL_PHASES={"RUNNING","WAITING","INITIAL_BUILD","PROTECTION","STOPPED","DRAFT","CONFIGURED"}

@dataclass(frozen=True)
class HealthResult:
    status:str;category:str;severity:str;summary:str;can_auto_heal:bool=False
    def mapping(self)->dict[str,Any]:return asdict(self)

def _seconds(value:Any,now:datetime)->float|None:
    if not isinstance(value,datetime):return None
    current=value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return max(0.0,(now-current).total_seconds())

def classify_bot_health(state:dict[str,Any],*,now:datetime|None=None)->HealthResult:
    now=now or datetime.now(timezone.utc);enabled=bool(state.get("enabled"));monitor=bool(state.get("monitor"));phase=str(state.get("phase","UNKNOWN")).upper();reason=str(state.get("lastReason","")).strip()
    if not enabled and not monitor:return HealthResult("healthy","stopped","info","Bot is bewust gestopt")
    age=_seconds(state.get("lastTickAt"),now)
    if age is None:return HealthResult("action_required","missing_data","high","Geen betrouwbare laatste botcontrole beschikbaar")
    if age>1800:return HealthResult("action_required","stale_scheduler","high",f"Bot reageert al {int(age//60)} minuten niet",True)
    if age>180:return HealthResult("warning","late_scheduler","medium",f"Laatste botcontrole is {int(age//60)} minuten oud",True)
    lower=reason.lower()
    if "portfolio risk engine" in lower or "risk" in lower and "blokkeer" in lower:
        return HealthResult("safety_blocked","risk_policy","medium","Nieuwe exposure is bewust door risicobeheer geblokkeerd")
    if "geen bewezen strategy-2-ownership" in lower:
        return HealthResult("action_required","ownership","high","Positie-eigendom moet veilig worden gereconcilieerd")
    if "minimale exchangeorder" in lower:
        return HealthResult("warning","exchange_minimum","medium","Een order voldoet niet aan het exchange-minimum",True)
    if phase in {"DATA_HOLD","RECONCILING","ERROR","FAILED"}:
        return HealthResult("warning","technical_hold","medium",reason or "Technische controle houdt nieuwe exposure tegen",phase=="RECONCILING")
    if phase in NORMAL_PHASES:return HealthResult("healthy","normal","info",reason or "Bot reageert normaal")
    return HealthResult("insufficient_data","unknown_phase","medium",reason or f"Onbekende botfase {phase}")

def safe_recovery_plan(state:dict[str,Any],health:HealthResult,*,now:datetime|None=None)->list[str]:
    """Return only idempotent actions that never create, close or resize exposure."""
    now=now or datetime.now(timezone.utc);actions=[]
    lease=state.get("leaseUntil")
    if health.category in {"stale_scheduler","late_scheduler"} and isinstance(lease,datetime) and lease<now:actions.append("release_stale_lease")
    if health.category in {"stale_scheduler","late_scheduler","technical_hold"}:actions.append("request_reconciliation")
    if health.category=="exchange_minimum":actions.append("skip_invalid_dca_candidate")
    return list(dict.fromkeys(actions))

def incident_key(uid:str,component:str,category:str)->str:
    safe="-".join(x for x in (uid,component,category) if x)
    return safe.replace("/","-")[:240]
