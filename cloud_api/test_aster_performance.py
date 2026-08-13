from datetime import datetime,timezone,timedelta
from aster_performance import *

def t(day,h=0):return datetime(2026,8,day,h,tzinfo=timezone.utc)
def test_deposit_and_withdrawal_are_not_performance():
    rows=[EquitySnapshot(t(1),1000),EquitySnapshot(t(1,23),1200,deposits=200),EquitySnapshot(t(2),1200),EquitySnapshot(t(2,23),1000,withdrawals=200)]
    days=daily_performance(rows);assert days[0].return_ratio==0 and days[1].return_ratio==0

def test_calendar_and_compounded_period_return():
    rows=[EquitySnapshot(t(1),100),EquitySnapshot(t(1,23),110),EquitySnapshot(t(2),110),EquitySnapshot(t(2,23),99)]
    out=summary(rows);assert round(out["returnRatio"],4)==-.01 and len(out["calendar"])==2

def test_open_loss_is_visible_in_equity_performance():
    rows=[EquitySnapshot(t(1),1000),EquitySnapshot(t(1,23),900,realized_pnl=100,unrealized_pnl=-200)]
    out=summary(rows);assert round(out["returnRatio"],6)==-.1 and out["realizedPnl"]==100 and out["unrealizedPnl"]==-200
