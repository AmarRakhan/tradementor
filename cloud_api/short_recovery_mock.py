"""Pure mock dispatcher. No client, storage, network, or actual order calls."""
from dataclasses import dataclass
from decimal import Decimal

def d(x):
    n=Decimal(str(x))
    if not n.is_finite(): raise ValueError("nonfinite")
    return n

def canonical_settings(raw):
    if not isinstance(raw,dict) or raw.get("enabled") is not True:
        return {"enabled":False,"stepPct":"3","steps":4}
    n=raw.get("steps")
    pct=d(raw.get("stepPct"))
    if isinstance(n,bool) or not isinstance(n,int) or not 1<=n<=100 or pct<=0 or pct*n>=100:
        raise ValueError("invalid plan")
    return {"enabled":True,"stepPct":str(pct),"steps":n}

@dataclass(frozen=True)
class Cycle:
    anchor: Decimal
    initial: Decimal
    confirmed_closed: Decimal=Decimal(0)
    cycle: int=1
    pending: bool=False

def mock_scan(cycle,mark,settings,*,net_tp=False,exchange_short=None,long_qty=None):
    """Read-only decision; runtime 1:1 override not yet connected."""
    s=canonical_settings(settings)
    if not s["enabled"]: return "OFF",d(0)
    if cycle.anchor<=0 or cycle.initial<=0 or cycle.confirmed_closed<0 or cycle.confirmed_closed>cycle.initial:
        return "BLOCKED",d(0)
    if cycle.pending: return "WAIT_PENDING",d(0)
    if net_tp: return "EXIT_PAIR",d(0)
    remain=cycle.initial-cycle.confirmed_closed
    if exchange_short is None or d(exchange_short)!=remain:
        return "BLOCKED_EXCHANGE_MISMATCH",d(0)
    if remain==0:
        return ("REHEDGE_PREVIEW",d(long_qty)) if long_qty is not None and d(long_qty)>0 else ("BLOCKED_NO_LONG",d(0))
    decline=max(d(0),(cycle.anchor-d(mark))*100/cycle.anchor)
    reached=min(s["steps"],int(decline//d(s["stepPct"])))
    due=max(d(0),cycle.initial*d(reached)/d(s["steps"])-cycle.confirmed_closed)
    return ("MOCK_REDUCE",due) if due>0 else ("HOLD_PARTIAL",d(0))

def confirmed_fill(cycle,qty):
    q=d(qty)
    if q<=0 or cycle.confirmed_closed+q>cycle.initial or cycle.pending: raise ValueError("invalid fill")
    return Cycle(cycle.anchor,cycle.initial,cycle.confirmed_closed+q,cycle.cycle)
