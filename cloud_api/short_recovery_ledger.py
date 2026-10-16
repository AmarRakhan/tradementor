"""Pure immutable hedge fill ledger. No orders or persistence."""
from dataclasses import dataclass, replace
from decimal import Decimal

def d(x):
    v=Decimal(str(x))
    if not v.is_finite(): raise ValueError("nonfinite")
    return v

@dataclass(frozen=True)
class Allocation:
    zone_id: str
    cycle_id: str
    remaining: Decimal

@dataclass(frozen=True)
class Fill:
    account: str
    symbol: str
    execution_id: str
    order_id: str
    closed_qty: Decimal
    realized_pnl: Decimal
    fee: Decimal
    funding: Decimal = Decimal("0")

@dataclass(frozen=True)
class Ledger:
    account: str
    symbol: str
    allocations: tuple[Allocation, ...]
    seen: frozenset[str] = frozenset()
    booked: tuple[tuple[str, str, Decimal, Decimal], ...] = ()

    def apply(self, fill: Fill, splits: tuple[tuple[str, str, Decimal], ...]):
        """Caller must persist using a compare-and-swap transaction."""
        if (fill.account,fill.symbol)!=(self.account,self.symbol): raise ValueError("scope")
        if not fill.execution_id or not fill.order_id or fill.execution_id in self.seen:
            raise ValueError("duplicate/missing fill")
        qty=d(fill.closed_qty)
        if qty<=0 or sum((d(q) for _,_,q in splits),d(0))!=qty: raise ValueError("quantity mismatch")
        keys=[(z,c) for z,c,_ in splits]
        if len(keys)!=len(set(keys)) or any(d(q)<=0 for _,_,q in splits): raise ValueError("invalid split")
        stock={(a.zone_id,a.cycle_id):a for a in self.allocations}
        if len(stock)!=len(self.allocations): raise ValueError("duplicate inventory")
        for z,c,q in splits:
            if (z,c) not in stock or d(q)>d(stock[(z,c)].remaining): raise ValueError("ambiguous/oversold")
        for z,c,q in splits:
            a=stock[(z,c)];stock[(z,c)]=replace(a,remaining=d(a.remaining)-d(q))
        net=d(fill.realized_pnl)-d(fill.fee)+d(fill.funding)
        bookings=tuple((z,c,d(q),net*d(q)/qty) for z,c,q in splits)
        return replace(self, allocations=tuple(stock[(a.zone_id,a.cycle_id)] for a in self.allocations),
            seen=self.seen|{fill.execution_id}, booked=self.booked+bookings)

    def cycle_realized(self, cycle_id):
        return sum((p for _,c,_,p in self.booked if c==cycle_id), d(0))

    def final_fill_confirmed(self, zone_id, cycle_id, required_ids, pending=False):
        row=next((a for a in self.allocations if (a.zone_id,a.cycle_id)==(zone_id,cycle_id)),None)
        return bool(row and d(row.remaining)==0 and not pending and bool(required_ids) and required_ids.issubset(self.seen))

    def rollback_risk(self):
        return "LEGACY_1_TO_1_TOPUP_RISK" if self.allocations else "NOT_PROVEN"
