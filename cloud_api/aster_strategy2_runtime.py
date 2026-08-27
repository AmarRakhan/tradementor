"""Pure runtime projection/planning for persistent Aster Strategy 2 ticks."""
from __future__ import annotations
from dataclasses import asdict, replace
from datetime import datetime, timezone
import math
from typing import Any
from aster_strategy2 import Decision,LegState,PortfolioState,Strategy2Config,decide_leg,net_profit,risk_mode
from aster_strategy2_state import OwnedLeg,number

ASTER_ESTIMATED_CLOSE_FEE_RATE = .0005
STRATEGY2_SCHEDULER_LATE_SECONDS = 180
STRATEGY2_COST_EVIDENCE_MAX_AGE_SECONDS = 300

def cost_evidence_max_age_seconds(owned:list[OwnedLeg]|list[dict[str,Any]],*,
                                  maximum_symbols_per_tick:int=6,scheduler_interval_seconds:int=60,
                                  safety_intervals:int=2)->int:
    """Scale freshness to one complete, rate-bounded symbol rotation.

    Changed symbols still jump to the front of the refresh queue.  Unchanged
    symbols rotate oldest-first, so the bound is deterministic for 68 and 100
    legs without increasing Aster request pressure.
    """
    symbols={str(item.symbol if isinstance(item,OwnedLeg) else item.get("symbol","")).upper()
        for item in owned if str(item.symbol if isinstance(item,OwnedLeg) else item.get("symbol",""))}
    rotations=math.ceil(len(symbols)/max(1,int(maximum_symbols_per_tick))) if symbols else 1
    return max(STRATEGY2_COST_EVIDENCE_MAX_AGE_SECONDS,
        (rotations+max(1,int(safety_intervals)))*max(1,int(scheduler_interval_seconds)))

def recover_audited_ownership(*,persisted:list[OwnedLeg],positions:list[dict[str,Any]],
                              audit_events:list[dict[str,Any]],fills:list[dict[str,Any]],
                              excluded_keys:set[tuple[str,str]]|None=None,
                              strategy_id:str="aster-strategy-2",engine_type:str="strategy2",
                              require_event_strategy:bool=False)->tuple[list[OwnedLeg],list[dict[str,Any]]]:
    """Recover a missing leg only when both our audit and a matching Aster fill prove ownership."""
    result=list(persisted);known={(x.symbol,x.side) for x in result};recovered=[];active=active_position_map(positions)
    excluded_keys=excluded_keys or set()
    opens=[]
    proven_open_events={"INITIAL_OPEN_LEG","OPEN_LEG","OPEN_PROTECTION"}
    for event in audit_events:
        if str(event.get("event","")).upper() not in proven_open_events:continue
        event_strategy=str(event.get("strategyId",event.get("strategy_id",""))).strip()
        if require_event_strategy and event_strategy!=strategy_id:continue
        if event_strategy and event_strategy!=strategy_id:continue
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
        leg=OwnedLeg(strategy_id=strategy_id,engine_type=engine_type,symbol=symbol,side=side,
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

def current_cycle_fill_ids(*,leg:OwnedLeg,fills:list[dict[str,Any]])->tuple[str,...]:
    """Prove the fill IDs belonging to the currently open hedge-mode cycle.

    History is replayed from flat. A truncated, malformed or internally
    inconsistent history never produces evidence. Older completed cycles are
    discarded only after their replayed quantity returns exactly to zero.
    """
    matching=[]
    for row in fills:
        if str(row.get("symbol","")).upper()!=leg.symbol or str(row.get("positionSide","")).upper()!=leg.side:
            continue
        fill_id=str(row.get("id",row.get("tradeId",""))).strip()
        side=str(row.get("side","")).upper()
        quantity=number(row.get("qty",row.get("quantity")))
        price=number(row.get("price"));timestamp=int(number(row.get("time",row.get("timestamp"))))
        if not fill_id or side not in {"BUY","SELL"} or quantity<=0 or price<=0 or timestamp<=0:
            return ()
        matching.append((timestamp,fill_id,side,quantity))
    matching.sort(key=lambda item:(item[0],item[1]))
    if not matching:return ()
    exposure=0.0;cycle=[];seen=set()
    for _,fill_id,side,quantity in matching:
        if fill_id in seen:return ()
        seen.add(fill_id)
        increases=(leg.side=="LONG" and side=="BUY") or (leg.side=="SHORT" and side=="SELL")
        updated=exposure+(quantity if increases else -quantity)
        tolerance=max(1e-8,abs(exposure)*1e-7,abs(quantity)*1e-7)
        if updated < -tolerance:return ()
        exposure=0.0 if abs(updated)<=tolerance else updated
        cycle.append(fill_id)
        if exposure==0.0:cycle=[]
    final_tolerance=max(1e-8,abs(leg.quantity)*1e-7)
    if not math.isclose(exposure,leg.quantity,rel_tol=1e-7,abs_tol=final_tolerance):return ()
    return tuple(cycle)

def transfer_active_ownership_to_strategy2(*,positions:list[dict[str,Any]],strategy2_legs:list[OwnedLeg],
                                           strategy3_legs:list[OwnedLeg]|None=None,
                                           strategy1_legs:list[OwnedLeg]|None=None
                                           )->tuple[list[OwnedLeg],list[tuple[str,str]],list[str]]:
    """Build one exclusive Strategy-2 ownership row for every active position.

    The exchange remains authoritative for side, quantity and entry price.  A
    transfer is allowed only when an existing strategy record proves the same
    symbol/side.  Strategy 2 wins collisions, followed by Strategy 3 and then
    Strategy 1. Duplicate claims inside one source are rejected.  This pure
    function never sends orders and never mutates persisted state.
    """
    active=active_position_map(positions)
    # A reliable empty exchange snapshot is authoritative: there is no active
    # ownership to transfer. Historical/duplicate stale claims must not keep a
    # flat account in RECONCILING; the caller will persist the empty result.
    if not active:
        return [],[],[]
    sources=(('strategy2',strategy2_legs),('strategy3',strategy3_legs or []),('strategy1',strategy1_legs or []))
    indexed:dict[str,dict[tuple[str,str],OwnedLeg]]={};errors=[]
    for name,legs in sources:
        by_key:dict[tuple[str,str],OwnedLeg]={}
        for leg in legs:
            key=(str(leg.symbol).upper(),str(leg.side).upper())
            if key in by_key:
                errors.append(f"duplicate-{name}-ownership")
            else:
                by_key[key]=leg
        indexed[name]=by_key
    transferred=[];missing=[]
    for key,row in sorted(active.items()):
        source=next((indexed[name][key] for name,_ in sources if key in indexed[name]),None)
        quantity=abs(number(row.get('positionAmt')));entry=number(row.get('entryPrice'))
        if source is None:
            missing.append(key);continue
        if quantity<=0 or entry<=0:
            errors.append('invalid-exchange-position');continue
        transferred.append(replace(source,strategy_id='aster-strategy-2',engine_type='strategy2',
            symbol=key[0],side=key[1],quantity=quantity,weighted_entry=entry,
            cycle_id=source.cycle_id or f"ownership-transfer-{key[0].lower()}-{key[1].lower()}"))
    if len({(leg.symbol,leg.side) for leg in transferred})!=len(transferred):
        errors.append('duplicate-transfer-output')
    return transferred,missing,sorted(set(errors))

def isolate_unproven_ownership(*,persisted:list[OwnedLeg],positions:list[dict[str,Any]]) -> tuple[list[OwnedLeg],set[tuple[str,str]],set[tuple[str,str]]]:
    """Keep management scoped to exchange-confirmed owned legs.

    Exchange-only positions remain unclaimed. Persisted legs absent from a
    reliable exchange snapshot are quarantined instead of blocking management
    of every other proven leg. This pure helper never mutates state or orders.
    """
    active_keys=set(active_position_map(positions))
    persisted_keys={(leg.symbol,leg.side) for leg in persisted}
    proven=[leg for leg in persisted if (leg.symbol,leg.side) in active_keys]
    return proven,active_keys-persisted_keys,persisted_keys-active_keys

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
    available=number(account.get("availableBalance"))
    return PortfolioState(equity,max(hwm,equity),maint/equity if equity>0 else 1.0,long_exposure,short_exposure,strategy_exposure,
        exchange_reliable,ownership_reliable,open_orders_unknown,strategy_margin,available)

def initial_build_high_water_mark(*,account:dict[str,Any],positions:list[dict[str,Any]],owned:list[OwnedLeg],
                                  previous_hwm:float,initial_build_complete:bool)->float:
    """Choose the drawdown baseline for a Strategy-2 entry cycle.

    A confirmed-flat, not-yet-built cycle is a fresh entry cycle. It must not
    inherit drawdown from a previous, already closed portfolio. Any active
    exchange position, proven owned leg, or completed build keeps the prior
    high-water mark so protective behaviour cannot be weakened during recovery.
    """
    wallet=number(account.get("totalWalletBalance"));unrealized=number(account.get("totalUnrealizedProfit"))
    equity=number(account.get("totalMarginBalance")) or wallet+unrealized
    active_positions=any(abs(number(row.get("positionAmt")))>0 for row in positions)
    if equity>0 and not initial_build_complete and not owned and not active_positions:
        return equity
    return max(previous_hwm,equity)

def leg_projection(owned:OwnedLeg,row:dict[str,Any])->LegState:
    mark=number(row.get("markPrice"));qty=abs(number(row.get("positionAmt")));entry=number(row.get("entryPrice")) or owned.weighted_entry
    notional=qty*mark
    return LegState(owned.side,owned.cycle_id,notional,entry,mark,owned.dca_count,owned.realized_pnl,
        number(row.get("unRealizedProfit",row.get("unrealizedProfit"))),owned.fees,owned.funding,owned.role,owned.config_version,"HARVEST")

def estimated_close_fee(row:dict[str,Any])->float:
    notional=abs(number(row.get("notional",row.get("notionalUsd"))))
    if notional<=0:
        notional=abs(number(row.get("positionAmt",row.get("quantity"))))*number(row.get("markPrice"))
    return notional*ASTER_ESTIMATED_CLOSE_FEE_RATE

def most_urgent_profitable_owned(config:Strategy2Config,owned:list[OwnedLeg],positions:list[dict[str,Any]])->OwnedLeg|None:
    """Pick the profitable owned leg furthest above its net TP threshold."""
    pos=active_position_map(positions);candidates=[]
    for leg in owned:
        if config.trading_mode=="focus" and str(leg.role).upper().startswith("FOCUS"):continue
        row=pos.get((leg.symbol,leg.side))
        if not row:continue
        gross=number(row.get("unRealizedProfit",row.get("unrealizedProfit")))
        projection=leg_projection(leg,row)
        surplus=net_profit(projection,estimated_close_fee(row))-projection.size*config.take_profit
        if gross>0:candidates.append((surplus,gross,leg))
    candidates.sort(key=lambda item:(item[0],item[1]),reverse=True)
    return candidates[0][2] if candidates else None

def next_management_decision(config:Strategy2Config,portfolio:PortfolioState,owned:list[OwnedLeg],positions:list[dict[str,Any]],
                             excluded_dca:set[tuple[str,str]]|None=None,
                             excluded_actions:set[tuple[str,str,str]]|None=None)->tuple[OwnedLeg,Decision]|None:
    pos=active_position_map(positions);rank={"FULL_TP":0,"PARTIAL_TP":0,"ASSIGN_PROTECTION":1,"ADD_DCA":2,"HOLD":9}
    excluded_dca=excluded_dca or set()
    excluded_actions=excluded_actions or set()
    choices=[]
    for item in owned:
        if config.trading_mode=="focus" and str(item.role).upper().startswith("FOCUS"):continue
        row=pos.get((item.symbol,item.side))
        if not row:continue
        close_fee=estimated_close_fee(row);projected=leg_projection(item,row)
        decision=decide_leg(config,projected,portfolio,estimated_close_fee=close_fee)
        if decision.kind=="ADD_DCA" and (item.symbol,item.side) in excluded_dca:
            continue
        if (item.symbol,item.side,decision.kind) in excluded_actions:
            continue
        tp_surplus=net_profit(projected,close_fee)-projected.size*config.take_profit
        choices.append((rank.get(decision.kind,8),-tp_surplus,item,decision))
    if not choices:return None
    choices.sort(key=lambda x:(x[0],x[1]))
    return (choices[0][2],choices[0][3]) if choices[0][3].kind!="HOLD" else None

def next_dca_decision(config:Strategy2Config,portfolio:PortfolioState,owned:list[OwnedLeg],positions:list[dict[str,Any]],
                      excluded_dca:set[tuple[str,str]]|None=None,
                      excluded_actions:set[tuple[str,str,str]]|None=None)->tuple[OwnedLeg,Decision]|None:
    """Return the most urgent proven DCA without letting seat refill suppress position management.

    Existing legs are evaluated with the normal Strategy-2 safety rules. TP still
    has separate higher priority in the caller; EMERGENCY, budget, ownership and
    open-order gates remain authoritative.
    """
    pos=active_position_map(positions);excluded_dca=excluded_dca or set();excluded_actions=excluded_actions or set();choices=[]
    for item in owned:
        if config.trading_mode=="focus" and str(item.role).upper().startswith("FOCUS"):continue
        row=pos.get((item.symbol,item.side))
        if not row or (item.symbol,item.side) in excluded_dca:continue
        projected=leg_projection(item,row);decision=decide_leg(config,projected,portfolio,estimated_close_fee=estimated_close_fee(row))
        if decision.kind!='ADD_DCA' or (item.symbol,item.side,decision.kind) in excluded_actions:continue
        deviation=abs(projected.current_price/projected.weighted_entry-1) if projected.weighted_entry>0 else 0
        choices.append((deviation,item,decision))
    if not choices:return None
    choices.sort(key=lambda x:x[0],reverse=True)
    return choices[0][1],choices[0][2]


def scanner_allowed(config:Strategy2Config,portfolio:PortfolioState,owned:list[OwnedLeg])->bool:
    # Focus deliberately suppresses normal Multi-pair seat refill. Existing owned
    # positions continue through the unchanged management path.
    if config.trading_mode=="focus":
        return False
    new_pair_margin=config.base_notional/max(1,config.leverage)
    # Seat refill is a Strategy-2 capacity invariant. Account-wide risk/recovery
    # modes may change management decisions, but may not strand configured empty
    # seats. The authoritative available-balance buffer and per-contract Aster
    # capacity/leverage checks below the scanner remain the hard execution gates.
    return len(owned)<config.maximum_pairs and portfolio.available_balance>=new_pair_margin*1.05

def balanced_entry_targets(total:int)->tuple[int,int]:
    """Return the closest possible LONG/SHORT split for a total position cap."""
    total=max(1,int(total))
    return ((total+1)//2,total//2)

def harvest_counts(owned:list[OwnedLeg])->tuple[int,int]:
    # Seat accounting counts every live Strategy-2 LONG/SHORT leg.
    return (sum(1 for x in owned if x.side=="LONG"),sum(1 for x in owned if x.side=="SHORT"))

def next_balanced_entry_side(owned:list[OwnedLeg],total:int,long_target:int|None=None,short_target:int|None=None)->str|None:
    if long_target is None or short_target is None: long_target,short_target=balanced_entry_targets(total)
    long_count,short_count=harvest_counts(owned)
    if long_count>=long_target and short_count>=short_target:return None
    if long_count<short_count and long_count<long_target:return "LONG"
    if short_count<long_count and short_count<short_target:return "SHORT"
    if long_count<long_target:return "LONG"
    return "SHORT" if short_count<short_target else None

def entry_order_limit(initial_build_complete:bool,owned:list[OwnedLeg],total:int,long_target:int|None=None,short_target:int|None=None)->int:
    """Expose the complete seat shortage; queue budget limits actual sends.

    ``initial_build_complete`` remains part of the public signature for stored
    runtime compatibility, but a later refill can have more than one missing
    seat.  Collapsing that shortage to one prevented a scan from using the
    account-scoped order budget that already safely caps exchange requests.
    """
    if long_target is None or short_target is None: long_target,short_target=balanced_entry_targets(total)
    long_count,short_count=harvest_counts(owned)
    return max(0,max(0,long_target-long_count)+max(0,short_target-short_count))

def queued_entry_order_limit(initial_build_complete:bool,owned:list[OwnedLeg],total:int,
                             *,orders_used:int=0,maximum_orders:int=15,long_target:int|None=None,short_target:int|None=None)->int:
    """Cap the complete seat shortage to the remaining account-scan budget."""
    return min(entry_order_limit(initial_build_complete,owned,total,long_target,short_target),
               max(0,int(maximum_orders)-max(0,int(orders_used))))

def management_preempts_initial_build(config:Strategy2Config,owned:list[OwnedLeg],decision:Decision)->bool:
    """Existing-position management always precedes initial entry building.

    A balanced start target controls only *new* entries. It must never postpone
    TP, DCA, recovery or protection for an already owned position. Otherwise a
    pair/risk limit can leave the startup incomplete forever while profitable
    legs remain unmanaged.
    """
    return decision.kind != "HOLD"

def same_pair_protection_decision(config:Strategy2Config,portfolio:PortfolioState,owned:list[OwnedLeg],positions:list[dict[str,Any]],
                                  blocked_actions:set[tuple[str,str,str]]|None=None)->tuple[OwnedLeg,Decision]|None:
    """Open an opposite same-symbol leg only after risk has escalated.

    Normal harvest entries never create a mandatory same-pair hedge. Protection
    starts at CAUTION and requires an actually losing, DCA-active leg (or a
    stronger portfolio risk mode), so a tiny spread loss cannot trigger it.
    """
    mode=risk_mode(config,portfolio)
    if not config.protection_enabled or mode=="NORMAL":return None
    pos=active_position_map(positions);keys={(x.symbol,x.side) for x in owned};blocked_actions=blocked_actions or set()
    candidates=[]
    for leg in owned:
        if config.trading_mode=="focus" and str(leg.role).upper().startswith("FOCUS"):continue
        if leg.role=="PROTECTION":continue
        row=pos.get((leg.symbol,leg.side));opposite="SHORT" if leg.side=="LONG" else "LONG"
        if (leg.symbol,leg.side,"OPEN_PROTECTION") in blocked_actions:continue
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
    managed=[x for x in owned if not (config.trading_mode=="focus" and str(x.role).upper().startswith("FOCUS"))]
    protected=[x for x in managed if x.role in {"PROTECTION","HARVEST_PROTECTION"}]
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

def enrich_confirmed_costs(owned:list[OwnedLeg],trades:list[dict[str,Any]],income:list[dict[str,Any]],*,
                           refreshed_symbols:set[str]|None=None,checked_at_ms:int=0)->list[OwnedLeg]:
    result=[]
    refreshed_symbols=refreshed_symbols or {x.symbol for x in owned}
    for leg in owned:
        if leg.symbol not in refreshed_symbols:
            result.append(leg);continue
        relevant=[x for x in trades if str(x.get("symbol","")).upper()==leg.symbol and str(x.get("positionSide","")).upper()==leg.side and int(number(x.get("time")))>=leg.created_at_ms]
        fees=sum(abs(number(x.get("commission"))) for x in relevant) if relevant else leg.fees
        realized=sum(number(x.get("realizedPnl")) for x in relevant) if relevant else leg.realized_pnl
        funding_rows=[x for x in income if str(x.get("symbol","")).upper()==leg.symbol
            and str(x.get("incomeType","")).upper()=="FUNDING_FEE" and str(x.get("positionSide","")).upper()==leg.side
            and int(number(x.get("time")))>=leg.created_at_ms]
        funding=sum(number(x.get("income")) for x in funding_rows) if funding_rows else leg.funding
        result.append(replace(leg,fees=fees,realized_pnl=realized,funding=funding,costs_updated_at_ms=checked_at_ms))
    return result

def scheduler_status(state:dict[str,Any],*,now:datetime|None=None)->dict[str,Any]:
    now=now or datetime.now(timezone.utc);stamp=state.get("lastTickAt")
    if not isinstance(stamp,datetime):
        return {"status":"STALE","lastTickAt":stamp,"ageSeconds":None,"warning":"Strategy-2-scheduler heeft nog geen bewezen heartbeat"}
    if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
    age=max(0,(now-stamp.astimezone(timezone.utc)).total_seconds());stale=age>STRATEGY2_SCHEDULER_LATE_SECONDS
    return {"status":"STALE" if stale else "HEALTHY","lastTickAt":stamp,"ageSeconds":round(age,1),
        "warning":f"Strategy-2-scheduler is {int(age)} seconden stil" if stale else ""}

def strategy2_position_tp_contract(*,row:dict[str,Any],owned:OwnedLeg|None,config:Strategy2Config,
                                   state:dict[str,Any],portfolio:PortfolioState|None,
                                   now:datetime|None=None)->dict[str,Any]:
    """Server-only TP evidence. Missing proof is explicit and never inferred by the browser."""
    now=now or datetime.now(timezone.utc);scheduler=scheduler_status(state,now=now)
    notional=abs(number(row.get("notionalUsd",row.get("notional"))))
    if notional<=0:notional=abs(number(row.get("quantity",row.get("positionAmt"))))*number(row.get("markPrice"))
    target=notional*config.take_profit;close_fee=estimated_close_fee(row)
    ownership=bool(owned and owned.strategy_id=="aster-strategy-2" and owned.engine_type=="strategy2")
    evidence_age=None
    if owned and owned.costs_updated_at_ms:evidence_age=max(0,now.timestamp()-owned.costs_updated_at_ms/1000)
    evidence_limit=cost_evidence_max_age_seconds(
        state.get("ownedLegs") if isinstance(state.get("ownedLegs"),list) else ([owned] if owned else []))
    costs_fresh=evidence_age is not None and evidence_age<=evidence_limit
    block=""
    if not ownership:block="Geen bewezen Strategy-2-ownership"
    elif not costs_fresh:block="Fees en funding zijn niet recent genoeg door Aster bevestigd"
    reliable=not bool(block)
    gross=number(row.get("unrealizedPnl",row.get("unRealizedProfit")))
    net=(gross+(owned.funding if owned else 0)-(owned.fees if owned else 0)-close_fee) if reliable else None
    status="Niet betrouwbaar te bepalen";decision_kind="HOLD"
    if reliable:
        status="TP bereikt" if net is not None and net>=target else "TP nog niet bereikt"
        if portfolio is not None and owned is not None:
            projection=LegState(owned.side,owned.cycle_id,notional,owned.weighted_entry,number(row.get("markPrice")),
                owned.dca_count,owned.realized_pnl,gross,owned.fees,owned.funding,owned.role,owned.config_version,"HARVEST")
            decision=decide_leg(config,projection,portfolio,estimated_close_fee=close_fee)
            decision_kind=decision.kind
            block=decision.reason
        elif portfolio is None:
            block=("Netto TP is betrouwbaar bereikt, maar protection kan niet worden beoordeeld omdat de actuele "
                "Strategy-2-portfoliostaat ontbreekt" if status=="TP bereikt" else
                "TP nog niet bereikt; ontbrekende portfoliostaat blokkeert alleen protection")
    if reliable and status=="TP bereikt":
        if config.mode!="live":block="TP bereikt, maar de opgeslagen Strategy-2-modus is paper"
        elif not bool(state.get("monitor")):block="TP bereikt, maar Strategy-2-monitoring staat uit"
        elif not bool(state.get("canaryValidated")):
            block="TP bereikt, maar canaryValidated is niet volledig bewezen"
        elif state.get("runtimeEnabled") is False:block="TP bereikt, maar de centrale Strategy-2-runtimepoort staat uit"
        elif str(state.get("phase","")).upper() in {"DATA_HOLD","RECONCILING","CANARY_HOLD"}:
            block=str(state.get("lastReason") or f"Strategy 2 staat in {state.get('phase')}")
    progress=(net/target*100) if reliable and net is not None and target>0 else None
    evaluated_at=(datetime.fromtimestamp(owned.costs_updated_at_ms/1000,tz=timezone.utc).isoformat()
        if owned and owned.costs_updated_at_ms else None)
    phase=str(state.get("phase","UNKNOWN"))
    return {"netProfitUsd":net,"takeProfitTargetUsd":target if ownership else None,
        "takeProfitPercent":config.take_profit*100 if ownership else None,
        "progressPercent":progress,"status":status,"evaluatedAt":evaluated_at,"blockReason":block,
        "scheduler":scheduler,"ownershipProven":ownership,"paidFeesUsd":owned.fees if reliable and owned else None,
        "fundingUsd":owned.funding if reliable and owned else None,"estimatedCloseFeeUsd":close_fee if reliable else None,
        "costEvidenceAgeSeconds":round(evidence_age,1) if evidence_age is not None else None,"decision":decision_kind,
        "phase":phase,"protection":{"role":owned.role if ownership and owned else None,
            "active":bool(ownership and owned and owned.role in {"PROTECTION","HARVEST_PROTECTION"})},
        "trailing":{"enabled":False,"active":False,"peakReturnPercent":None}}
