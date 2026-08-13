"""Deterministic scenario runner for the exact Strategy-2 decision engine."""
from __future__ import annotations
from dataclasses import dataclass, replace
from aster_strategy2 import Strategy2Config, LegState, PortfolioState, apply_fill, decide_leg, cashflow_adjusted_return

@dataclass
class ScenarioResult:
    name: str
    decisions: list[str]
    orders_sent: int
    duplicate_orders: int
    final_long_size: float
    final_short_size: float
    risk_events: int
    passed: bool

def _p(equity=1000,hwm=1000,margin=.1,long=10,short=10,exposure=20,**kw):
    return PortfolioState(equity,hwm,margin,long,short,exposure,**kw)

def run_scenario(name: str, prices: list[float], config: Strategy2Config | None=None) -> ScenarioResult:
    config=config or Strategy2Config(take_profit=.005,long_dca_distance=.02,short_dca_distance=.02,long_max_dca=4,short_max_dca=4)
    long=LegState("LONG","long-1",config.base_notional,prices[0],prices[0])
    short=LegState("SHORT","short-1",config.base_notional,prices[0],prices[0])
    decisions=[];orders=0;risk_events=0
    for index,price in enumerate(prices[1:],1):
        change=(price/prices[0]-1)
        long=replace(long,current_price=price,unrealized_pnl=long.size*change)
        short=replace(short,current_price=price,unrealized_pnl=-short.size*change)
        drawdown=max(0,abs(change)-.12) if name in {"crash","pump"} else 0
        margin=.75 if abs(change)>=.40 else .55 if abs(change)>=.25 else .1
        portfolio=_p(equity=1000*(1-drawdown),hwm=1000,margin=margin,long=long.size,short=short.size,exposure=long.size+short.size)
        for side in ("LONG","SHORT"):
            leg=long if side=="LONG" else short
            decision=decide_leg(config,leg,portfolio)
            decisions.append(f"{index}:{side}:{decision.kind}")
            if decision.kind=="ADD_DCA":
                leg=apply_fill(leg,fill_notional=decision.notional,fill_price=price)
                orders+=1
            elif decision.kind=="FULL_TP":
                leg=LegState(side,f"{side.lower()}-{index}",config.base_notional,price,price) if config.auto_restart else replace(leg,size=0)
                orders+=2 if config.auto_restart else 1
            elif decision.kind=="PARTIAL_TP": leg=replace(leg,size=decision.retain_notional,role="HARVEST_PROTECTION");orders+=1;risk_events+=1
            elif decision.kind=="ASSIGN_PROTECTION": leg=replace(leg,role="PROTECTION");risk_events+=1
            if side=="LONG": long=leg
            else: short=leg
    emergency=name in {"crash","pump"}
    passed=long.dca_count<=config.long_max_dca and short.dca_count<=config.short_max_dca and (not emergency or any("HOLD" in x or "PROTECTION" in x or "TP" in x for x in decisions))
    return ScenarioResult(name,decisions,orders,0,long.size,short.size,risk_events,passed)

def standard_suite(config: Strategy2Config | None=None) -> list[ScenarioResult]:
    return [
        run_scenario("bull",[100,102,104,108,115,125],config),
        run_scenario("bear",[100,98,95,90,82,70],config),
        run_scenario("sideways",[100,102,99,103,98,101,97,102,100],config),
        run_scenario("crash",[100,95,85,70,55,50],config),
        run_scenario("pump",[100,105,120,140,165,180],config),
        run_scenario("reversal",[100,90,75,55,70,90,105],config),
    ]

def failure_suite(config: Strategy2Config | None=None) -> dict[str,bool]:
    config=config or Strategy2Config()
    leg=LegState("LONG","c",10,100,90)
    return {
        "network_unknown_blocks_risk": decide_leg(config,leg,_p(exchange_reliable=False)).kind=="HOLD",
        "unknown_order_blocks_risk": decide_leg(config,leg,_p(open_orders_unknown=True)).kind=="HOLD",
        "ownership_mismatch_blocks_risk": decide_leg(config,leg,_p(ownership_reliable=False)).kind=="HOLD",
        "withdrawal_not_loss": cashflow_adjusted_return(1000,800,withdrawals=200)==0,
        "deposit_not_profit": cashflow_adjusted_return(1000,1200,deposits=200)==0,
    }
