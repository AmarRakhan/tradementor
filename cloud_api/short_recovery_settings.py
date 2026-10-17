"""Canonical Short Recovery settings validation; no Firestore or orders."""
from decimal import Decimal, InvalidOperation

def _number(value):
    try:
        v=Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("stepPct must be numeric")
    if not v.is_finite(): raise ValueError("stepPct must be finite")
    return v

def canonical_recovery_settings(value=None):
    if value is None:
        return {"enabled":False,"stepPct":"3","steps":4,"mode":"OFF"}
    if not isinstance(value,dict): raise ValueError("settings must be object")
    enabled=value.get("enabled",False)
    if not isinstance(enabled,bool): raise ValueError("enabled must be bool")
    steps=value.get("steps",4)
    if isinstance(steps,bool) or not isinstance(steps,int) or not 1<=steps<=100:
        raise ValueError("steps must be integer 1..100")
    step_pct=_number(value.get("stepPct","3"))
    if step_pct<=0 or step_pct*steps>=100:
        raise ValueError("final trigger must be above zero")
    return {"enabled":enabled,"stepPct":str(step_pct),"steps":steps,
            "mode":"SHADOW_ONLY" if enabled else "OFF"}

def project_user_settings(account_settings):
    """Read-only canonical projection. Never infer enabled from Auto Hedge enabled."""
    return canonical_recovery_settings((account_settings or {}).get("shortRecoveryPlan"))

def execution_allowed(settings):
    """Hard safety gate: this phase cannot authorize recovery orders."""
    return False

def reconcile_routing(*, settings, deliberate_partial_symbols, existing_skip_symbols):
    """Keep legacy reconciler untouched until a separately approved execution switch."""
    config=project_user_settings(settings)
    return {"runtime":"SHADOW_ONLY" if config["enabled"] else "LEGACY",
            "legacy_skip_symbols":set(existing_skip_symbols),
            "preview_excluded_symbols":set(deliberate_partial_symbols) if config["enabled"] else set(),
            "execution_allowed":False}
