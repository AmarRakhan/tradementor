"""Durable Money Grabber state conversion and restart reconciliation."""
from __future__ import annotations
from dataclasses import asdict,replace
from typing import Any

from money_grabber import ProtectedPair,Round


def round_to_mapping(value:Round)->dict[str,Any]:
    return {"accountId":value.account_id,"roundId":value.round_id,"status":value.status,
        "startNetValue":value.start_net_value,"targetRatio":value.target_ratio,
        "targetNetValue":value.target_net_value,"startedAtMs":value.started_at_ms,
        "consecutiveTargetProofs":value.consecutive_target_proofs,"closeIntentId":value.close_intent_id}


def round_from_mapping(raw:dict[str,Any])->Round:
    return Round(str(raw["accountId"]),str(raw["roundId"]),str(raw["status"]),
        float(raw["startNetValue"]),float(raw["targetRatio"]),float(raw["targetNetValue"]),
        int(raw["startedAtMs"]),int(raw.get("consecutiveTargetProofs",0)),str(raw.get("closeIntentId","")))


def pair_to_mapping(value:ProtectedPair)->dict[str,Any]:
    return {"accountId":value.account_id,"roundId":value.round_id,"symbol":value.symbol,
        "originalSide":value.original_side,"status":value.status,"originalNotional":value.original_notional,
        "protectionNotional":value.protection_notional,"residualNotional":value.residual_notional,
        "intentId":value.intent_id,"cooldownScans":value.cooldown_scans}


def pair_from_mapping(raw:dict[str,Any])->ProtectedPair:
    return ProtectedPair(str(raw["accountId"]),str(raw["roundId"]),str(raw["symbol"]).upper(),
        str(raw["originalSide"]).upper(),str(raw.get("status","FREE")),float(raw.get("originalNotional",0)),
        float(raw.get("protectionNotional",0)),float(raw.get("residualNotional",0)),
        str(raw.get("intentId","")),int(raw.get("cooldownScans",0)))


def reconcile_pairs(*,account_id:str,round_id:str,pairs:list[ProtectedPair],
                    positions:list[dict[str,Any]],open_orders:list[dict[str,Any]],
                    exchange_reliable:bool)->tuple[list[ProtectedPair],list[str]]:
    if not exchange_reliable:return [replace(x,status="RECOVERY") for x in pairs],["Exchange-state onbetrouwbaar"]
    quantities={(str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()):abs(float(x.get("positionAmt",0))) for x in positions}
    order_keys={(str(x.get("symbol","")).upper(),str(x.get("positionSide","")).upper()) for x in open_orders}
    result=[];reasons=[]
    for pair in pairs:
        if pair.account_id!=account_id or pair.round_id!=round_id:
            result.append(replace(pair,status="RECOVERY"));reasons.append(f"{pair.symbol}: ownershipconflict");continue
        original=quantities.get((pair.symbol,pair.original_side),0);protection=quantities.get((pair.symbol,pair.protection_side),0)
        has_order=(pair.symbol,pair.original_side) in order_keys or (pair.symbol,pair.protection_side) in order_keys
        if pair.status in {"PROTECTION_PENDING","FULL_PROTECTION_PENDING","PAIR_CLOSE_PENDING","PAIR_CLOSING"} and has_order:
            result.append(pair);continue
        if pair.status=="COOLDOWN":
            if original or protection or has_order:result.append(replace(pair,status="RECOVERY"));reasons.append(f"{pair.symbol}: exposure tijdens cooldown")
            elif pair.cooldown_scans>=1:result.append(replace(pair,status="FREE",cooldown_scans=pair.cooldown_scans+1))
            else:result.append(replace(pair,cooldown_scans=1))
            continue
        if original==0 and protection==0 and not has_order:
            result.append(replace(pair,status="COOLDOWN",original_notional=0,protection_notional=0,residual_notional=0,cooldown_scans=0));continue
        if original<=0 or protection<=0:
            result.append(replace(pair,status="RECOVERY"));reasons.append(f"{pair.symbol}: slechts één gekoppelde kant aanwezig");continue
        ratio=protection/original
        status="LOCKED" if ratio>=.999999 else "PARTIAL_PROTECTION"
        result.append(replace(pair,status=status,original_notional=original,protection_notional=protection,
            residual_notional=max(0,original-protection)))
    return result,reasons
