"""Durable idempotency ledger rules for Money Grabber exchange intents."""
from __future__ import annotations
from dataclasses import dataclass,replace
from typing import Literal

IntentStatus=Literal["PREPARED","SUBMITTING","CONFIRMED","REJECTED","UNKNOWN","RECOVERY"]

@dataclass(frozen=True)
class DurableIntent:
    intent_id:str;account_id:str;round_id:str;kind:str;symbol:str;side:str
    target_notional:float;status:IntentStatus="PREPARED";exchange_order_id:str=""
    filled_notional:float=0.0;attempts:int=0;updated_at_ms:int=0

def prepare(existing:DurableIntent|None,candidate:DurableIntent)->DurableIntent:
    if not candidate.intent_id or not candidate.account_id or not candidate.round_id:
        raise ValueError("Intent-, account- en ronde-ID zijn verplicht")
    if candidate.target_notional<=0:raise ValueError("Intent-notional moet positief zijn")
    if existing is None:return candidate
    identity=(existing.account_id,existing.round_id,existing.kind,existing.symbol,existing.side)
    requested=(candidate.account_id,candidate.round_id,candidate.kind,candidate.symbol,candidate.side)
    if existing.intent_id!=candidate.intent_id or identity!=requested:
        raise ValueError("Intent-ID botst met andere economische ownership")
    return existing

def may_submit(value:DurableIntent)->bool:
    return value.status=="PREPARED" and value.attempts==0 and not value.exchange_order_id

def mark_submitting(value:DurableIntent,now_ms:int)->DurableIntent:
    if not may_submit(value):raise RuntimeError("Intent mag niet opnieuw worden verstuurd; reconcileer eerst")
    return replace(value,status="SUBMITTING",attempts=1,updated_at_ms=now_ms)

def mark_unknown(value:DurableIntent,now_ms:int)->DurableIntent:
    if value.status!="SUBMITTING":raise RuntimeError("Alleen een verstuurde intentie kan UNKNOWN worden")
    return replace(value,status="UNKNOWN",updated_at_ms=now_ms)

def reconcile(value:DurableIntent,*,order_found:bool,terminal_status:str,exchange_order_id:str="",
              filled_notional:float=0.0,now_ms:int)->DurableIntent:
    if value.status not in {"SUBMITTING","UNKNOWN","RECOVERY"}:return value
    status=terminal_status.upper()
    if not order_found:
        # Absence in one read is not proof of rejection. Remain recovery-only.
        return replace(value,status="RECOVERY",updated_at_ms=now_ms)
    if status=="FILLED" and filled_notional>0:
        return replace(value,status="CONFIRMED",exchange_order_id=exchange_order_id,
            filled_notional=filled_notional,updated_at_ms=now_ms)
    if status in {"REJECTED","CANCELED","EXPIRED"}:
        return replace(value,status="REJECTED",exchange_order_id=exchange_order_id,updated_at_ms=now_ms)
    return replace(value,status="UNKNOWN",exchange_order_id=exchange_order_id,updated_at_ms=now_ms)

def to_mapping(value:DurableIntent)->dict:
    return {"intentId":value.intent_id,"accountId":value.account_id,"roundId":value.round_id,
        "kind":value.kind,"symbol":value.symbol,"side":value.side,"targetNotional":value.target_notional,
        "status":value.status,"exchangeOrderId":value.exchange_order_id,"filledNotional":value.filled_notional,
        "attempts":value.attempts,"updatedAtMs":value.updated_at_ms}

def from_mapping(raw:dict)->DurableIntent:
    return DurableIntent(str(raw["intentId"]),str(raw["accountId"]),str(raw["roundId"]),str(raw["kind"]),
        str(raw.get("symbol","")),str(raw.get("side","")),float(raw["targetNotional"]),str(raw.get("status","PREPARED")),
        str(raw.get("exchangeOrderId","")),float(raw.get("filledNotional",0)),int(raw.get("attempts",0)),int(raw.get("updatedAtMs",0)))
