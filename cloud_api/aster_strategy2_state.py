"""Persistent ownership, reconciliation and audit models for Aster Strategy 2."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal
import math

Side=Literal["LONG","SHORT"]

def number(value:Any)->float:
    try: result=float(value)
    except (TypeError,ValueError): return 0.0
    return result if math.isfinite(result) else 0.0

@dataclass(frozen=True)
class Fill:
    fill_id:str;intent_id:str;quantity:float;price:float;fee:float=0.0;timestamp_ms:int=0

@dataclass(frozen=True)
class OwnedLeg:
    strategy_id:str;engine_type:str;symbol:str;side:Side;cycle_id:str;config_version:int
    quantity:float=0.0;weighted_entry:float=0.0;dca_count:int=0;role:str="HARVEST"
    intent_ids:tuple[str,...]=();fill_ids:tuple[str,...]=();open_order_ids:tuple[str,...]=()
    created_at_ms:int=0;realized_pnl:float=0.0;fees:float=0.0;funding:float=0.0;last_order_at_ms:int=0

@dataclass(frozen=True)
class RecoveryResult:
    legs:tuple[OwnedLeg,...];allow_risk_increase:bool;reasons:tuple[str,...];audit:tuple[dict[str,Any],...]

def apply_confirmed_fill(leg:OwnedLeg,fill:Fill,*,is_dca:bool)->OwnedLeg:
    if fill.fill_id in leg.fill_ids:return leg
    if fill.quantity<=0 or fill.price<=0:raise ValueError("Partial fill moet een positieve werkelijk gevulde hoeveelheid en prijs hebben")
    old_notional=leg.quantity*leg.weighted_entry;new_quantity=leg.quantity+fill.quantity
    average=(old_notional+fill.quantity*fill.price)/new_quantity
    return replace(leg,quantity=new_quantity,weighted_entry=average,dca_count=leg.dca_count+(1 if is_dca else 0),
        intent_ids=tuple(dict.fromkeys((*leg.intent_ids,fill.intent_id))),fill_ids=tuple(dict.fromkeys((*leg.fill_ids,fill.fill_id))))

def funding_and_costs(*,trades:list[dict[str,Any]],income:list[dict[str,Any]])->dict[str,float]:
    """Rebuild net trading result while keeping deposits/withdrawals separate."""
    fees=sum(abs(number(x.get("commission"))) for x in trades)
    realized=sum(number(x.get("realizedPnl")) for x in trades)
    funding=0.0;external_cashflow=0.0
    for row in income:
        kind=str(row.get("incomeType","")).upper();amount=number(row.get("income"))
        if kind=="FUNDING_FEE":funding+=amount
        elif kind in {"TRANSFER","WELCOME_BONUS","INSURANCE_CLEAR"}:external_cashflow+=amount
    return {"fees":fees,"realizedPnl":realized,"funding":funding,"externalCashflow":external_cashflow,
        "netTradingResult":realized+funding-fees}

def reconcile_owned_legs(*,persisted:list[OwnedLeg],positions:list[dict[str,Any]],open_orders:list[dict[str,Any]],fills:list[dict[str,Any]],exchange_reliable:bool,strategy_label:str="Strategy-2")->RecoveryResult:
    if not exchange_reliable:return RecoveryResult(tuple(persisted),False,("Aster exchange-state kon niet betrouwbaar worden gelezen",),())
    by_key={(x.symbol,x.side):x for x in persisted};exchange={}
    for row in positions:
        symbol=str(row.get("symbol","")).upper();side=str(row.get("positionSide","")).upper();qty=abs(number(row.get("positionAmt")))
        if symbol and side in {"LONG","SHORT"} and qty>0:exchange[(symbol,side)]=(qty,number(row.get("entryPrice")))
    orders={}
    for row in open_orders:
        key=(str(row.get("symbol","")).upper(),str(row.get("positionSide","")).upper());orders.setdefault(key,[]).append(str(row.get("clientOrderId",row.get("orderId",""))))
    result=[];reasons=[];audit=[]
    for key,(qty,entry) in exchange.items():
        owned=by_key.get(key)
        if not owned:
            reasons.append(f"{key[0]} {key[1]}: exchange-exposure heeft geen bewezen {strategy_label}-ownership")
            continue
        changed=not math.isclose(owned.quantity,qty,rel_tol=1e-7,abs_tol=1e-8) or not math.isclose(owned.weighted_entry,entry,rel_tol=1e-7,abs_tol=1e-8)
        if changed:
            related=[x for x in fills if str(x.get("symbol","")).upper()==key[0] and str(x.get("positionSide","")).upper()==key[1]]
            if not related:
                reasons.append(f"{key[0]} {key[1]}: afwijking kan niet uit fills worden herbouwd")
            audit.append({"event":"RECONCILIATION","symbol":key[0],"side":key[1],"oldQuantity":owned.quantity,"newQuantity":qty})
        related=[x for x in fills if str(x.get("symbol","")).upper()==key[0] and str(x.get("positionSide","")).upper()==key[1]]
        latest_fill=max((int(number(x.get("time",x.get("timestamp",0)))) for x in related),default=0)
        result.append(replace(owned,quantity=qty,weighted_entry=entry,open_order_ids=tuple(x for x in orders.get(key,[]) if x),last_order_at_ms=max(owned.last_order_at_ms,latest_fill)))
    for key,owned in by_key.items():
        if key not in exchange and orders.get(key):reasons.append(f"{key[0]} {key[1]}: geen positie maar nog wel open order")
        elif key not in exchange:audit.append({"event":"CONFIRMED_FLAT","symbol":key[0],"side":key[1],"cycleId":owned.cycle_id})
    return RecoveryResult(tuple(result),not reasons,tuple(reasons or (f"Exchange-state en {strategy_label}-ownership zijn gereconcilieerd",)),tuple(audit))

def audit_event(event:str,*,strategy_id:str="aster-strategy-2",symbol:str="",side:str="",reason:str="",**details:Any)->dict[str,Any]:
    return {"event":event,"strategyId":strategy_id,"symbol":symbol,"side":side,"reason":reason,"details":details,"timestamp":datetime.now(timezone.utc)}
