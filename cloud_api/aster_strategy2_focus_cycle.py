"""Persistent Focus cycle guard: equity handbrake, hedge parking and rotation."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Literal
import math

BrakeMode = Literal["off", "usd", "pct"]


def _f(value: Any, default: float = 0.0) -> float:
    try: result = float(value)
    except (TypeError, ValueError): return default
    return result if math.isfinite(result) else default


@dataclass(frozen=True)
class ParkedPair:
    symbol: str
    cycle_id: str
    original_side: str = "LONG"
    hedge_side: str = "SHORT"
    original_quantity: float = 0.0
    hedge_quantity: float = 0.0
    hedge_order_id: str = ""
    hedge_intent_id: str = ""
    parked_at_ms: int = 0
    status: str = "PARKED"


@dataclass(frozen=True)
class FocusCycleState:
    cycle_id: str = ""
    high_water_equity: float = 0.0
    current_equity: float = 0.0
    drawdown_usd: float = 0.0
    drawdown_pct: float = 0.0
    used_pairs: tuple[str, ...] = ()
    parked_pairs: tuple[ParkedPair, ...] = ()
    current_pair_number: int = 0
    recovery_status: str = "OK"
    last_event: str = ""
    last_event_at_ms: int = 0

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["used_pairs"] = list(self.used_pairs)
        value["parked_pairs"] = [asdict(x) for x in self.parked_pairs]
        return value


def cycle_state_from_mapping(raw: Any) -> FocusCycleState:
    row = raw if isinstance(raw, dict) else {}
    parked_raw = row.get("parkedPairs", row.get("parked_pairs", ()))
    parked: list[ParkedPair] = []
    for item in parked_raw if isinstance(parked_raw, (list, tuple)) else ():
        if not isinstance(item, dict): continue
        parked.append(ParkedPair(
            symbol=str(item.get("symbol", "")).upper(), cycle_id=str(item.get("cycleId", item.get("cycle_id", ""))),
            original_side=str(item.get("originalSide", item.get("original_side", "LONG"))).upper(),
            hedge_side=str(item.get("hedgeSide", item.get("hedge_side", "SHORT"))).upper(),
            original_quantity=abs(_f(item.get("originalQuantity", item.get("original_quantity", 0)))),
            hedge_quantity=abs(_f(item.get("hedgeQuantity", item.get("hedge_quantity", 0)))),
            hedge_order_id=str(item.get("hedgeOrderId", item.get("hedge_order_id", ""))),
            hedge_intent_id=str(item.get("hedgeIntentId", item.get("hedge_intent_id", ""))),
            parked_at_ms=int(_f(item.get("parkedAt", item.get("parked_at_ms", 0)))), status=str(item.get("status", "PARKED")),
        ))
    used_raw = row.get("usedPairs", row.get("used_pairs", ()))
    used = tuple(dict.fromkeys(str(x).upper() for x in used_raw if str(x).strip())) if isinstance(used_raw, (list, tuple)) else ()
    return FocusCycleState(
        cycle_id=str(row.get("cycleId", row.get("cycle_id", ""))),
        high_water_equity=_f(row.get("highWaterEquity", row.get("high_water_equity", 0))),
        current_equity=_f(row.get("currentEquity", row.get("current_equity", 0))),
        drawdown_usd=_f(row.get("drawdownUsd", row.get("drawdown_usd", 0))),
        drawdown_pct=_f(row.get("drawdownPct", row.get("drawdown_pct", 0))),
        used_pairs=used, parked_pairs=tuple(parked), current_pair_number=int(_f(row.get("currentPairNumber", row.get("current_pair_number", 0)))),
        recovery_status=str(row.get("recoveryStatus", row.get("recovery_status", "OK"))),
        last_event=str(row.get("lastEvent", row.get("last_event", ""))), last_event_at_ms=int(_f(row.get("lastEventAt", row.get("last_event_at_ms", 0)))),
    )


def cycle_state_to_mapping(state: FocusCycleState) -> dict[str, Any]:
    return {
        "cycleId": state.cycle_id, "highWaterEquity": state.high_water_equity, "currentEquity": state.current_equity,
        "drawdownUsd": state.drawdown_usd, "drawdownPct": state.drawdown_pct, "usedPairs": list(state.used_pairs),
        "parkedPairs": [{"symbol":x.symbol,"cycleId":x.cycle_id,"originalSide":x.original_side,"hedgeSide":x.hedge_side,
            "originalQuantity":x.original_quantity,"hedgeQuantity":x.hedge_quantity,"hedgeOrderId":x.hedge_order_id,
            "hedgeIntentId":x.hedge_intent_id,"parkedAt":x.parked_at_ms,"status":x.status} for x in state.parked_pairs],
        "currentPairNumber": state.current_pair_number, "recoveryStatus": state.recovery_status,
        "lastEvent": state.last_event, "lastEventAt": state.last_event_at_ms,
    }


def update_high_water(state: FocusCycleState, *, equity: float, timestamp_ms: int) -> FocusCycleState:
    equity=max(0.0,_f(equity)); high=max(state.high_water_equity,equity)
    dd=max(0.0,high-equity); pct=dd/high if high>0 else 0.0
    event="FOCUS_HIGH_WATER_UPDATED" if high>state.high_water_equity else state.last_event
    return FocusCycleState(state.cycle_id,high,equity,dd,pct,state.used_pairs,state.parked_pairs,state.current_pair_number,
        state.recovery_status,event,timestamp_ms if event=="FOCUS_HIGH_WATER_UPDATED" else state.last_event_at_ms)


def brake_triggered(state: FocusCycleState, *, mode: str, value: float) -> bool:
    threshold=max(0.0,_f(value)); mode=str(mode).lower()
    if threshold<=0 or mode=="off" or state.high_water_equity<=0:return False
    if mode=="usd": return state.drawdown_usd >= threshold
    if mode=="pct": return state.drawdown_pct >= threshold
    return False


def can_rotate(state: FocusCycleState, max_pairs: int) -> bool:
    return int(max_pairs)>0 and len(state.used_pairs) < int(max_pairs)


def mark_pair_used(state: FocusCycleState, symbol: str, *, timestamp_ms: int) -> FocusCycleState:
    symbol=str(symbol).upper(); used=tuple(dict.fromkeys((*state.used_pairs,symbol)))
    return FocusCycleState(state.cycle_id,state.high_water_equity,state.current_equity,state.drawdown_usd,state.drawdown_pct,
        used,state.parked_pairs,len(used),state.recovery_status,"FOCUS_SELECTED",timestamp_ms)


def park_pair(state: FocusCycleState, parked: ParkedPair, *, timestamp_ms: int) -> FocusCycleState:
    rows=tuple(x for x in state.parked_pairs if x.symbol!=parked.symbol)+(parked,)
    used=tuple(dict.fromkeys((*state.used_pairs,parked.symbol)))
    return FocusCycleState(state.cycle_id,state.high_water_equity,state.current_equity,state.drawdown_usd,state.drawdown_pct,
        used,rows,len(used),"OK","FOCUS_PARKED",timestamp_ms)


def reset_cycle(*, equity: float, cycle_id: str="", timestamp_ms: int=0) -> FocusCycleState:
    equity=max(0.0,_f(equity))
    return FocusCycleState(cycle_id=cycle_id,high_water_equity=equity,current_equity=equity,last_event="FOCUS_CYCLE_RESET",last_event_at_ms=timestamp_ms)
