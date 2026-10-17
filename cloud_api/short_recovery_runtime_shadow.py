"""Fail-closed, read-only SHORT Recovery preview for existing Auto Hedge runtime."""
from decimal import Decimal, InvalidOperation

def number(value):
    try:
        v=Decimal(str(value))
        return v if v.is_finite() else None
    except (InvalidOperation,TypeError,ValueError):
        return None

def normalize_plan(raw):
    if not isinstance(raw,dict) or raw.get("enabled") is not True:
        return {"enabled":False,"status":"OFF"}
    steps=raw.get("steps")
    distance=number(raw.get("stepPct"))
    if isinstance(steps,bool) or not isinstance(steps,int) or not 1<=steps<=100 or distance is None or distance<=0 or steps*distance>=100:
        return {"enabled":False,"status":"INVALID_SETTINGS"}
    return {"enabled":True,"status":"SHADOW_ONLY","steps":steps,"stepPct":distance}

def preview_existing_pairs(*, settings, pair_states, positions, open_orders):
    """No new settings writes or orders. Never alters the 1:1 reconciliation."""
    plan=normalize_plan(settings.get("shortRecoveryPlan"))
    if not plan["enabled"]:
        return {"status":plan["status"],"ordersSent":0,"pairs":[]}
    if open_orders:
        return {"status":"BLOCKED_PENDING_ORDERS","ordersSent":0,"pairs":[]}
    results=[]
    for symbol,row in sorted(pair_states.items()):
        if str(row.get("protectedSide","")).upper()!="LONG" or str(row.get("hedgeSide","")).upper()!="SHORT":
            continue
        # Existing per-symbol ownership is not proof of distinct price-zone allocations.
        # Show eligibility only if a verified independent ownership flag exists.
        anchor=number((row.get("hedgeLeg") or {}).get("entryPrice"))
        if not row.get("recoveryOwnershipVerified") or anchor is None or anchor<=0:
            results.append({"symbol":symbol,"status":"BLOCKED_OWNERSHIP_OR_ANCHOR"})
            continue
        marks=[number(p.get("markPrice")) for p in positions if str(p.get("symbol","")).upper()==symbol]
        marks=[x for x in marks if x is not None and x>0]
        if not marks:
            results.append({"symbol":symbol,"status":"BLOCKED_PRICE"})
            continue
        mark=marks[0]
        decline=max(Decimal(0),(anchor-mark)/anchor*Decimal(100))
        reached=min(plan["steps"],int(decline//plan["stepPct"]))
        results.append({"symbol":symbol,"status":"PREVIEW_ONLY",
                        "anchor":str(anchor),"declinePct":str(decline),
                        "reachedSteps":reached,"steps":plan["steps"],
                        "targetClosePct":str(Decimal(100)*reached/plan["steps"])})
    return {"status":"SHADOW_ONLY","ordersSent":0,"pairs":results}
