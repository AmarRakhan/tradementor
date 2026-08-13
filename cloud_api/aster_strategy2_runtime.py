"""Pure runtime projection/planning for persistent Aster Strategy 2 ticks."""
from __future__ import annotations
from dataclasses import asdict, replace
import math
from typing import Any
from aster_strategy2 import Decision,LegState,PortfolioState,Strategy2Config,decide_leg,risk_mode
from aster_strategy2_state import OwnedLeg,number

def recover_audited_ownership(*,persisted:list[OwnedLeg],positions:list[dict[str,Any]],
                              audit_events:list[dict[str,Any]],fills:list[dict[str,Any]],
                              excluded_keys:set[tuple[str,str]]|None=None)->tuple[list[OwnedLeg],list[dict[str,Any]]]:
    """Recover a missing leg only when both our audit and a matching Aster fill prove ownership."""
    result=list(persisted);known={(x.symbol,x.side) for x in result};recovered=[];active=active_position_map(positions)
    excluded_keys=excluded_keys or set()
    opens=[]
    for event in audit_events:
        if str(event.get("event","")).upper()!="INITIAL_OPEN_LEG":continue
        symbol=str(event.get("symbol","")).upper();side=str(event.get("side","")).upper()
        if (symbol,side) not in active or (symbol,side) in known or (symbol,side) in excluded_keys:continue
        stamp=event.get("timestamp");stamp_ms=int(stamp.timestamp()*1000) if hasattr(stamp,"timestamp") else int(number(stamp))
        opens.append((stamp_ms,event,symbol,side))
    opens.sort(key=lambda x:x[0],reverse=True)
    for stamp_ms,event,symbol,side in opens:
        key=(symbol,side);cycle=str(event.get("cycleId",event.get("cycle_id","")))
        if key in known:continue
        if any(str(x.get("event","")).upper()=="CONFIRMED_FLAT" and str(x.get("symbol","")).upper()==symbol and
               str(x.get("side","")).upper()==side and (not cycle or str(x.get("cycleId",x.get("cycle_id","")))==cycle)
               for x in audit_events):continue
        matching=[]
        for fill in fills:
            if str(fill.get("symbol","")).upper()!=symbol or str(fill.get("positionSide","")).upper()!=side:continue
            fill_ms=int(number(fill.get("time",fill.get("timestamp",0))))
            if stamp_ms and abs(fill_ms-stamp_ms)<=300_000:matching.append(fill)
        row=active[key];qty=abs(number(row.get("positionAmt")));entry=number(row.get("entryPrice"))
        if not matching or qty<=0 or entry<=0:continue
        leg=OwnedLeg(strategy_id="aster-strategy-2",engine_type="strategy2",symbol=symbol,side=side,
            cycle_id=cycle or f"recovered-{stamp_ms}",config_version=int(number(event.get("configVersion",1))) or 1,
            quantity=qty,weighted_entry=entry,role="HARVEST",created_at_ms=stamp_ms,
            fill_ids=tuple(str(x.get("id",x.get("tradeId",""))) for x in matching if x.get("id",x.get("tradeId"))),
            last_order_at_ms=max((int(number(x.get("time",x.get("timestamp",0)))) for x in matching),default=stamp_ms))
        result.append(leg);known.add(key);recovered.append({"symbol":symbol,"side":side,"cycleId":leg.cycle_id})
    return result,recovered

def owned_from_mapping(row:dict[str,Any])->OwnedLeg:
    values=dict(row)
    for key in ("intent_ids","fill_ids","open_order_ids"):
        values[key]=tuple(values.get(key,()))
    return OwnedLeg(**values)

def owned_to_mapping(leg:OwnedLeg)->dict[str,Any]:
    value=asdict(leg)
    for key in ("intent_ids","fill_ids","open_order_ids"):value[key]=list(value[key])
    return value

def remove_strategy3_proven_conflicts(*,strategy2_legs:list[OwnedLeg],strategy3_legs:list[OwnedLeg])->tuple[list[OwnedLeg],list[dict[str,Any]]]:
    """Remove only S2 metadata shadowing an explicitly intent-proven S3 leg.

    This never changes exchange exposure. Ambiguous collisions remain intact
    so the caller continues to fail closed.
    """
    proven={(leg.symbol,leg.side) for leg in strategy3_legs
        if leg.strategy_id=="aster-strategy-3" and leg.engine_type=="strategy3"
        and any(str(intent).startswith("s3-") for intent in leg.intent_ids)}
    kept=[];removed=[]
    for leg in strategy2_legs:
        if (leg.symbol,leg.side) in proven:
            removed.append({"symbol":leg.symbol,"side":leg.side,"cycleId":leg.cycle_id,
                "reason":"Expliciete Strategy-3-orderintent bewijst ownership; foutieve Strategy-2-schaduwclaim verwijderd"})
        else:kept.append(leg)
    return kept,removed

def active_position_map(rows:list[dict[str,Any]])->dict[tuple[str,str],dict[str,Any]]:
    return {(str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()):x for x in rows
        if abs(number(x.get("positionAmt")))>0 and str(x.get("positionSide","")).upper() in {"LONG","SHORT"}}

def changed_owned_symbols(owned:list[OwnedLeg],positions:list[dict[str,Any]])->set[str]:
    """Symbols that need fill-history recovery because position truth changed."""
    pos=active_position_map(positions);changed=set()
    for leg in owned:
        row=pos.get((leg.symbol,leg.side))
        if row is None:continue
        quantity=abs(number(row.get("positionAmt")));entry=number(row.get("entryPrice"))
        if (not math.isclose(leg.quantity,quantity,rel_tol=1e-7,abs_tol=1e-8)
                or not math.isclose(leg.weighted_entry,entry,rel_tol=1e-7,abs_tol=1e-8)):
            changed.add(leg.symbol)
    return changed

def portfolio_state(config:Strategy2Config,account:dict[str,Any],positions:list[dict[str,Any]],owned:list[OwnedLeg],hwm:float,
                    *,exchange_reliable:bool=True,ownership_reliable:bool=True,open_orders_unknown:bool=False)->PortfolioState:
    wallet=number(account.get("totalWalletBalance"));unrealized=number(account.get("totalUnrealizedProfit"))
    equity=number(account.get("totalMarginBalance")) or wallet+unrealized
    maint=number(account.get("totalMaintMargin"));pos=active_position_map(positions)
    long_exposure=sum(abs(number(x.get("positionAmt")))*number(x.get("markPrice")) for x in positions if str(x.get("positionSide","")).upper()=="LONG")
    short_exposure=sum(abs(number(x.get("positionAmt")))*number(x.get("markPrice")) for x in positions if str(x.get("positionSide","")).upper()=="SHORT")
    strategy_exposure=sum(abs(number(pos.get((x.symbol,x.side),{}).get("positionAmt")))*number(pos.get((x.symbol,x.side),{}).get("markPrice")) for x in owned)
    strategy_margin=sum(abs(number(pos.get((x.symbol,x.side),{}).get("positionAmt")))*number(pos.get((x.symbol,x.side),{}).get("markPrice"))
        / max(1,number(pos.get((x.symbol,x.side),{}).get("leverage")) or config.leverage) for x in owned)
    return PortfolioState(equity,max(hwm,equity),maint/equity if equity>0 else 1.0,long_exposure,short_exposure,strategy_exposure,
        exchange_reliable,ownership_reliable,open_orders_unknown,strategy_margin)

def leg_projection(owned:OwnedLeg,row:dict[str,Any])->LegState:
    mark=number(row.get("markPrice"));qty=abs(number(row.get("positionAmt")));entry=number(row.get("entryPrice")) or owned.weighted_entry
    notional=qty*mark
    return LegState(owned.side,owned.cycle_id,notional,entry,mark,owned.dca_count,owned.realized_pnl,
        number(row.get("unRealizedProfit",row.get("unrealizedProfit"))),owned.fees,owned.funding,owned.role,owned.config_version,"HARVEST")

def next_management_decision(config:Strategy2Config,portfolio:PortfolioState,owned:list[OwnedLeg],positions:list[dict[str,Any]],
                             excluded_dca:set[tuple[str,str]]|None=None)->tuple[OwnedLeg,Decision]|None:
    pos=active_position_map(positions);rank={"FULL_TP":0,"PARTIAL_TP":0,"ASSIGN_PROTECTION":1,"ADD_DCA":2,"HOLD":9}
    excluded_dca=excluded_dca or set()
    choices=[]
    for item in owned:
        row=pos.get((item.symbol,item.side))
        if not row:continue
        decision=decide_leg(config,leg_projection(item,row),portfolio,estimated_close_fee=abs(number(row.get("notional")))*.0005)
        if decision.kind=="ADD_DCA" and (item.symbol,item.side) in excluded_dca:
            continue
        choices.append((rank.get(decision.kind,8),item,decision))
    if not choices:return None
    choices.sort(key=lambda x:x[0])
    return (choices[0][1],choices[0][2]) if choices[0][2].kind!="HOLD" else None

def scanner_allowed(config:Strategy2Config,portfolio:PortfolioState,owned:list[OwnedLeg])->bool:
    harvest=[x for x in owned if x.role!="PROTECTION"]
    new_pair_margin=config.base_notional/max(1,config.leverage)
    return risk_mode(config,portfolio)=="NORMAL" and len(harvest)<config.maximum_pairs and portfolio.strategy_margin+new_pair_margin<=portfolio.equity*config.strategy_budget

def balanced_entry_targets(total:int)->tuple[int,int]:
    """Return the closest possible LONG/SHORT split for a total position cap."""
    total=max(1,int(total))
    return ((total+1)//2,total//2)

def harvest_counts(owned:list[OwnedLeg])->tuple[int,int]:
    values=[x for x in owned if x.role!="PROTECTION"]
    return (sum(1 for x in values if x.side=="LONG"),sum(1 for x in values if x.side=="SHORT"))

def next_balanced_entry_side(owned:list[OwnedLeg],total:int)->str|None:
    long_target,short_target=balanced_entry_targets(total);long_count,short_count=harvest_counts(owned)
    if long_count>=long_target and short_count>=short_target:return None
    if long_count<short_count and long_count<long_target:return "LONG"
    if short_count<long_count and short_count<short_target:return "SHORT"
    if long_count<long_target:return "LONG"
    return "SHORT" if short_count<short_target else None

def entry_order_limit(initial_build_complete:bool,owned:list[OwnedLeg],total:int)->int:
    long_target,short_target=balanced_entry_targets(total);long_count,short_count=harvest_counts(owned)
    remaining=max(0,(long_target-long_count)+(short_target-short_count))
    return min(1,remaining) if initial_build_complete else remaining

def management_preempts_initial_build(config:Strategy2Config,owned:list[OwnedLeg],decision:Decision)->bool:
    """Existing-position management always precedes initial entry building.

    A balanced start target controls only *new* entries. It must never postpone
    TP, DCA, recovery or protection for an already owned position. Otherwise a
    pair/risk limit can leave the startup incomplete forever while profitable
    legs remain unmanaged.
    """
    return decision.kind != "HOLD"

def same_pair_protection_decision(config:Strategy2Config,portfolio:PortfolioState,owned:list[OwnedLeg],positions:list[dict[str,Any]])->tuple[OwnedLeg,Decision]|None:
    """Open an opposite same-symbol leg only after risk has escalated.

    Normal harvest entries never create a mandatory same-pair hedge. Protection
    starts at CAUTION and requires an actually losing, DCA-active leg (or a
    stronger portfolio risk mode), so a tiny spread loss cannot trigger it.
    """
    mode=risk_mode(config,portfolio)
    if not config.protection_enabled or mode=="NORMAL":return None
    pos=active_position_map(positions);keys={(x.symbol,x.side) for x in owned}
    candidates=[]
    for leg in owned:
        if leg.role=="PROTECTION":continue
        row=pos.get((leg.symbol,leg.side));opposite="SHORT" if leg.side=="LONG" else "LONG"
        if not row or (leg.symbol,opposite) in keys or (leg.symbol,opposite) in pos:continue
        loss=number(row.get("unRealizedProfit",row.get("unrealizedProfit")))
        if loss>=0 or (leg.dca_count<1 and mode=="CAUTION"):continue
        notional=abs(number(row.get("positionAmt")))*number(row.get("markPrice"))
        amount=min(notional*config.max_protection_ratio,portfolio.equity*config.max_protection_ratio)
        if amount>0:candidates.append((loss,leg,Decision("OPEN_PROTECTION",opposite,notional=amount,role="PROTECTION",reason=f"{mode}: {leg.symbol} {leg.side} krijgt dezelfde-pair bescherming")))
    if not candidates:return None
    candidates.sort(key=lambda x:x[0])
    return candidates[0][1],candidates[0][2]

def portfolio_protection_decision(config:Strategy2Config,portfolio:PortfolioState,owned:list[OwnedLeg])->tuple[OwnedLeg,Decision]|None:
    mode=risk_mode(config,portfolio)
    protected=[x for x in owned if x.role in {"PROTECTION","HARVEST_PROTECTION"}]
    if mode=="NORMAL" and protected:
        leg=protected[0]
        if leg.role=="PROTECTION":return leg,Decision("CLOSE_PROTECTION",leg.side,notional=leg.quantity*leg.weighted_entry,role="PROTECTION",reason="Portfolio is terug in NORMAL; tijdelijke hedge wordt gesloten",risk_reducing=True)
        return leg,Decision("RELEASE_PROTECTION",leg.side,role="HARVEST",reason="Portfolio is terug in NORMAL; protectionrol vrijgegeven",risk_reducing=True)
    if not config.protection_enabled or mode not in {"DEFENSIVE","EMERGENCY"}:return None
    cap=portfolio.equity*config.max_net_exposure_ratio;net=portfolio.long_exposure-portfolio.short_exposure
    if abs(net)<=cap:return None
    if portfolio.margin_ratio>=config.emergency_margin_ratio:
        overweight="LONG" if net>0 else "SHORT";candidate=next((x for x in owned if x.side==overweight),None)
        if not candidate:return None
        amount=min(abs(net)-cap,candidate.quantity*candidate.weighted_entry*.25)
        return candidate,Decision("EMERGENCY_REDUCE",overweight,notional=max(0,amount),role=candidate.role,
            reason="EMERGENCY: protection kan niet veilig groeien; netto exposure gecontroleerd reduceren",risk_reducing=True)
    # Normal portfolio imbalance never enlarges an unrelated symbol. Any new
    # hedge must be selected by same_pair_protection_decision for the exact
    # endangered position. Emergency reduction remains available above.
    return None

def update_owned_after_open(leg:OwnedLeg,*,quantity:float,price:float,intent_id:str,is_dca:bool)->OwnedLeg:
    total=leg.quantity+quantity
    average=(leg.quantity*leg.weighted_entry+quantity*price)/total if total>0 else 0
    return replace(leg,quantity=total,weighted_entry=average,dca_count=leg.dca_count+(1 if is_dca else 0),
        intent_ids=tuple(dict.fromkeys((*leg.intent_ids,intent_id))))

def enrich_confirmed_costs(owned:list[OwnedLeg],trades:list[dict[str,Any]],income:list[dict[str,Any]])->list[OwnedLeg]:
    result=[]
    for leg in owned:
        relevant=[x for x in trades if str(x.get("symbol","")).upper()==leg.symbol and str(x.get("positionSide","")).upper()==leg.side and int(number(x.get("time")))>=leg.created_at_ms]
        fees=sum(abs(number(x.get("commission"))) for x in relevant)
        realized=sum(number(x.get("realizedPnl")) for x in relevant)
        funding=sum(number(x.get("income")) for x in income if str(x.get("symbol","")).upper()==leg.symbol
            and str(x.get("incomeType","")).upper()=="FUNDING_FEE" and str(x.get("positionSide","")).upper()==leg.side
            and int(number(x.get("time")))>=leg.created_at_ms)
        result.append(replace(leg,fees=fees,realized_pnl=realized,funding=funding))
    return result
