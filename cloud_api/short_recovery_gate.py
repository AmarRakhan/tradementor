"""Pure fail-closed, shadow-only configuration and 1:1 reconciliation classification."""
from decimal import Decimal, InvalidOperation

def decimal(v):
    try: x=Decimal(str(v))
    except (ValueError,TypeError,InvalidOperation) as e: raise ValueError("invalid percentage") from e
    if not x.is_finite(): raise ValueError("nonfinite percentage")
    return x

def normalize_settings(raw):
    if raw is None: raw={}
    if not isinstance(raw,dict):raise ValueError("invalid settings")
    n=raw.get("steps",4); p=decimal(raw.get("stepPct","3"))
    if isinstance(n,bool) or not isinstance(n,int) or not 1<=n<=100 or p<=0 or p*n>=100:
        raise ValueError("invalid step count/level")
    return {"enabled":raw.get("enabled") is True,"steps":n,"stepPct":str(p),
            "reducePct":str(Decimal(100)/n),"lastLevelPct":str(p*n)}

def partition_reconciliation(*,settings,protected_sides,existing_skip_symbols,recovery_cycles):
    config=normalize_settings(settings)
    legacy=set(existing_skip_symbols)
    if not config["enabled"]:
        return {"status":"OFF","legacy_skip":legacy,"shadow_skip":legacy,"orders":0}
    shadow=set(legacy);status={}
    for symbol,row in recovery_cycles.items():
        if (protected_sides.get(symbol)!="LONG" or row.get("ownerSide")!="SHORT"
                or row.get("cycleConfirmed") is not True
                or row.get("ownershipVerified") is not True
                or row.get("state") not in {"PARTIAL","FINAL_PENDING"}):
            status[symbol]="BLOCKED_UNVERIFIED"
            continue
        shadow.add(symbol);status[symbol]="SHADOW_PARTIAL_NO_TOPUP"
    # Live reconciliation deliberately receives no modifications.
    return {"status":"SHADOW_ONLY","legacy_skip":legacy,"shadow_skip":shadow,
            "pairs":status,"orders":0}
