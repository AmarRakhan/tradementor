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


def blocks_live_recovery_without_canonical_fence(settings):
    """Fail closed before any live client when Recovery ownership is unresolved."""
    if settings is None:
        return False
    try:
        return normalize_settings(settings)['enabled']
    except (TypeError, ValueError, KeyError):
        return True


def resolve_existing_active_strategy(settings):
    """Read-only strategy decision over the existing canonical Auto Hedge config.

    An enabled shortRecoveryPlan selects Recovery but grants no live order right.
    Missing/disabled plan preserves legacy Classic behavior; malformed input
    fails closed. No second configuration collection or router is created.
    """
    if not isinstance(settings, dict):
        return 'BLOCKED_INVALID_ACTIVE_SETTINGS'
    if 'shortRecoveryPlan' not in settings or settings['shortRecoveryPlan'] is None:
        return 'ASTER_CLASSIC'
    try:
        config = normalize_settings(settings['shortRecoveryPlan'])
    except (TypeError, ValueError, KeyError):
        return 'BLOCKED_INVALID_ACTIVE_SETTINGS'
    return 'AUTO_HEDGE_SHORT_RECOVERY_2' if config['enabled'] else 'ASTER_CLASSIC'
