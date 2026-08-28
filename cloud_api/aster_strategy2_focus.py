"""Pure Strategy-2 Focus / Coin van het moment domain engine.

No network client is imported here. Shadow and a future live adapter must use
this exact planner. Monetary order amounts are leveraged order-notional USD,
matching Strategy 2 ``baseNotional``. Focus budget is also notional USD;
required/available margin are kept separate and equal notional/leverage.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from statistics import fmean, pstdev
from typing import Any, Literal
import math, uuid

FocusSelectionMode=Literal["automatic","manual"]
FocusSizingMode=Literal["fixed_usd","equity_pct"]
FocusDcaMode=Literal["fixed","progressive","custom"]
FocusActionKind=Literal["HOLD","OPEN","DCA","PARTIAL_TP","CLOSE"]
MAX_FOCUS_DCA=float("inf")
DEFAULT_FOCUS_DCA=5

def _finite(value:Any,default:float=0.0)->float:
    try: result=float(value)
    except (TypeError,ValueError): return default
    return result if math.isfinite(result) else default

def _ema(values:list[float],period:int)->float:
    if not values:return 0.0
    if len(values)<period:return values[-1]
    result=fmean(values[:period]);alpha=2.0/(period+1.0)
    for value in values[period:]:result=value*alpha+result*(1-alpha)
    return result

@dataclass(frozen=True)
class FocusMarket:
    symbol:str;price:float;change_24h_pct:float;quote_volume_24h:float
    liquidity_score:float=1.0;closes:tuple[float,...]=()

@dataclass(frozen=True)
class FocusRankingRow:
    symbol:str;price:float;change_24h_pct:float;quote_volume_24h:float;liquidity_score:float
    ema20:float;ema50:float;momentum_pct:float;bollinger_middle:float;bollinger_upper:float;bollinger_lower:float
    distance_middle_pct:float;distance_upper_pct:float;pullback_pct:float;overextended:bool;eligible:bool
    score:float;reason:str;rejection_reason:str=""
    def public_dict(self)->dict[str,Any]:return asdict(self)

@dataclass(frozen=True)
class FocusExposurePreview:
    first_order_notional:float;dca_notionals:tuple[float,...];total_max_order_notional:float;required_margin:float
    max_leveraged_exposure:float;portfolio_margin_pct:float;remaining_free_margin:float;worst_case_average_entry:float
    dca_trigger_prices:tuple[float,...];dca_trigger_drops_pct:tuple[float,...];total_drop_to_last_dca_pct:float
    focus_budget_notional:float;focus_budget_remaining_notional:float;available_margin:float;safe:bool;status:str
    def public_dict(self)->dict[str,Any]:
        value=asdict(self);value["dca_notionals"]=list(self.dca_notionals);value["dca_trigger_prices"]=list(self.dca_trigger_prices);value["dca_trigger_drops_pct"]=list(self.dca_trigger_drops_pct);return value

@dataclass(frozen=True)
class FocusState:
    active_pair:str="";cycle_id:str="";cycle_status:str="Pair selecteren";opened_at_ms:int=0
    original_entry:float=0.0;weighted_entry:float=0.0;total_quantity:float=0.0;total_notional:float=0.0;used_margin:float=0.0
    dca_count:int=0;next_dca_trigger:float=0.0;highest_price:float=0.0;highest_profit_pct:float=0.0
    trailing_active:bool=False;trailing_floor:float=0.0;partials_taken:tuple[int,...]=();realized_pnl:float=0.0
    theoretical_portfolio_value:float=0.0;focus_budget_used:float=0.0;last_selection_reason:str="";last_action:str="";last_reason:str=""
    def public_dict(self)->dict[str,Any]:
        value=asdict(self);value["partials_taken"]=list(self.partials_taken);return value

@dataclass(frozen=True)
class FocusDecision:
    kind:FocusActionKind;symbol:str="";side:Literal["LONG"]="LONG";notional:float=0.0;close_fraction:float=0.0
    reason:str="";status:str="";risk_reducing:bool=False
    def public_dict(self)->dict[str,Any]:return asdict(self)

def focus_order_notional(*,sizing_mode:FocusSizingMode,fixed_usd:float,equity_pct:float,equity:float,max_start_order_usd:float)->float:
    value=max(0.0,equity)*max(0.0,equity_pct) if sizing_mode=="equity_pct" else max(0.0,fixed_usd)
    return min(value,max_start_order_usd) if max_start_order_usd>0 else value

def dca_notional_sequence(*,amount:float,multiplier:float,count:int,amount_mode:str="multiplier",increment:float=0.0)->tuple[float,...]:
    count=max(0,int(count));amount=max(0.0,float(amount));multiplier=max(0.0,float(multiplier));increment=max(0.0,float(increment))
    if amount_mode=="linear": return tuple(amount+increment*index for index in range(count))
    return tuple(amount*(multiplier**index) for index in range(count))

def dca_drop_sequence(*,distance_pct:float,count:int,mode:FocusDcaMode="fixed",custom_levels:tuple[float,...]=())->tuple[float,...]:
    count=max(0,int(count));distance=max(0.0,float(distance_pct))
    if mode=="custom": return tuple(max(0.0,float(x)) for x in custom_levels[:count])
    return tuple(distance*i*(i+1)/2 for i in range(1,count+1)) if mode=="progressive" else tuple(distance*i for i in range(1,count+1))

def weighted_average_entry(start_price:float,start_notional:float,trigger_prices:tuple[float,...],dca_notionals:tuple[float,...])->float:
    if start_price<=0 or start_notional<=0:return 0.0
    qty=start_notional/start_price;total=start_notional
    for price,notional in zip(trigger_prices,dca_notionals):
        if price>0 and notional>0:qty+=notional/price;total+=notional
    return total/qty if qty>0 else 0.0

def exposure_preview(*,entry_price:float,first_order_notional:float,dca_enabled:bool,dca_amount:float,dca_multiplier:float,max_dca:int,
                     dca_distance_pct:float,dca_mode:FocusDcaMode,leverage:int,equity:float,available_margin:float,focus_budget:float)->FocusExposurePreview:
    leverage=max(1,int(leverage));count=max(0,int(max_dca)) if dca_enabled else 0
    notionals=dca_notional_sequence(amount=dca_amount,multiplier=dca_multiplier,count=count)
    drops=dca_drop_sequence(distance_pct=dca_distance_pct,count=count,mode=dca_mode)
    prices=tuple(max(1e-8,entry_price*(1-drop)) for drop in drops);total=max(0.0,first_order_notional)+sum(notionals)
    margin=total/leverage;budget=max(0.0,focus_budget);available=max(0.0,available_margin)
    safe=total<=budget+1e-9 and margin<=available+1e-9
    status="budget overschreden" if total>budget+1e-9 else "onvoldoende beschikbare margin" if margin>available+1e-9 else "veilig"
    return FocusExposurePreview(max(0.0,first_order_notional),notionals,total,margin,total,margin/equity if equity>0 else 0.0,
        max(0.0,available-margin),weighted_average_entry(entry_price,first_order_notional,prices,notionals),prices,drops,drops[-1] if drops else 0.0,
        budget,max(0.0,budget-total),available,safe,status)

def _market_indicators(market:FocusMarket)->FocusRankingRow:
    values=[x for x in (_finite(v) for v in market.closes) if x>0];price=_finite(market.price)
    if len(values)>=20:
        window=values[-20:];middle=fmean(window);dev=pstdev(window);upper,lower=middle+2*dev,middle-2*dev
    else:middle=upper=lower=price
    ema20=_ema(values,20) if values else price;ema50=_ema(values,50) if values else price
    momentum=(values[-1]/values[-6]-1) if len(values)>=6 and values[-6]>0 else 0.0
    recent_high=max(values[-10:]) if values else price;pullback=max(0.0,1-price/recent_high) if recent_high>0 else 0.0
    distance_middle=price/middle-1 if middle>0 else 0.0;distance_upper=price/upper-1 if upper>0 else 0.0
    overextended=upper>0 and price>upper*1.01;liquid=market.quote_volume_24h>0 and market.liquidity_score>0;uptrend=ema20>=ema50
    technical=(8 if uptrend else -8)+max(-6,min(6,momentum*100))+(6 if -.03<=distance_middle<=.01 else 2 if distance_middle<.04 else -3)
    technical+=5 if .005<=pullback<=.08 else 0;technical-=22 if overextended else 0
    technical+=max(0,min(4,math.log10(max(1,market.quote_volume_24h))-5))+max(0,min(3,market.liquidity_score*3))
    eligible=liquid and market.change_24h_pct>0 and price>0;reason="24h stijger"
    if uptrend:reason+=" · EMA20 boven EMA50"
    if -.03<=distance_middle<=.01:reason+=" · gunstige pullback rond BB-middle"
    if overextended:reason+=" · boven upper band/overstrekt"
    rejection="" if eligible else "onvoldoende volume/liquiditeit" if not liquid else "geen positieve 24h stijging" if market.change_24h_pct<=0 else "ongeldige prijs"
    return FocusRankingRow(market.symbol.upper(),price,market.change_24h_pct,market.quote_volume_24h,market.liquidity_score,ema20,ema50,momentum,middle,upper,lower,distance_middle,distance_upper,pullback,overextended,eligible,market.change_24h_pct*100+technical,reason,rejection)

def rank_focus_pairs(markets:list[FocusMarket],*,minimum_quote_volume:float=0.0,minimum_liquidity_score:float=0.0)->list[FocusRankingRow]:
    rows=[]
    for market in markets:
        row=_market_indicators(market)
        if row.quote_volume_24h<minimum_quote_volume:row=replace(row,eligible=False,rejection_reason="minimum 24h quote-volume niet gehaald")
        if row.liquidity_score<minimum_liquidity_score:row=replace(row,eligible=False,rejection_reason="minimum liquidity-score niet gehaald")
        rows.append(row)
    rows.sort(key=lambda r:r.change_24h_pct,reverse=True);leaders=[r for r in rows if r.eligible][:10];leaders.sort(key=lambda r:(r.score,r.change_24h_pct),reverse=True)
    leader_symbols={r.symbol for r in leaders};return leaders+[r for r in rows if r.symbol not in leader_symbols]

def select_focus_pair(markets:list[FocusMarket],*,selection_mode:FocusSelectionMode="automatic",manual_pair:str="",active_pair:str="",cycle_open:bool=False,
                      minimum_quote_volume:float=0.0,minimum_liquidity_score:float=0.0)->tuple[FocusRankingRow|None,list[FocusRankingRow],str]:
    ranking=rank_focus_pairs(markets,minimum_quote_volume=minimum_quote_volume,minimum_liquidity_score=minimum_liquidity_score)
    if cycle_open and active_pair:
        return next((r for r in ranking if r.symbol==active_pair.upper()),None),ranking,"actieve cyclus behouden; geen pair-hopping"
    if selection_mode=="manual":
        selected=next((r for r in ranking if r.symbol==manual_pair.upper().strip()),None)
        return selected,ranking,"handmatige Focus-selectie" if selected else "handmatige pair niet beschikbaar op Aster"
    selected=next((r for r in ranking if r.eligible),None);return selected,ranking,selected.reason if selected else "geen geschikte LONG-kandidaat"

def next_dca_trigger(*,original_entry:float,dca_count:int,max_dca:int,distance_pct:float,mode:FocusDcaMode,custom_levels:tuple[float,...]=(),unlimited:bool=False)->float:
    if original_entry<=0:return 0.0
    if unlimited:
        if mode!="fixed" or not 0<distance_pct<1:return 0.0
        # Geometric spacing keeps a next trigger available indefinitely instead
        # of a linear original-entry ladder mathematically reaching zero.
        return original_entry*((1-distance_pct)**(max(0,int(dca_count))+1))
    if dca_count>=max_dca:return 0.0
    drops=dca_drop_sequence(distance_pct=distance_pct,count=max_dca,mode=mode,custom_levels=custom_levels)
    return max(0.0,original_entry*(1-drops[dca_count])) if dca_count<len(drops) else 0.0

def can_add_focus_order(*,proposed_notional:float,leverage:int,focus_budget_used:float,focus_budget:float,strategy_margin_used:float,strategy_budget:float,
                        available_margin:float,exchange_max_notional_remaining:float,liquidation_distance_pct:float,minimum_liquidation_distance_pct:float,
                        maintenance_margin_ratio:float,maximum_maintenance_margin_ratio:float)->tuple[bool,str]:
    margin=proposed_notional/max(1,leverage)
    if proposed_notional<=0:return False,"ongeldige DCA-order"
    if focus_budget_used+proposed_notional>focus_budget+1e-9:return False,"Focus-budget bereikt"
    if strategy_margin_used+margin>strategy_budget+1e-9:return False,"Strategy-2-budget bereikt"
    if margin>available_margin+1e-9:return False,"onvoldoende beschikbare margin"
    if proposed_notional>exchange_max_notional_remaining+1e-9:return False,"exchange max-notional bereikt"
    if liquidation_distance_pct<minimum_liquidation_distance_pct:return False,"liquidation-distance te klein"
    if maintenance_margin_ratio>maximum_maintenance_margin_ratio:return False,"maintenance-margin grens bereikt"
    return True,"veilig"

def apply_focus_buy(state:FocusState,*,price:float,notional:float,leverage:int,timestamp_ms:int,is_dca:bool,reason:str="")->FocusState:
    if price<=0 or notional<=0:raise ValueError("Focus-fill vereist positieve prijs en notional")
    quantity=notional/price;total_qty=state.total_quantity+quantity;total_notional=state.total_notional+notional
    return replace(state,cycle_id=state.cycle_id or f"focus-{uuid.uuid4().hex}",opened_at_ms=state.opened_at_ms or timestamp_ms,
        original_entry=state.original_entry or price,weighted_entry=total_notional/total_qty,total_quantity=total_qty,total_notional=total_notional,
        used_margin=state.used_margin+notional/max(1,leverage),focus_budget_used=state.focus_budget_used+notional,dca_count=state.dca_count+(1 if is_dca else 0),
        highest_price=max(state.highest_price,price),cycle_status="Dip kopen" if is_dca else "Instap",last_action="DCA" if is_dca else "OPEN",last_reason=reason)

def focus_pnl_pct(state:FocusState,price:float)->float:return price/state.weighted_entry-1 if state.weighted_entry>0 else 0.0

def update_trailing(state:FocusState,*,price:float,activation_pct:float,trailing_distance_pct:float,minimum_profit_pct:float)->FocusState:
    if state.weighted_entry<=0 or price<=0:return state
    high=max(state.highest_price,price);high_profit=max(state.highest_profit_pct,high/state.weighted_entry-1);active=state.trailing_active or high_profit>=max(activation_pct,minimum_profit_pct)
    floor=max(state.trailing_floor,high*(1-trailing_distance_pct)) if active else state.trailing_floor
    return replace(state,highest_price=high,highest_profit_pct=high_profit,trailing_active=active,trailing_floor=floor,cycle_status="Trailing actief" if active else "Trend volgen")

def exit_decision(state:FocusState,*,price:float,minimum_profit_pct:float,trailing_activation_pct:float,trailing_distance_pct:float,
                  partial_tp_enabled:bool,first_partial_tp_pct:float,first_partial_close_pct:float,second_partial_tp_pct:float,second_partial_close_pct:float,
                  momentum_healthy:bool=True,bollinger_overextended_reversal:bool=False)->tuple[FocusState,FocusDecision]:
    updated=update_trailing(state,price=price,activation_pct=trailing_activation_pct,trailing_distance_pct=trailing_distance_pct,minimum_profit_pct=minimum_profit_pct);pnl=focus_pnl_pct(updated,price);taken=set(updated.partials_taken)
    if partial_tp_enabled and pnl>=first_partial_tp_pct and 1 not in taken:
        taken.add(1);updated=replace(updated,partials_taken=tuple(sorted(taken)),cycle_status="Partial winst nemen");return updated,FocusDecision("PARTIAL_TP",updated.active_pair,notional=updated.total_notional*first_partial_close_pct,close_fraction=first_partial_close_pct,reason="eerste partial TP bereikt",status="Partial winst nemen",risk_reducing=True)
    if partial_tp_enabled and pnl>=second_partial_tp_pct and 2 not in taken:
        taken.add(2);updated=replace(updated,partials_taken=tuple(sorted(taken)),cycle_status="Partial winst nemen");return updated,FocusDecision("PARTIAL_TP",updated.active_pair,notional=updated.total_notional*second_partial_close_pct,close_fraction=second_partial_close_pct,reason="tweede partial TP bereikt",status="Partial winst nemen",risk_reducing=True)
    if updated.trailing_active and updated.trailing_floor>0 and price<=updated.trailing_floor:return replace(updated,cycle_status="Winst nemen"),FocusDecision("CLOSE",updated.active_pair,notional=updated.total_notional,close_fraction=1,reason="trailing floor geraakt",status="Winst nemen",risk_reducing=True)
    if pnl>=minimum_profit_pct and bollinger_overextended_reversal and not momentum_healthy:return replace(updated,cycle_status="Winst nemen"),FocusDecision("CLOSE",updated.active_pair,notional=updated.total_notional,close_fraction=1,reason="momentum draait na Bollinger-overstretch",status="Winst nemen",risk_reducing=True)
    return updated,FocusDecision("HOLD",updated.active_pair,reason="runner blijft open",status=updated.cycle_status)

def reset_after_full_exit(state:FocusState,*,realized_pnl:float,theoretical_portfolio_value:float)->FocusState:
    return FocusState(realized_pnl=state.realized_pnl+realized_pnl,theoretical_portfolio_value=theoretical_portfolio_value,cycle_status="Nieuwe pair zoeken",last_action="CLOSE",last_reason="volledige Focus-cyclus gesloten")

def focus_shadow_report(*,state:FocusState,decision:FocusDecision,ranking:list[FocusRankingRow],portfolio_equity:float,realized_pnl:float=0.0,unrealized_pnl:float=0.0,max_drawdown:float=0.0,fees:float=0.0,capital_used_margin:float=0.0,trades:int=0)->dict[str,Any]:
    return {"mode":"focus-shadow","ordersSent":0,"state":state.public_dict(),"decision":decision.public_dict(),"ranking":[r.public_dict() for r in ranking],"performance":{"portfolioEquity":portfolio_equity,"realizedPnl":realized_pnl,"unrealizedPnl":unrealized_pnl,"maxDrawdown":max_drawdown,"trades":trades,"dcaCount":state.dca_count,"fees":fees,"capitalUsedMargin":capital_used_margin,"returnPerUsedMargin":(realized_pnl+unrealized_pnl)/capital_used_margin if capital_used_margin>0 else 0.0}}
