"""Cash-flow-adjusted strategy and portfolio performance aggregation."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,date
from typing import Iterable
from aster_strategy2 import compounded_return

@dataclass(frozen=True)
class EquitySnapshot:
    at:datetime;equity:float;realized_pnl:float=0;unrealized_pnl:float=0;fees:float=0;funding:float=0;deposits:float=0;withdrawals:float=0

@dataclass(frozen=True)
class DailyPerformance:
    day:date;start_equity:float;end_equity:float;return_ratio:float;realized_pnl:float;unrealized_change:float;fees:float;funding:float;deposits:float;withdrawals:float

def daily_performance(values:Iterable[EquitySnapshot])->list[DailyPerformance]:
    grouped={}
    for value in sorted(values,key=lambda x:x.at):grouped.setdefault(value.at.date(),[]).append(value)
    result=[]
    for day,rows in grouped.items():
        first,last=rows[0],rows[-1];deposits=sum(x.deposits for x in rows);withdrawals=sum(x.withdrawals for x in rows)
        ratio=(last.equity-deposits+withdrawals-first.equity)/first.equity if first.equity>0 else 0
        result.append(DailyPerformance(day,first.equity,last.equity,ratio,sum(x.realized_pnl for x in rows),last.unrealized_pnl-first.unrealized_pnl,sum(x.fees for x in rows),sum(x.funding for x in rows),deposits,withdrawals))
    return result

def period_return(days:Iterable[DailyPerformance])->float:return compounded_return([x.return_ratio for x in days])

def summary(values:Iterable[EquitySnapshot])->dict:
    rows=sorted(values,key=lambda x:x.at);days=daily_performance(rows)
    if not rows:return {"returnRatio":0,"highWaterMark":0,"drawdown":0,"calendar":[]}
    adjusted=rows[0].equity;hwm=adjusted
    for row in rows[1:]:adjusted=row.equity-row.deposits+row.withdrawals;hwm=max(hwm,adjusted)
    current=rows[-1].equity;drawdown=max(0,1-current/hwm) if hwm>0 else 0
    return {"returnRatio":period_return(days),"highWaterMark":hwm,"drawdown":drawdown,"realizedPnl":sum(x.realized_pnl for x in rows),"unrealizedPnl":rows[-1].unrealized_pnl,"fees":sum(x.fees for x in rows),"funding":sum(x.funding for x in rows),"calendar":[{"date":x.day.isoformat(),"returnRatio":x.return_ratio,"startEquity":x.start_equity,"endEquity":x.end_equity,"realizedPnl":x.realized_pnl,"unrealizedChange":x.unrealized_change,"fees":x.fees,"funding":x.funding,"deposits":x.deposits,"withdrawals":x.withdrawals} for x in days]}

