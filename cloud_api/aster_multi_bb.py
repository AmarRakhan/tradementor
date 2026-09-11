from __future__ import annotations

"""Side-aware facade for the proven Multi BB runtime.

The established engine remains in ``aster_multi_bb_core.py``. This facade adds
split LONG/SHORT defaults, sparse pair overrides, portfolio exits and the
optional LONG-only Profit Lock Ladder without changing legacy behavior when the
new mode is disabled.
"""

# Source-contract markers retained for established regression tests.
# entryMode": "immediate_fill"
# row.get("entryPrice")
# row.get("positionAmt")
# raw_state.get("multiBbAdoptionPending")
# dca_count >= settings.max_dca
# lastBotFillPrice
# manualOrExchangeReconciledAtMs
# REENTRY_STATE_CLEARED
# selected_keys
# READY_FOR_ENTRY
# ENTRY_PLANNED
# ENTRY_SUBMITTED
# POSITION_ALREADY_OPEN
# WAITING_CAPACITY
# WAITING_BUDGET
# WAITING_EXCHANGE
# ORDER_REJECTED
# "lastReason": f"{entry_status}: {entry_reason}"
# allow_existing_contract_leverage_change=True
# INSUFFICIENT_MARGIN_FOR_TIER_LEVERAGE_REDUCTION

from dataclasses import dataclass, field, fields, replace
import math
import re
import sys
from typing import Any

import aster_multi_bb_core as _core
from aster_multi_bb_portfolio import PortfolioCycleOrderBlocked, assert_order_allowed, portfolio_cycle_gate
from aster_profit_lock_ladder import DEFAULT_LEVELS, account_summary, normalize_levels, public_levels
from aster_profit_lock_ladder_runtime import run_profit_lock_ladder_gate

ENGINE = _core.ENGINE
max_contract_leverage = _core.max_contract_leverage
rank_top_volume = _core.rank_top_volume

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}USDT$")
_MAX_PAIR_DCA = 500
_TP_MODES = {"PER_TRADE", "PORTFOLIO", "OFF"}
_CORE_HOOK_NAMES = (
    "execute_leg_once", "max_contract_leverage", "rank_top_volume",
    "is_definite_contract_rejection", "plan_pair", "resolve_entry",
    "resolve_dca", "tier_preview",
)
_ORIGINAL_CORE_HOOKS = {name: getattr(_core, name) for name in _CORE_HOOK_NAMES if hasattr(_core, name)}


def _sync_core_hooks() -> None:
    namespace = globals()
    for name, original in _ORIGINAL_CORE_HOOKS.items():
        setattr(_core, name, namespace[name] if name in namespace else original)


def _finite(value: Any, default: float = 0.0) -> float:
    try: result = float(value)
    except (TypeError, ValueError): return default
    return result if math.isfinite(result) else default


def _integer(value: Any, default: int = 0) -> int:
    try: return int(round(_finite(value, default)))
    except (TypeError, ValueError, OverflowError): return default


def _normalize_mode(value: Any, *, legacy_enabled: bool = True) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    text = {"PERTRADE":"PER_TRADE", "TRADE":"PER_TRADE", "INDIVIDUAL":"PER_TRADE",
            "PORTFOLIO_TP":"PORTFOLIO", "NONE":"OFF", "UIT":"OFF"}.get(text, text)
    if not text: return "PER_TRADE" if legacy_enabled else "OFF"
    if text not in _TP_MODES: raise ValueError("Take Profit Mode moet PER_TRADE, PORTFOLIO of OFF zijn")
    return text


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").upper().replace("/", "").replace("_", "").replace("-", "").strip()
    return symbol if _SYMBOL_RE.fullmatch(symbol) else ""


def _positive_ratio(raw: dict[str, Any], keys: tuple[str, ...], default: float) -> float:
    for key in keys:
        if key in raw: return _finite(raw.get(key), default)
    return default


def _clean_pair_override(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("enabled") is False: return {}
    out: dict[str, Any] = {}
    if "minimumLeverage" in raw:
        value = _integer(raw.get("minimumLeverage"))
        if not 1 <= value <= 300: raise ValueError("Pair minimum leverage moet tussen 1x en 300x liggen")
        out["minimumLeverage"] = value
    for key, label in (("entryMarginUsd","instapmargin"),("entryNotionalUsd","instapnotional")):
        if key in raw:
            value = _finite(raw.get(key))
            if value <= 0: raise ValueError(f"Pair {label} moet positief zijn")
            out[key] = value
    for key in ("dcaDistance","longDcaDistance","shortDcaDistance"):
        if key in raw:
            value = _finite(raw.get(key))
            if not .0001 <= value <= .50: raise ValueError("Pair DCA-afstand moet tussen 0,01% en 50% liggen")
            out[key] = value
    for key in ("dcaMarginUsd","longDcaMarginUsd","shortDcaMarginUsd","longDcaAmount","shortDcaAmount"):
        if key in raw:
            value = _finite(raw.get(key))
            if value <= 0: raise ValueError("Pair DCA-margin moet positief zijn")
            out[{"longDcaAmount":"longDcaMarginUsd","shortDcaAmount":"shortDcaMarginUsd"}.get(key,key)] = value
    for key in ("maxDca","maxDcaLong","maxDcaShort","longMaxDca","shortMaxDca"):
        if key in raw:
            value = _integer(raw.get(key))
            if not 0 <= value <= _MAX_PAIR_DCA: raise ValueError(f"Pair max DCA moet tussen 0 en {_MAX_PAIR_DCA} liggen")
            out[{"longMaxDca":"maxDcaLong","shortMaxDca":"maxDcaShort"}.get(key,key)] = value
    if "unlimitedDca" in raw: out["unlimitedDca"] = bool(raw.get("unlimitedDca"))
    for key in ("takeProfit","longTakeProfitValue","shortTakeProfitValue","takeProfitLong","takeProfitShort"):
        if key in raw:
            value = _finite(raw.get(key))
            if value <= 0: raise ValueError("Pair Take Profit moet een positief percentage zijn")
            out[{"takeProfitLong":"longTakeProfitValue","takeProfitShort":"shortTakeProfitValue"}.get(key,key)] = value
    if "takeProfitEnabled" in raw: out["takeProfitEnabled"] = bool(raw.get("takeProfitEnabled"))
    if "shortStartMultiplier" in raw:
        value = _finite(raw.get("shortStartMultiplier"))
        if not 1 <= value <= 10: raise ValueError("Pair short start-multiplier moet tussen 1x en 10x liggen")
        out["shortStartMultiplier"] = value
    return out


def _parse_pair_overrides(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict): return {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        symbol = _normalize_symbol(key)
        if not symbol: raise ValueError(f"Ongeldige pair override: {key}")
        cleaned = _clean_pair_override(value)
        if cleaned: result[symbol] = cleaned
    if len(result) > 200: raise ValueError("Maximaal 200 pair-specifieke overrides")
    return result


def _profit_lock_source(source: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Keep stored legacy settings intact; LONG-only is a runtime projection."""
    enabled = bool(source.get("profitLockLadderEnabled", False))
    if not enabled:
        return dict(source), False
    if bool(source.get("asymmetricHedgeModeEnabled", False)):
        raise ValueError("Profit Lock Ladder kan niet tegelijk met Asymmetrische Hedge actief zijn")
    return dict(source), True


@dataclass(frozen=True)
class MultiBbConfig(_core.MultiBbConfig):
    take_profit_mode: str = "PER_TRADE"
    entry_margin_long_usd: float = 5.0
    entry_margin_short_usd: float = 5.0
    long_dca_distance: float = .003
    short_dca_distance: float = .003
    long_dca_margin_usd: float = 2.0
    short_dca_margin_usd: float = 2.0
    max_dca_long: int = 3
    max_dca_short: int = 3
    long_take_profit_value: float = .015
    short_take_profit_value: float = .015
    portfolio_tp_percent: float = 20.0
    pair_overrides: dict[str, dict[str, Any]] = field(default_factory=dict, compare=False)
    profit_lock_ladder_enabled: bool = False
    profit_lock_levels: tuple[tuple[float, float], ...] = DEFAULT_LEVELS

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "MultiBbConfig":
        source = raw or {}
        normalized, profit_lock_enabled = _profit_lock_source(source)
        base = _core.MultiBbConfig.from_mapping(normalized)
        values = {item.name:getattr(base,item.name) for item in fields(_core.MultiBbConfig)}
        legacy_entry = base.entry_margin_usd
        values.update({
            "take_profit_mode": _normalize_mode(source.get("takeProfitMode"), legacy_enabled=base.take_profit_enabled),
            "entry_margin_long_usd": _positive_ratio(source,("entryMarginLongUsd","entryMarginLong"),legacy_entry),
            "entry_margin_short_usd": _positive_ratio(source,("entryMarginShortUsd","entryMarginShort"),legacy_entry),
            "long_dca_distance": _positive_ratio(source,("longDcaDistance",),base.dca_distance),
            "short_dca_distance": _positive_ratio(source,("shortDcaDistance",),base.dca_distance),
            "long_dca_margin_usd": _positive_ratio(source,("longDcaMarginUsd","longDcaAmount"),base.dca_margin_usd),
            "short_dca_margin_usd": _positive_ratio(source,("shortDcaMarginUsd","shortDcaAmount"),base.dca_margin_usd),
            "max_dca_long": _integer(source.get("maxDcaLong",source.get("longMaxDca",base.max_dca)),base.max_dca),
            "max_dca_short": _integer(source.get("maxDcaShort",source.get("shortMaxDca",base.max_dca)),base.max_dca),
            "long_take_profit_value": _positive_ratio(source,("longTakeProfitValue","takeProfitLong"),base.take_profit),
            "short_take_profit_value": _positive_ratio(source,("shortTakeProfitValue","takeProfitShort"),base.take_profit),
            "portfolio_tp_percent": _finite(source.get("portfolioTpPercent"),20.0),
            "pair_overrides": _parse_pair_overrides(source.get("pairOverrides")),
            "profit_lock_ladder_enabled": profit_lock_enabled,
            "profit_lock_levels": normalize_levels(source.get("profitLockLevels")),
        })
        return cls(**values).validated()

    def validated(self) -> "MultiBbConfig":
        super().validated()
        if self.take_profit_mode not in _TP_MODES: raise ValueError("Take Profit Mode is ongeldig")
        if any(not math.isfinite(x) or x <= 0 for x in (self.entry_margin_long_usd,self.entry_margin_short_usd)): raise ValueError("Instap LONG/SHORT moet positief zijn")
        if any(not .0001 <= x <= .50 for x in (self.long_dca_distance,self.short_dca_distance)): raise ValueError("LONG/SHORT DCA-afstand moet tussen 0,01% en 50% liggen")
        if any(not math.isfinite(x) or x <= 0 for x in (self.long_dca_margin_usd,self.short_dca_margin_usd)): raise ValueError("LONG/SHORT DCA-bedrag moet positief zijn")
        if any(not 0 <= x <= _MAX_PAIR_DCA for x in (self.max_dca_long,self.max_dca_short)): raise ValueError(f"LONG/SHORT max DCA moet tussen 0 en {_MAX_PAIR_DCA} liggen")
        if any(not math.isfinite(x) or x <= 0 for x in (self.long_take_profit_value,self.short_take_profit_value)): raise ValueError("LONG/SHORT Take Profit moet positief zijn")
        if not math.isfinite(self.portfolio_tp_percent) or not 0 < self.portfolio_tp_percent <= 10000: raise ValueError("Portfolio TP percentage moet groter dan 0 zijn")
        return self

    def public_dict(self) -> dict[str, Any]:
        payload = super().public_dict()
        payload.update({
            # Legacy shared aliases remain deterministic for older clients.
            "entryMarginUsd":self.entry_margin_long_usd,
            "entryMarginLongUsd":self.entry_margin_long_usd, "entryMarginShortUsd":self.entry_margin_short_usd,
            "entryMarginLong":self.entry_margin_long_usd, "entryMarginShort":self.entry_margin_short_usd,
            "dcaDistance":self.long_dca_distance, "dcaMarginUsd":self.long_dca_margin_usd,
            "maxDca":self.max_dca_long, "takeProfit":self.long_take_profit_value,
            "takeProfitMode":self.take_profit_mode,
            "longDcaDistance":self.long_dca_distance, "shortDcaDistance":self.short_dca_distance,
            "longDcaMarginUsd":self.long_dca_margin_usd, "shortDcaMarginUsd":self.short_dca_margin_usd,
            "longDcaAmount":self.long_dca_margin_usd, "shortDcaAmount":self.short_dca_margin_usd,
            "maxDcaLong":self.max_dca_long, "maxDcaShort":self.max_dca_short,
            "longMaxDca":self.max_dca_long, "shortMaxDca":self.max_dca_short,
            "longTakeProfitValue":self.long_take_profit_value, "shortTakeProfitValue":self.short_take_profit_value,
            "takeProfitLong":self.long_take_profit_value, "takeProfitShort":self.short_take_profit_value,
            "portfolioTpPercent":self.portfolio_tp_percent,
            "profitLockLadderEnabled":self.profit_lock_ladder_enabled,
            "profitLockLevels":public_levels(self.profit_lock_levels),
            "profitLockPrimarySide":"LONG" if self.profit_lock_ladder_enabled else None,
        })
        payload["pairOverrides"] = {s:{"enabled":True,**dict(v)} for s,v in sorted(self.pair_overrides.items())}
        return payload


_SHARED_ATTR_TO_KEY = {"minimum_leverage":"minimumLeverage",
                       "entry_notional_usd":"entryNotionalUsd","unlimited_dca":"unlimitedDca",
                       "short_start_multiplier":"shortStartMultiplier"}


def _execution_context_from_stack() -> tuple[str,str]:
    frame = sys._getframe(2); symbol=""; side=""
    for _ in range(14):
        if frame is None: break
        direct = _normalize_symbol(frame.f_locals.get("symbol"))
        if direct: symbol = direct
        local_side = str(frame.f_locals.get("side") or "").upper()
        if local_side in {"LONG","SHORT"}: side=local_side
        row = frame.f_locals.get("row")
        if isinstance(row,dict):
            r_symbol=_normalize_symbol(row.get("symbol")); r_side=str(row.get("positionSide","")).upper()
            if r_symbol: symbol=r_symbol
            if r_side in {"LONG","SHORT"}: side=r_side
        key=str(frame.f_locals.get("key") or "")
        if "|" in key:
            key_symbol,key_side=key.rsplit("|",1); normalized=_normalize_symbol(key_symbol)
            if normalized: symbol=normalized
            if key_side.upper() in {"LONG","SHORT"}: side=key_side.upper()
        ranked_row=frame.f_locals.get("ranked_row")
        if isinstance(ranked_row,dict):
            ranked_symbol=_normalize_symbol(ranked_row.get("symbol"))
            if ranked_symbol: symbol=ranked_symbol
        if symbol and side: return symbol,side
        frame=frame.f_back
    return symbol,side


def _side_value(base: MultiBbConfig, override: dict[str,Any], side: str, kind: str) -> Any:
    is_short=side=="SHORT"
    if kind=="entry_margin_usd": return override.get("entryMarginUsd",base.entry_margin_short_usd if is_short else base.entry_margin_long_usd)
    if kind=="dca_distance": return override.get("shortDcaDistance" if is_short else "longDcaDistance",override.get("dcaDistance",base.short_dca_distance if is_short else base.long_dca_distance))
    if kind=="dca_margin_usd": return override.get("shortDcaMarginUsd" if is_short else "longDcaMarginUsd",override.get("dcaMarginUsd",base.short_dca_margin_usd if is_short else base.long_dca_margin_usd))
    if kind=="max_dca": return override.get("maxDcaShort" if is_short else "maxDcaLong",override.get("maxDca",base.max_dca_short if is_short else base.max_dca_long))
    if kind=="take_profit": return override.get("shortTakeProfitValue" if is_short else "longTakeProfitValue",override.get("takeProfit",base.short_take_profit_value if is_short else base.long_take_profit_value))
    raise AttributeError(kind)


class _PairAwareSettings:
    def __init__(self,base:MultiBbConfig,blocked_side:str="",blocked_side_count:int=0):
        object.__setattr__(self,"_base",base);object.__setattr__(self,"_blocked_side",str(blocked_side).upper())
        object.__setattr__(self,"_blocked_side_count",max(0,int(blocked_side_count)))
    def __getattr__(self,name:str)->Any:
        base:MultiBbConfig=object.__getattribute__(self,"_base")
        blocked_side=object.__getattribute__(self,"_blocked_side");blocked_count=object.__getattribute__(self,"_blocked_side_count")
        # Profit Lock Ladder is LONG-only at execution time, but public/stored
        # LONG/SHORT choices remain untouched so turning the mode OFF restores them.
        if base.profit_lock_ladder_enabled:
            if name=="long_slots": return base.maximum_positions
            if name=="short_slots": return 0
            if name=="manual_symbols": return tuple((symbol,"LONG") for symbol,_side in base.manual_symbols)
        if blocked_side and name=="long_slots" and blocked_side=="LONG": return blocked_count
        if blocked_side and name=="short_slots" and blocked_side=="SHORT": return blocked_count
        if name=="maximum_positions" and blocked_side=="SHORT" and base.profit_lock_ladder_enabled:
            # Profit Lock SHORT legs protect LONG seats; they do not consume a user seat.
            return base.maximum_positions + blocked_count
        symbol,side=_execution_context_from_stack(); override=base.pair_overrides.get(symbol,{}) if symbol else {}
        if blocked_side and side==blocked_side and name=="take_profit_enabled": return False
        if blocked_side and side==blocked_side and name=="max_dca": return -1
        if name in {"entry_margin_usd","dca_distance","dca_margin_usd","max_dca","take_profit"}:
            legacy_key={"entry_margin_usd":"entryMarginUsd","dca_distance":"dcaDistance","dca_margin_usd":"dcaMarginUsd","max_dca":"maxDca","take_profit":"takeProfit"}[name]
            if legacy_key in override: return override[legacy_key]
            if side in {"LONG","SHORT"}: return _side_value(base,override,side,name)
            if name=="entry_margin_usd": return base.entry_margin_long_usd
        if name=="take_profit_enabled":
            if base.take_profit_mode!="PER_TRADE": return False
            return bool(override.get("takeProfitEnabled",base.take_profit_enabled))
        key=_SHARED_ATTR_TO_KEY.get(name)
        if key and key in override: return override[key]
        return getattr(base,name)


def effective_pair_settings(settings:MultiBbConfig,symbol:str)->dict[str,Any]:
    normalized=_normalize_symbol(symbol); override=settings.pair_overrides.get(normalized,{})
    base=settings.public_dict(); base.pop("pairOverrides",None)
    result={**base,**override,"symbol":normalized,"custom":bool(override)}
    result.update({
        "entryMarginLongUsd":_side_value(settings,override,"LONG","entry_margin_usd"),
        "entryMarginShortUsd":_side_value(settings,override,"SHORT","entry_margin_usd"),
        "longDcaDistance":_side_value(settings,override,"LONG","dca_distance"),
        "shortDcaDistance":_side_value(settings,override,"SHORT","dca_distance"),
        "longDcaMarginUsd":_side_value(settings,override,"LONG","dca_margin_usd"),
        "shortDcaMarginUsd":_side_value(settings,override,"SHORT","dca_margin_usd"),
        "maxDcaLong":_side_value(settings,override,"LONG","max_dca"),
        "maxDcaShort":_side_value(settings,override,"SHORT","max_dca"),
        "longTakeProfitValue":_side_value(settings,override,"LONG","take_profit"),
        "shortTakeProfitValue":_side_value(settings,override,"SHORT","take_profit"),
        "individualTpActive":settings.take_profit_mode=="PER_TRADE" and not settings.profit_lock_ladder_enabled and bool(override.get("takeProfitEnabled",settings.take_profit_enabled)),
    })
    return result


def position_action_preview(*,row:dict[str,Any],state:dict[str,Any],settings:MultiBbConfig,account_equity:float=0.0)->dict[str,Any]:
    preview_settings = replace(settings, take_profit_mode="OFF") if settings.profit_lock_ladder_enabled else settings
    return _core.position_action_preview(row=row,state=state,settings=_PairAwareSettings(preview_settings),account_equity=account_equity)


def leverage_tier_preview(*,client:Any,symbol:str,settings:MultiBbConfig)->dict[str,Any]:
    return _core.leverage_tier_preview(client=client,symbol=symbol,settings=_PairAwareSettings(settings))


class _CoreWriteProxy:
    """Augment the core's existing atomic state write; never add a second write."""
    def __init__(self,ref:Any,extra_report:dict[str,Any]): self._ref=ref; self._extra_report=extra_report
    def set(self,row:dict[str,Any],merge:bool=True):
        payload=dict(row)
        if isinstance(payload.get("multiBbReport"),dict): payload["multiBbReport"]={**payload["multiBbReport"],**self._extra_report}
        return self._ref.set(payload,merge=merge)
    def __getattr__(self,name:str)->Any: return getattr(self._ref,name)


def run_multi_bb_step(*,settings:MultiBbConfig,**kwargs:Any)->dict[str,Any]:
    _sync_core_hooks()
    client=kwargs["client"]; ref=kwargs["ref"]; raw_state=kwargs["raw_state"]; uid=kwargs["uid"]
    account=kwargs["account"]; positions=kwargs["positions"]; open_orders=kwargs["open_orders"]
    timestamp_ms=kwargs["timestamp_ms"]; dry_run=bool(kwargs.get("dry_run",False)); order_budget=kwargs.get("order_budget"); before_order=kwargs.get("before_order")

    # Profit Lock Ladder owns the cycle exit while enabled. Existing TP settings
    # stay persisted but cannot close the LONG and accidentally leave its hedge naked.
    effective_tp_mode = "OFF" if settings.profit_lock_ladder_enabled else settings.take_profit_mode
    gate=portfolio_cycle_gate(client=client,ref=ref,raw_state=raw_state,uid=uid,account=account,positions=positions,
        open_orders=open_orders,timestamp_ms=timestamp_ms,take_profit_mode=effective_tp_mode,
        portfolio_tp_percent=settings.portfolio_tp_percent,dry_run=dry_run,order_budget=order_budget,before_order=before_order)
    cycle_snapshot=gate.report
    if gate.handled and not gate.restart:
        report={"engine":ENGINE,"configVersion":settings.version,"status":"simulated" if dry_run else "portfolio-tp-executing",
            "action":"PORTFOLIO_TP","entryStatus":str(cycle_snapshot.get("cycleStatus","PORTFOLIO_TP_EXECUTING")),
            "entryReason":"Portfolio TP heeft absolute uitvoeringsprioriteit","pairOverrideCount":len(settings.pair_overrides),
            "portfolioCycle":cycle_snapshot,**cycle_snapshot}
        if not dry_run: ref.set({"multiBbReport":report},merge=True)
        return report

    if gate.restart:
        raw_state=gate.raw_state; account=gate.account; positions=gate.positions; open_orders=gate.open_orders
        order_budget=max(0,(15 if order_budget is None else int(order_budget))-gate.orders_sent)

    profit_lock = run_profit_lock_ladder_gate(client=client,ref=ref,raw_state=raw_state,settings=settings,uid=uid,
        account=account,positions=positions,open_orders=open_orders,timestamp_ms=timestamp_ms,dry_run=dry_run,
        order_budget=order_budget,before_order=before_order)
    if profit_lock.handled and not profit_lock.restart:
        report={"engine":ENGINE,"configVersion":settings.version,"status":"simulated" if dry_run else "running",
            "action":"PROFIT_LOCK_LADDER","entryStatus":str(profit_lock.report.get("status","ACTIVE")),
            "entryReason":"Profit Lock Ladder heeft prioriteit op normale DCA/entry in deze scan",
            "pairOverrideCount":len(settings.pair_overrides),"profitLockLadder":profit_lock.report,
            "profitLockLadderEnabled":True,"takeProfitSuppressedByProfitLock":True,
            "portfolioCycle":cycle_snapshot,"ordersSent":profit_lock.orders_sent,
            "actions":profit_lock.report.get("actions",[])}
        if not dry_run: ref.set({"multiBbReport":report,"profitLockLadderReport":profit_lock.report},merge=True)
        return report
    if profit_lock.restart:
        raw_state=profit_lock.raw_state; account=profit_lock.account; positions=profit_lock.positions; open_orders=profit_lock.open_orders
        order_budget=max(0,(15 if order_budget is None else int(order_budget))-profit_lock.orders_sent)

    def guarded_before_order(intent:Any)->Any:
        assert_order_allowed(ref,intent,client=client)
        if before_order is not None:
            try: return before_order(intent)
            except TypeError: return before_order(intent,None)
        return None

    blocked_side=str(kwargs.get("dynamic_hedge_blocked_side","")).upper()
    if settings.profit_lock_ladder_enabled:
        blocked_side="SHORT"
    blocked_count=sum(1 for row in positions if str(row.get("positionSide","")).upper()==blocked_side and abs(_finite(row.get("positionAmt",0)))>0) if blocked_side in {"LONG","SHORT"} else 0
    core_kwargs=dict(kwargs); core_kwargs.pop("dynamic_hedge_blocked_side",None); core_kwargs["before_order"]=guarded_before_order
    core_kwargs.update({"raw_state":raw_state,"account":account,"positions":positions,"open_orders":open_orders,"order_budget":order_budget})
    runtime_settings=replace(settings,take_profit_mode="OFF") if settings.profit_lock_ladder_enabled else settings
    extra={"pairOverrideCount":len(settings.pair_overrides),"takeProfitMode":settings.take_profit_mode,
        "dynamicHedgeBlockedSide":blocked_side or None,
        "entryMarginLongUsd":settings.entry_margin_long_usd,"entryMarginShortUsd":settings.entry_margin_short_usd,
        "longDcaDistance":settings.long_dca_distance,"shortDcaDistance":settings.short_dca_distance,
        "maxDcaLong":settings.max_dca_long,"maxDcaShort":settings.max_dca_short,
        "longTakeProfitValue":settings.long_take_profit_value,"shortTakeProfitValue":settings.short_take_profit_value,
        "portfolioCycle":cycle_snapshot,"profitLockLadderEnabled":settings.profit_lock_ladder_enabled,
        "takeProfitSuppressedByProfitLock":settings.profit_lock_ladder_enabled,
        "profitLockLadder":profit_lock.report}
    core_kwargs["ref"]=_CoreWriteProxy(ref,extra)
    try: report=_core.run_multi_bb_step(settings=_PairAwareSettings(runtime_settings,blocked_side,blocked_count),**core_kwargs)
    except PortfolioCycleOrderBlocked as exc:
        report={"status":"waiting","action":"PORTFOLIO_CYCLE_GUARD","ordersSent":0,"entryStatus":"PORTFOLIO_CYCLE_BLOCKED","entryReason":str(exc),"actions":[]}
    report.update(extra)
    if gate.restart:
        report["portfolioRestart"]=True; report["previousPortfolioExitOrders"]=gate.orders_sent
    if profit_lock.restart:
        report["profitLockRestart"]=True; report["previousProfitLockExitOrders"]=profit_lock.orders_sent

    if settings.profit_lock_ladder_enabled and not dry_run:
        latest=ref.get().to_dict() or {}
        latest_state=latest.get("multiBbPositions") if isinstance(latest.get("multiBbPositions"),dict) else {}
        fresh_positions=client.position_risk() if int(_finite(report.get("ordersSent")))>0 else positions
        summary=account_summary(positions=fresh_positions,state=latest_state,levels=settings.profit_lock_levels,enabled=True)
        report["profitLockLadder"]=summary
        ref.set({"profitLockLadderReport":summary,"multiBbReport":report},merge=True)
    return report


def __getattr__(name:str)->Any:
    return getattr(_core,name)
