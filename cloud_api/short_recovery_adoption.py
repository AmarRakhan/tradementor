"""Pure shadow-only adoption evaluation for ALREADY OPEN hedge SHORTs."""
from dataclasses import dataclass
from decimal import Decimal

def d(x):
    v=Decimal(str(x))
    if not v.is_finite(): raise ValueError("not finite")
    return v

@dataclass(frozen=True)
class ExistingHedge:
    account: str
    symbol: str
    long_position_id: str
    hedge_cycle_id: str
    long_qty: Decimal
    short_qty: Decimal
    exchange_long_qty: Decimal
    exchange_short_qty: Decimal
    current_mark_price: Decimal
    confirmed_hedge_entry_price: Decimal = Decimal('0')
    pending_orders: bool = False
    ownership_verified: bool = False

def adoption_preview(h: ExistingHedge, *, user_enabled: bool, steps: int, step_pct) -> dict:
    """Shadow-only preview. Use verified original SHORT fill price, never ROI."""
    if not user_enabled: return {"status":"OFF"}
    if not h.account or not h.symbol or not h.long_position_id or not h.hedge_cycle_id:
        return {"status":"BLOCKED_IDENTITY"}
    if not h.ownership_verified: return {"status":"BLOCKED_OWNERSHIP"}
    if h.pending_orders: return {"status":"BLOCKED_PENDING"}
    if min(d(h.long_qty),d(h.short_qty),d(h.exchange_long_qty),d(h.exchange_short_qty),d(h.current_mark_price),d(h.confirmed_hedge_entry_price)) <= 0:
        return {"status":"BLOCKED_QUANTITY_OR_PRICE"}
    if d(h.long_qty)!=d(h.exchange_long_qty) or d(h.short_qty)!=d(h.exchange_short_qty):
        return {"status":"BLOCKED_EXCHANGE_MISMATCH"}
    if d(h.short_qty)!=d(h.long_qty):
        return {"status":"BLOCKED_NOT_EXACT_1_TO_1"}
    if isinstance(steps,bool) or not isinstance(steps,int) or not 1<=steps<=100:
        return {"status":"BLOCKED_SETTINGS"}
    rate=d(step_pct)
    if rate<=0 or rate*steps>=100: return {"status":"BLOCKED_SETTINGS"}
    anchor=d(h.confirmed_hedge_entry_price)
    decline=max(Decimal(0),(anchor-d(h.current_mark_price))/anchor*Decimal(100))
    reached=min(steps,int(decline//rate))
    return {"status":"ELIGIBLE_PREVIEW_ONLY","anchor_price":anchor,
            "original_short_qty":d(h.short_qty),"completed_steps":0,
            "reached_steps":reached,"planned_close_qty":d(h.short_qty)*Decimal(reached)/Decimal(steps),
            "next_trigger":anchor*(Decimal(1)-rate*Decimal(reached+1)/Decimal(100)) if reached<steps else None,
            "requires_explicit_atomic_activation":True}
