"""Pure adaptive hedge planner for Strategy-2 Focus Portfolio Airbag.

No network calls and no order submission live here. The runtime supplies current
Aster truth and 1m Bollinger evidence, then executes the returned target through
existing idempotent Hedge-Mode order plumbing.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
import math


@dataclass(frozen=True)
class AirbagPlan:
    enabled: bool
    status: str
    target_ratio: float
    current_ratio: float
    action: str
    reason: str
    next_action: str
    next_action_price: float | None = None


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value if math.isfinite(value) else low))


def bollinger_1m(closes: Iterable[float]) -> tuple[float, float, float] | None:
    values=[float(x) for x in closes if math.isfinite(float(x)) and float(x)>0]
    if len(values)<20:return None
    window=values[-20:];middle=sum(window)/len(window)
    variance=sum((x-middle)**2 for x in window)/len(window);dev=math.sqrt(max(0.0,variance))
    return middle,middle+2*dev,middle-2*dev


def plan_focus_airbag(*, enabled: bool, main_side: str, main_quantity: float, mark: float,
                      hedge_quantity: float, start_ratio: float, maximum_ratio: float,
                      minimum_ratio: float, drawdown_levels: tuple[float,float,float],
                      adverse_drawdown: float, portfolio_drawdown: float,
                      bollinger: tuple[float,float,float] | None, local_extreme: float | None = None, new_portfolio_high: bool = False) -> AirbagPlan:
    current=_clamp(hedge_quantity/max(main_quantity,1e-12)) if main_quantity>0 else 0.0
    if not enabled:
        action="CLOSE" if current>.002 else "HOLD"
        return AirbagPlan(False,"UIT",0.0,current,action,"Portfolio Airbag staat uit","Hedge volledig sluiten" if action=="CLOSE" else "Geen hedge actief")
    if main_quantity<=0 or mark<=0:
        return AirbagPlan(True,"WACHT",0.0,current,"HOLD","Geen betrouwbare actieve hoofdpositie","Wacht op Aster position truth")
    start=_clamp(start_ratio);maximum=max(start,_clamp(maximum_ratio));minimum=min(start,_clamp(minimum_ratio))
    l1,l2,l3=sorted(_clamp(x,0.0001,.95) for x in drawdown_levels)
    risk=max(0.0,adverse_drawdown,portfolio_drawdown)
    mid=max(start,(start+maximum)/2)
    if risk>=l3: target=maximum;status="MAX BESCHERMING"
    elif risk>=l2: target=mid;status="ACTIEF"
    elif risk>=l1: target=start;status="ACTIEF"
    else: target=start;status="WACHT"
    middle=upper=lower=None
    if bollinger:middle,upper,lower=bollinger
    side=main_side.upper();recovery=False;breakout=False
    if middle and upper and lower:
        recovery=(mark>=middle if side=="LONG" else mark<=middle)
        breakout=(mark>=upper if side=="LONG" else mark<=lower)
    if local_extreme and local_extreme>0:
        breakout=breakout or (mark>=local_extreme if side=="LONG" else mark<=local_extreme)
    breakout=breakout or bool(new_portfolio_high)
    if breakout:
        target=minimum;status="AAN HET AFBOUWEN" if current>minimum+.002 else "WACHT"
    elif recovery and target>minimum:
        target=max(minimum, target-(maximum-minimum)/3);status="AAN HET AFBOUWEN" if current>target+.002 else status
    target=_clamp(target,0,maximum)
    tolerance=.01
    if current<target-tolerance:action="INCREASE"
    elif current>target+tolerance:action="REDUCE"
    else:action="HOLD"
    reason_parts=[f"drawdown {risk*100:.2f}%"]
    if recovery:reason_parts.append("1m BB herstel")
    if breakout:reason_parts.append("sterke 1m breakout / local high")
    next_action="Hedge stabiel"
    next_price=None
    if action=="INCREASE":next_action=f"Hedge verhogen naar {target*100:.0f}%"
    elif action=="REDUCE":next_action=f"Hedge afbouwen naar {target*100:.0f}%"
    elif middle:
        next_price=middle;next_action=(f"Bij herstel boven {middle:.8g} bescherming afbouwen" if side=="LONG" else f"Bij herstel onder {middle:.8g} bescherming afbouwen")
    return AirbagPlan(True,status,target,current,action," · ".join(reason_parts),next_action,next_price)
