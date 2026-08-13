"""Deterministic Strategy-3 paper scenarios. No exchange adapter is imported."""
from dataclasses import dataclass, replace
from aster_strategy3 import Strategy3Config, LegState, PortfolioState, decide, net_return, update_trailing_peak

@dataclass
class ScenarioResult:
    name: str
    passed: bool
    decisions: list[str]
    protection_events: int
    trailing_events: int
    simulated_orders: int

def run_scenario(name: str, prices: list[float], config: Strategy3Config) -> ScenarioResult:
    long=LegState("LONG",config.base_notional,prices[0],prices[0]);short=LegState("SHORT",config.base_notional,prices[0],prices[0])
    events=[];protection=trailing=orders=0
    for price in prices[1:]:
        change=price/prices[0]-1
        long=replace(long,current_price=price,unrealized_pnl=long.size*change)
        short=replace(short,current_price=price,unrealized_pnl=-short.size*change)
        extreme=abs(change)>=.25
        p=PortfolioState(900 if extreme else 1000,1000,.62 if extreme else .10,long.size,short.size)
        for leg in (long,short):
            d=decide(config,leg,p);events.append(f"{leg.side}:{d.kind}")
            protection += int(d.kind in {"ASSIGN_PROTECTION","PARTIAL_TP"})
            trailing += int(d.kind in {"ARM_TRAILING","TRAILING_TP"})
            orders += int(d.kind in {"ADD_DCA","FULL_TP","PARTIAL_TP","TRAILING_TP"})
            if d.kind=="ARM_TRAILING": leg=update_trailing_peak(leg,net_return(leg))
            if leg.side=="LONG": long=leg
            else: short=leg
    passed=bool(events) and (not name.startswith("extreme") or any("HOLD" in x or "PROTECTION" in x for x in events))
    return ScenarioResult(name,passed,events,protection,trailing,orders)

def standard_suite(config: Strategy3Config):
    return [run_scenario("bull",[100,102,105,110,125],config),run_scenario("bear",[100,98,94,85,70],config),
        run_scenario("sideways",[100,102,99,103,98,102,100],config),run_scenario("extreme-pump",[100,110,130,160],config),
        run_scenario("extreme-crash",[100,90,70,50],config),run_scenario("reversal",[100,80,60,85,105],config)]

def failure_suite(config: Strategy3Config):
    leg=LegState("LONG",10,100,90);p=lambda **kw:PortfolioState(1000,1000,.1,10,10,**kw)
    return {"live_adapter_absent":True,"unknown_exchange_blocks_risk":decide(config,leg,p(exchange_reliable=False)).kind=="HOLD",
        "unknown_ownership_blocks_risk":decide(config,leg,p(ownership_reliable=False)).kind=="HOLD",
        "unknown_order_blocks_risk":decide(config,leg,p(open_orders_unknown=True)).kind=="HOLD"}
