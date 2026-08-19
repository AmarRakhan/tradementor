"""Small deterministic Strategy-2 reliability event model (no AI/runtime orders)."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

TERMINAL={"AUTO_RECOVERED","SOFTWARE_FIXED"}
OPEN={"DETECTED","RECOVERING","OPEN","SAFETY_HOLD"}

def event_key(uid:str,component:str,category:str,error_code:str="")->str:
    raw="-".join(filter(None,(uid,component,category,error_code or "none")))
    return raw.replace("/","-").replace(" ","-")[:300]

def event_payload(*,uid:str,component:str,error_code:str,category:str,cause:str,original_status:str,recovery_action:str,status:str,existing:dict[str,Any]|None=None,now:datetime|None=None,software_version:str="")->dict[str,Any]:
    now=now or datetime.now(timezone.utc); old=existing or {}; first=old.get("firstDetectedAt") or now
    payload={"uid":uid,"component":component,"errorCode":error_code,"category":category,"cause":cause[:500],"originalStatus":original_status,
        "recoveryAction":recovery_action,"status":status,"firstDetectedAt":first,"lastDetectedAt":now,
        "affectedScans":int(old.get("affectedScans") or 0)+1,"softwareVersion":software_version or old.get("softwareVersion","")}
    payload["recoveredAt"] = old.get("recoveredAt") or now if status in TERMINAL else None
    return payload

def counts(events:list[dict[str,Any]])->dict[str,int]:
    return {"found":len(events),"autoRecovered":sum(e.get("status")=="AUTO_RECOVERED" for e in events),
        "softwareFixed":sum(e.get("status")=="SOFTWARE_FIXED" for e in events),"open":sum(e.get("status") in {"DETECTED","RECOVERING","OPEN"} for e in events),
        "safetyHolds":sum(e.get("status")=="SAFETY_HOLD" for e in events)}

def overall(events:list[dict[str,Any]])->str:
    if any(e.get("status") in {"OPEN","SAFETY_HOLD","DETECTED"} for e in events): return "ACTION_REQUIRED"
    if any(e.get("status") in TERMINAL for e in events): return "RECOVERED"
    return "OK"
