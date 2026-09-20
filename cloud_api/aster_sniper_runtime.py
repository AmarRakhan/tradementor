"""Live SNIPER runtime with one-order-per-tick fail-closed execution."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, Callable
import hashlib
import time

from aster_execution import PairExecutionPlan, execute_leg_once
from aster_gateway import PositionSide
from aster_sniper import SniperSettings, evaluate_candidate, exit_decision, number
from aster_state import account_information_values
from aster_execution import plan_pair as plan_aster_pair


def _position(rows: list[dict[str, Any]], symbol: str, side: str) -> dict[str, Any] | None:
    return next((row for row in rows
        if str(row.get("symbol","")).upper()==symbol.upper()
        and str(row.get("positionSide","")).upper()==side.upper()
        and abs(number(row.get("positionAmt")))>0), None)


def _brackets(rows: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    for row in rows:
        if str(row.get("symbol","")).upper()==symbol.upper():
            return list(row.get("brackets") or [])
    return list(rows or [])


def _trade_public(trade: dict[str, Any], row: dict[str, Any] | None, now_ms: int) -> dict[str, Any]:
    value=dict(trade)
    if row:
        mark=number(row.get("markPrice"));qty=abs(number(row.get("positionAmt")))
        pnl=number(row.get("unRealizedProfit",row.get("unrealizedPnl")))
        value.update({"markPrice":mark,"quantity":qty,"notionalUsd":qty*mark,"unrealizedPnlUsd":pnl})
        value["unrealizedPnlPercent"]=(pnl/(qty*mark)*100) if qty*mark>0 else 0.0
    value["elapsedSeconds"]=max(0,(now_ms-int(number(trade.get("openedAtMs"))))/1000)
    return value


def reconcile_pending(
    *,
    client: Any,
    state: dict[str, Any],
    settings: SniperSettings,
    now_ms: int,
    release_symbol: Callable[[str], None],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    pending=state.get("pendingIntent") if isinstance(state.get("pendingIntent"),dict) else {}
    if not pending:
        return state,None
    symbol=str(pending.get("symbol","")).upper();side=str(pending.get("side","")).upper()
    positions=client.position_risk()
    row=_position(positions,symbol,side)
    if row is not None and str(pending.get("action","")).upper()=="OPEN":
        trades=[dict(x) for x in state.get("activeTrades",[]) if isinstance(x,dict)]
        if not any(str(x.get("symbol","")).upper()==symbol for x in trades):
            qty=abs(number(row.get("positionAmt")));entry=number(row.get("entryPrice"));mark=number(row.get("markPrice"))
            trades.append({
                "tradeId":str(pending.get("tradeId") or f"recovered-{symbol}-{now_ms}"),
                "symbol":symbol,"side":side,"quantity":qty,"entryPrice":entry,"markPrice":mark,
                "notionalUsd":qty*mark,"marginUsd":number(pending.get("marginUsd")),
                "leverage":int(number(row.get("leverage")) or settings.leverage),
                "openedAtMs":int(number(pending.get("createdAtMs")) or now_ms),
                "deadlineAtMs":int(number(pending.get("createdAtMs")) or now_ms)+settings.max_trade_seconds*1000,
                "tpPercent":number(pending.get("tpPercent")) or settings.tp_min_percent,
                "checks":pending.get("checks") if isinstance(pending.get("checks"),list) else [],
                "timeframe":str(pending.get("timeframe") or "recovered"),
                "entryReason":"Hersteld uit exchange-state na onderbroken orderflow",
                "openClientOrderId":str(pending.get("clientOrderId") or ""),
            })
        state={**state,"activeTrades":trades,"pendingIntent":None,"phase":"RUNNING",
            "lastReason":f"{symbol}: pending Sniper-entry uit exchange-state hersteld"}
        return state,{"event":"RECOVERED_OPEN","symbol":symbol,"side":side}
    if row is None:
        orders=[x for x in client.open_orders(symbol) if str(x.get("symbol","")).upper()==symbol]
        age=now_ms-int(number(pending.get("createdAtMs")))
        if not orders and age>=60_000:
            release_symbol(symbol)
            state={**state,"pendingIntent":None,"phase":"RUNNING",
                "lastReason":f"{symbol}: onbevestigde Sniper-intentie veilig vrijgegeven na exchange-reconciliation"}
            return state,{"event":"PENDING_CLEARED","symbol":symbol,"side":side}
    return state,None


def run_sniper_tick(
    *,
    client: Any,
    state: dict[str, Any],
    settings: SniperSettings,
    blocked_symbols: set[str],
    claim_symbol: Callable[[str, str], bool],
    release_symbol: Callable[[str], None],
    persist_pending: Callable[[dict[str, Any] | None], None],
    live_enabled: bool,
    dry_run: bool = False,
    now_ms: int | None = None,
) -> dict[str, Any]:
    now_ms=int(now_ms or time.time()*1000)
    state,recovery=reconcile_pending(client=client,state=state,settings=settings,now_ms=now_ms,release_symbol=release_symbol)
    if state.get("pendingIntent"):
        return {"status":"reconciling","ordersSent":0,"state":state,"recovery":recovery}

    positions=client.position_risk()
    trades=[dict(x) for x in state.get("activeTrades",[]) if isinstance(x,dict)]
    history_record=None

    # Existing Sniper trades always get management priority, even after the user
    # turns new entries off. One exchange order maximum per tick.
    for trade in list(trades):
        symbol=str(trade.get("symbol","")).upper();side=str(trade.get("side","")).upper()
        row=_position(positions,symbol,side)
        if row is None:
            trades.remove(trade);release_symbol(symbol)
            history_record={**trade,"closedAtMs":now_ms,"exitReason":"Exchange bevestigt positie flat",
                "realizedPnlUsd":number(trade.get("lastKnownPnlUsd")),"status":"CLOSED_RECONCILED"}
            state={**state,"activeTrades":trades,"lastReason":f"{symbol}: exchange-flat gereconcilieerd"}
            return {"status":"ok","action":"RECONCILE_FLAT","ordersSent":0,"state":state,"historyRecord":history_record}
        decision=exit_decision(trade,row,now_ms=now_ms,settings=settings)
        trade.update(_trade_public(trade,row,now_ms))
        trade["lastKnownPnlUsd"]=decision["pnlUsd"]
        if decision["action"]=="HOLD":
            continue
        if dry_run or not live_enabled:
            return {"status":"simulated" if dry_run else "blocked","action":decision["action"],"ordersSent":0,
                "state":{**state,"activeTrades":trades},"reason":"Sniper live execution staat centraal uit" if not dry_run else decision["reason"]}
        qty=abs(Decimal(str(row.get("positionAmt"))));mark=number(row.get("markPrice"))
        plan=PairExecutionPlan(symbol,qty,qty*Decimal(str(mark)),max(1,int(number(row.get("leverage")) or settings.leverage)))
        close_id=f"snc-{hashlib.sha256((str(trade.get('tradeId'))+decision['action']).encode()).hexdigest()[:14]}"
        pending={"action":"CLOSE","symbol":symbol,"side":side,"tradeId":trade.get("tradeId"),"createdAtMs":now_ms,
            "clientOrderId":close_id,"reason":decision["reason"]}
        persist_pending(pending)
        result=execute_leg_once(client,plan,side=PositionSide(side),action="CLOSE",id_prefix=close_id,confirm=True,
            automatic_loss_exit_authorized=True,fill_poll_attempts=2,fill_poll_delay_seconds=.15)
        remaining=_position(client.position_risk(symbol),symbol,side)
        if remaining is not None:
            raise RuntimeError(f"{symbol}: Sniper-close is nog niet exchange-flat bevestigd")
        rr=result.get("result",{}) if isinstance(result,dict) else {}
        trades.remove(trade);release_symbol(symbol);persist_pending(None)
        history_record={**trade,"closedAtMs":now_ms,"exitReason":decision["reason"],"exitAction":decision["action"],
            "realizedPnlUsd":decision["pnlUsd"],"closeClientOrderId":str(rr.get("clientOrderId","")),
            "closeOrderId":str(rr.get("orderId","")),"status":"CLOSED"}
        state={**state,"activeTrades":trades,"pendingIntent":None,"phase":"RUNNING" if state.get("enabled") else "DRAINING",
            "lastReason":f"{symbol}: {decision['reason']}"}
        return {"status":"ok","action":decision["action"],"ordersSent":1,"state":state,"historyRecord":history_record}

    state={**state,"activeTrades":trades}
    if not bool(state.get("enabled")):
        return {"status":"stopped","ordersSent":0,"state":{**state,"monitor":bool(trades),"phase":"DRAINING" if trades else "STOPPED"}}
    if len(trades)>=settings.max_concurrent:
        return {"status":"waiting","ordersSent":0,"state":state,"reason":"Sniper maximum gelijktijdige trades bereikt"}

    day_loss=number(state.get("dayRealizedPnlUsd"))
    if day_loss<=-settings.max_daily_loss_usd:
        return {"status":"risk-hold","ordersSent":0,"state":{**state,"phase":"RISK_HOLD","lastReason":"Maximaal Sniper dagverlies bereikt"}}

    account=client.account_information()
    equity,_,available,_,maintenance=account_information_values(account)
    margin_ratio=maintenance/equity if equity>0 else 1.0
    if equity<=0 or margin_ratio>=.65:
        return {"status":"risk-hold","ordersSent":0,"state":{**state,"phase":"RISK_HOLD","lastReason":"Account-risicoguard blokkeert nieuwe Sniper-entry"}}

    info_rows={str(x.get("symbol","")).upper():x for x in client.public_exchange_info().get("symbols",[]) if isinstance(x,dict)}
    prices={str(x.get("symbol","")).upper():number(x.get("price")) for x in client.ticker_prices()}
    tickers=[x for x in client.ticker_24h() if isinstance(x,dict)]
    tickers.sort(key=lambda x:number(x.get("quoteVolume")),reverse=True)
    active_symbols={str(x.get("symbol","")).upper() for x in trades}|set(blocked_symbols)
    cooldowns={str(k):dict(v) for k,v in (state.get("cooldowns") or {}).items() if isinstance(v,dict)}
    signals=[]
    for market in tickers[:settings.universe_top_n]:
        symbol=str(market.get("symbol","")).upper()
        if not symbol.endswith("USDT") or symbol in active_symbols or symbol not in info_rows or prices.get(symbol,0)<=0:
            continue
        prior=cooldowns.get(symbol,{})
        if int(number(prior.get("untilMs")))>now_ms:
            continue
        try:
            signal=evaluate_candidate(symbol,candles_1m=client.klines(symbol,"1m",100),
                candles_3m=client.klines(symbol,"3m",80),candles_5m=client.klines(symbol,"5m",80),
                ticker_24h=market,book=client.book_ticker(symbol),depth=client.order_book(symbol,20),settings=settings)
        except Exception as exc:
            signals.append({"symbol":symbol,"score":0,"eligible":False,"reason":f"Data check mislukt: {str(exc)[:120]}"})
            continue
        signals.append(signal)
        if not signal.get("eligible"):
            continue
        if not claim_symbol(symbol,"SNIPER"):
            signals[-1]={**signal,"eligible":False,"reason":"BLOCKED_BY_OTHER_STRATEGY"}
            continue
        try:
            notional=settings.margin_per_trade_usd*settings.leverage
            plan=plan_aster_pair(info_rows[symbol],_brackets(client.leverage_brackets(symbol),symbol),prices[symbol],notional,
                accepted_leverage=settings.leverage)
            plan=replace(plan,leverage=settings.leverage)
            required=float(plan.notional_per_leg)/max(1,settings.leverage)
            if required*1.05>available:
                release_symbol(symbol)
                return {"status":"risk-hold","ordersSent":0,"state":state,"signals":signals[:20],
                    "reason":"Onvoldoende werkelijk beschikbare Aster-margin"}
            trade_id=f"sn-{now_ms}-{symbol.lower()}"
            prefix=f"sno-{hashlib.sha256((trade_id+signal['side']).encode()).hexdigest()[:14]}"
            pending={"action":"OPEN","symbol":symbol,"side":signal["side"],"tradeId":trade_id,"createdAtMs":now_ms,
                "marginUsd":required,"notionalUsd":float(plan.notional_per_leg),"leverage":settings.leverage,
                "tpPercent":signal["tpPercent"],"checks":signal["checks"],"timeframe":signal["timeframe"],"clientOrderId":prefix}
            if dry_run:
                release_symbol(symbol)
                return {"status":"simulated","action":"OPEN","ordersSent":0,"state":state,"signals":signals[:20],"planned":pending}
            if not live_enabled:
                release_symbol(symbol)
                return {"status":"blocked","ordersSent":0,"state":state,"signals":signals[:20],"reason":"Sniper live execution staat centraal uit"}
            persist_pending(pending)
            opened=execute_leg_once(client,plan,side=PositionSide(signal["side"]),action="OPEN",id_prefix=prefix,confirm=True,
                new_position_leverage=settings.leverage,fill_poll_attempts=2,fill_poll_delay_seconds=.15)
            rr=opened.get("result",{});qty=number(rr.get("executedQty"));entry=number(rr.get("avgPrice"))
            if qty<=0 or entry<=0:
                raise RuntimeError("Sniper-entry mist bevestigde fill")
            trade={**pending,"quantity":qty,"entryPrice":entry,"markPrice":prices[symbol],
                "openedAtMs":now_ms,"deadlineAtMs":now_ms+settings.max_trade_seconds*1000,
                "openClientOrderId":str(rr.get("clientOrderId","")),"openOrderId":str(rr.get("orderId","")),
                "entryReason":signal["reason"],"status":"OPEN"}
            trades.append(trade);persist_pending(None)
            state={**state,"activeTrades":trades,"pendingIntent":None,"signals":signals[:20],"phase":"RUNNING",
                "lastReason":f"{symbol} {signal['side']}: Sniper live entry bevestigd","lastActionAtMs":now_ms}
            return {"status":"ok","action":"OPEN","ordersSent":1,"state":state,"trade":trade,"signals":signals[:20]}
        except Exception:
            # Keep a persisted pending intent when submission may have happened.
            # The next tick reconciles it against exchange truth before any retry.
            if not state.get("pendingIntent"):
                release_symbol(symbol)
            raise
    state={**state,"signals":signals[:20],"phase":"SCANNING","lastReason":"Geen 12/12 Sniper setup gevonden","lastScanAtMs":now_ms}
    return {"status":"waiting","ordersSent":0,"state":state,"signals":signals[:20]}
