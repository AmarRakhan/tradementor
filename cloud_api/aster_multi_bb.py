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
from aster_smart_rescue import (
    SMART_RESCUE_VERSION, DEFAULT_RESCUE_RANGE_PERCENT, DEFAULT_DCA_COUNT,
    DEFAULT_ORDER_GROWTH_MULTIPLIER, DEFAULT_TRAILING_RECOVERY_PERCENT,
    advance_state as advance_smart_rescue_state,
    apply_fill as apply_smart_rescue_fill,
    apply_failure as apply_smart_rescue_failure,
    build_position_state as build_smart_rescue_position_state,
    preview_ladder as smart_rescue_preview_ladder,
    validate_config as validate_smart_rescue_config,
)
from aster_smart_rescue_runtime import active_keys as smart_rescue_active_keys, run_gate as run_smart_rescue_gate
from aster_stop_loss import run_stop_loss_gate

ENGINE = _core.ENGINE
max_contract_leverage = _core.max_contract_leverage
rank_top_volume = _core.rank_top_volume

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}USDT$")
_MAX_PAIR_DCA = 500
_TP_MODES = {"PER_TRADE", "PORTFOLIO", "OFF"}
_PORTFOLIO_TP_INPUT_MODES = {"PERCENT", "USD"}
_PORTFOLIO_TP_BASE_MODES = {"CYCLE_START", "CURRENT_VALUE", "CUSTOM"}
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


def _normalize_portfolio_tp_input_mode(value: Any) -> str:
    text = str(value or "PERCENT").strip().upper().replace("%", "PERCENT").replace("$", "USD")
    if text not in _PORTFOLIO_TP_INPUT_MODES:
        raise ValueError("Portfolio TP invoermodus moet PERCENT of USD zijn")
    return text


def _normalize_portfolio_tp_base_mode(value: Any) -> str:
    text = str(value or "CYCLE_START").strip().upper().replace("-", "_").replace(" ", "_")
    text = {"CYCLE":"CYCLE_START", "CURRENT":"CURRENT_VALUE", "CURRENT_EQUITY":"CURRENT_VALUE",
            "CUSTOM_VALUE":"CUSTOM", "AANGEPAST":"CUSTOM"}.get(text, text)
    if text not in _PORTFOLIO_TP_BASE_MODES:
        raise ValueError("Portfolio TP basis moet CYCLE_START, CURRENT_VALUE of CUSTOM zijn")
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
    entry_notional_long_usd: float = 250.0
    entry_notional_short_usd: float = 250.0
    long_dca_distance: float = .003
    short_dca_distance: float = .003
    long_dca_margin_usd: float = 2.0
    short_dca_margin_usd: float = 2.0
    max_dca_long: int = 3
    max_dca_short: int = 3
    long_take_profit_value: float = .015
    short_take_profit_value: float = .015
    portfolio_tp_percent: float = 20.0
    portfolio_tp_input_mode: str = "PERCENT"
    portfolio_tp_value: float = 20.0
    portfolio_tp_base_mode: str = "CYCLE_START"
    portfolio_tp_custom_base_equity: float = 0.0
    stop_loss_enabled: bool = False
    stop_loss_mode: str = "PERCENT"
    stop_loss_long: float = 0.0
    stop_loss_short: float = 0.0
    pair_overrides: dict[str, dict[str, Any]] = field(default_factory=dict, compare=False)
    profit_lock_ladder_enabled: bool = False
    profit_lock_levels: tuple[tuple[float, float], ...] = DEFAULT_LEVELS
    smart_rescue_enabled: bool = False
    smart_rescue_version: int = SMART_RESCUE_VERSION
    smart_rescue_range_percent: float = DEFAULT_RESCUE_RANGE_PERCENT
    smart_rescue_dca_count: int = DEFAULT_DCA_COUNT
    smart_rescue_order_growth_multiplier: float = DEFAULT_ORDER_GROWTH_MULTIPLIER
    smart_rescue_trailing_recovery_percent: float = DEFAULT_TRAILING_RECOVERY_PERCENT

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "MultiBbConfig":
        source = raw or {}
        normalized, profit_lock_enabled = _profit_lock_source(source)
        base = _core.MultiBbConfig.from_mapping(normalized)
        values = {item.name:getattr(base,item.name) for item in fields(_core.MultiBbConfig)}
        legacy_entry = base.entry_margin_usd
        legacy_portfolio_tp = _finite(source.get("portfolioTpPercent"), 20.0)
        portfolio_tp_input_mode = _normalize_portfolio_tp_input_mode(source.get("portfolioTpInputMode"))
        portfolio_tp_value = _finite(source.get("portfolioTpValue"), legacy_portfolio_tp if portfolio_tp_input_mode == "PERCENT" else 5.0)
        portfolio_tp_base_mode = _normalize_portfolio_tp_base_mode(source.get("portfolioTpBaseMode"))
        values.update({
            "take_profit_mode": _normalize_mode(source.get("takeProfitMode"), legacy_enabled=base.take_profit_enabled),
            "entry_margin_long_usd": _positive_ratio(source,("entryMarginLongUsd","entryMarginLong"),legacy_entry),
            "entry_margin_short_usd": _positive_ratio(source,("entryMarginShortUsd","entryMarginShort"),legacy_entry),
            "entry_notional_long_usd": _positive_ratio(source,("entryNotionalLongUsd","entryNotionalLong","entryNotionalUsd"),base.entry_notional_usd),
            "entry_notional_short_usd": _positive_ratio(source,("entryNotionalShortUsd","entryNotionalShort"),base.entry_notional_usd),
            "long_dca_distance": _positive_ratio(source,("longDcaDistance",),base.dca_distance),
            "short_dca_distance": _positive_ratio(source,("shortDcaDistance",),base.dca_distance),
            "long_dca_margin_usd": _positive_ratio(source,("longDcaMarginUsd","longDcaAmount"),base.dca_margin_usd),
            "short_dca_margin_usd": _positive_ratio(source,("shortDcaMarginUsd","shortDcaAmount"),base.dca_margin_usd),
            "max_dca_long": _integer(source.get("maxDcaLong",source.get("longMaxDca",base.max_dca)),base.max_dca),
            "max_dca_short": _integer(source.get("maxDcaShort",source.get("shortMaxDca",base.max_dca)),base.max_dca),
            "long_take_profit_value": _positive_ratio(source,("longTakeProfitValue","takeProfitLong"),base.take_profit),
            "short_take_profit_value": _positive_ratio(source,("shortTakeProfitValue","takeProfitShort"),base.take_profit),
            "portfolio_tp_percent": legacy_portfolio_tp,
            "portfolio_tp_input_mode": portfolio_tp_input_mode,
            "portfolio_tp_value": portfolio_tp_value,
            "portfolio_tp_base_mode": portfolio_tp_base_mode,
            "portfolio_tp_custom_base_equity": _finite(source.get("portfolioTpCustomBaseEquity"), 0.0),
            "stop_loss_enabled": bool(source.get("stopLossEnabled", False)),
            "stop_loss_mode": str(source.get("stopLossMode", "PERCENT")).strip().upper().replace("%", "PERCENT").replace("$", "USD"),
            "stop_loss_long": _finite(source.get("stopLossLong"), 0.0),
            "stop_loss_short": _finite(source.get("stopLossShort"), 0.0),
            "pair_overrides": _parse_pair_overrides(source.get("pairOverrides")),
            "profit_lock_ladder_enabled": profit_lock_enabled,
            "profit_lock_levels": normalize_levels(source.get("profitLockLevels")),
            "smart_rescue_enabled": bool(source.get("smartRescueEnabled", False)),
            "smart_rescue_version": max(1, _integer(source.get("smartRescueVersion"), SMART_RESCUE_VERSION)),
            "smart_rescue_range_percent": _finite(source.get("smartRescueRangePercent"), DEFAULT_RESCUE_RANGE_PERCENT),
            "smart_rescue_dca_count": _integer(source.get("smartRescueDcaCount"), DEFAULT_DCA_COUNT),
            "smart_rescue_order_growth_multiplier": _finite(source.get("smartRescueOrderGrowthMultiplier"), DEFAULT_ORDER_GROWTH_MULTIPLIER),
            "smart_rescue_trailing_recovery_percent": _finite(source.get("smartRescueTrailingRecoveryPercent"), DEFAULT_TRAILING_RECOVERY_PERCENT),
        })
        return cls(**values).validated()

    def validated(self) -> "MultiBbConfig":
        super().validated()
        if self.take_profit_mode not in _TP_MODES: raise ValueError("Take Profit Mode is ongeldig")
        if any(not math.isfinite(x) or x <= 0 for x in (self.entry_margin_long_usd,self.entry_margin_short_usd)): raise ValueError("Instapmargin LONG/SHORT moet positief zijn")
        if any(not math.isfinite(x) or x <= 0 for x in (self.entry_notional_long_usd,self.entry_notional_short_usd)): raise ValueError("Positieomvang LONG/SHORT moet positief zijn")
        if any(not .0001 <= x <= .50 for x in (self.long_dca_distance,self.short_dca_distance)): raise ValueError("LONG/SHORT DCA-afstand moet tussen 0,01% en 50% liggen")
        if any(not math.isfinite(x) or x <= 0 for x in (self.long_dca_margin_usd,self.short_dca_margin_usd)): raise ValueError("LONG/SHORT DCA-bedrag moet positief zijn")
        if any(not 0 <= x <= _MAX_PAIR_DCA for x in (self.max_dca_long,self.max_dca_short)): raise ValueError(f"LONG/SHORT max DCA moet tussen 0 en {_MAX_PAIR_DCA} liggen")
        if any(not math.isfinite(x) or x <= 0 for x in (self.long_take_profit_value,self.short_take_profit_value)): raise ValueError("LONG/SHORT Take Profit moet positief zijn")
        if self.portfolio_tp_input_mode not in _PORTFOLIO_TP_INPUT_MODES: raise ValueError("Portfolio TP invoermodus is ongeldig")
        if self.portfolio_tp_base_mode not in _PORTFOLIO_TP_BASE_MODES: raise ValueError("Portfolio TP basis is ongeldig")
        if not math.isfinite(self.portfolio_tp_value) or self.portfolio_tp_value <= 0: raise ValueError("Portfolio TP moet groter dan 0 zijn")
        if self.portfolio_tp_input_mode == "PERCENT" and self.portfolio_tp_value > 10000: raise ValueError("Portfolio TP percentage mag maximaal 10.000% zijn")
        if self.portfolio_tp_input_mode == "USD" and self.portfolio_tp_value > 1_000_000_000: raise ValueError("Portfolio TP bedrag is te groot")
        if self.portfolio_tp_base_mode == "CUSTOM" and (not math.isfinite(self.portfolio_tp_custom_base_equity) or self.portfolio_tp_custom_base_equity <= 0): raise ValueError("Aangepaste Portfolio TP basis moet groter dan 0 zijn")
        if self.stop_loss_mode not in {"USD","PERCENT"}: raise ValueError("Stoploss type moet USD of PERCENT zijn")
        if self.stop_loss_enabled and (not math.isfinite(self.stop_loss_long) or self.stop_loss_long <= 0 or not math.isfinite(self.stop_loss_short) or self.stop_loss_short <= 0): raise ValueError("Stoploss LONG en SHORT moeten groter dan 0 zijn wanneer Stoploss aan staat")
        if self.smart_rescue_enabled:
            validate_smart_rescue_config(
                rescue_range_percent=self.smart_rescue_range_percent,
                dca_count=self.smart_rescue_dca_count,
                order_growth_multiplier=self.smart_rescue_order_growth_multiplier,
                trailing_recovery_percent=self.smart_rescue_trailing_recovery_percent,
            )
        if self.smart_rescue_enabled and self.asymmetric_hedge_enabled:
            raise ValueError("Smart Rescue DCA kan niet tegelijk met Asymmetrische Hedge actief zijn")
        if self.smart_rescue_enabled and self.profit_lock_ladder_enabled:
            raise ValueError("Smart Rescue DCA en Profit Lock Ladder zijn twee verschillende LONG-modi en kunnen niet tegelijk actief zijn")
        return self

    def public_dict(self) -> dict[str, Any]:
        payload = super().public_dict()
        payload.update({
            # Legacy shared aliases remain deterministic for older clients.
            "entryMarginUsd":self.entry_margin_long_usd,
            "entryMarginLongUsd":self.entry_margin_long_usd, "entryMarginShortUsd":self.entry_margin_short_usd,
            "entryMarginLong":self.entry_margin_long_usd, "entryMarginShort":self.entry_margin_short_usd,
            "entryNotionalUsd":self.entry_notional_long_usd,
            "entryNotionalLongUsd":self.entry_notional_long_usd, "entryNotionalShortUsd":self.entry_notional_short_usd,
            "entryNotionalLong":self.entry_notional_long_usd, "entryNotionalShort":self.entry_notional_short_usd,
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
            "portfolioTpPercent":self.portfolio_tp_value if self.portfolio_tp_input_mode=="PERCENT" else self.portfolio_tp_percent,
            "portfolioTpInputMode":self.portfolio_tp_input_mode,
            "portfolioTpValue":self.portfolio_tp_value,
            "portfolioTpBaseMode":self.portfolio_tp_base_mode,
            "portfolioTpCustomBaseEquity":self.portfolio_tp_custom_base_equity,
            "stopLossEnabled":self.stop_loss_enabled,
            "stopLossMode":self.stop_loss_mode,
            "stopLossLong":self.stop_loss_long,
            "stopLossShort":self.stop_loss_short,
            "profitLockLadderEnabled":self.profit_lock_ladder_enabled,
            "profitLockLevels":public_levels(self.profit_lock_levels),
            "profitLockPrimarySide":"LONG" if self.profit_lock_ladder_enabled else None,
            "smartRescueEnabled":self.smart_rescue_enabled,
            "smartRescueVersion":self.smart_rescue_version,
            "smartRescueRangePercent":self.smart_rescue_range_percent,
            "smartRescueDcaCount":self.smart_rescue_dca_count,
            "smartRescueOrderGrowthMultiplier":self.smart_rescue_order_growth_multiplier,
            "smartRescueTrailingRecoveryPercent":self.smart_rescue_trailing_recovery_percent,
            "smartRescuePrimarySide":"LONG" if self.smart_rescue_enabled else None,
        })
        payload["pairOverrides"] = {s:{"enabled":True,**dict(v)} for s,v in sorted(self.pair_overrides.items())}
        return payload


_SHARED_ATTR_TO_KEY = {"minimum_leverage":"minimumLeverage",
                       "unlimited_dca":"unlimitedDca",
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
    if kind=="entry_notional_usd":
        side_key="entryNotionalShortUsd" if is_short else "entryNotionalLongUsd"
        legacy_key="entryNotionalShort" if is_short else "entryNotionalLong"
        fallback=base.entry_notional_short_usd if is_short else base.entry_notional_long_usd
        return override.get(side_key,override.get(legacy_key,override.get("entryNotionalUsd",fallback)))
    if kind=="dca_distance": return override.get("shortDcaDistance" if is_short else "longDcaDistance",override.get("dcaDistance",base.short_dca_distance if is_short else base.long_dca_distance))
    if kind=="dca_margin_usd": return override.get("shortDcaMarginUsd" if is_short else "longDcaMarginUsd",override.get("dcaMarginUsd",base.short_dca_margin_usd if is_short else base.long_dca_margin_usd))
    if kind=="max_dca": return override.get("maxDcaShort" if is_short else "maxDcaLong",override.get("maxDca",base.max_dca_short if is_short else base.max_dca_long))
    if kind=="take_profit": return override.get("shortTakeProfitValue" if is_short else "longTakeProfitValue",override.get("takeProfit",base.short_take_profit_value if is_short else base.long_take_profit_value))
    raise AttributeError(kind)


class _PairAwareSettings:
    def __init__(self,base:MultiBbConfig,blocked_side:str="",blocked_side_count:int=0,smart_rescue_keys:set[str]|None=None):
        object.__setattr__(self,"_base",base);object.__setattr__(self,"_blocked_side",str(blocked_side).upper())
        object.__setattr__(self,"_blocked_side_count",max(0,int(blocked_side_count)))
        object.__setattr__(self,"_smart_rescue_keys",set(smart_rescue_keys or set()))
    def __getattr__(self,name:str)->Any:
        base:MultiBbConfig=object.__getattribute__(self,"_base")
        blocked_side=object.__getattribute__(self,"_blocked_side");blocked_count=object.__getattribute__(self,"_blocked_side_count")
        smart_keys:set[str]=object.__getattribute__(self,"_smart_rescue_keys")
        # Profit Lock Ladder is LONG-only at execution time, but public/stored
        # LONG/SHORT choices remain untouched so turning the mode OFF restores them.
        if base.profit_lock_ladder_enabled:
            if name=="long_slots": return base.maximum_positions
            if name=="short_slots": return 0
            if name=="manual_symbols": return tuple((symbol,"LONG") for symbol,_side in base.manual_symbols)
        if base.smart_rescue_enabled:
            if name=="long_slots": return base.maximum_positions
            if name=="short_slots": return 0
            if name=="manual_symbols": return tuple((symbol,"LONG") for symbol,_side in base.manual_symbols)
        if blocked_side and name=="long_slots" and blocked_side=="LONG": return blocked_count
        if blocked_side and name=="short_slots" and blocked_side=="SHORT": return blocked_count
        if name=="maximum_positions" and blocked_side=="SHORT" and base.profit_lock_ladder_enabled:
            # Profit Lock SHORT legs protect LONG seats; they do not consume a user seat.
            return base.maximum_positions + blocked_count
        symbol,side=_execution_context_from_stack(); override=base.pair_overrides.get(symbol,{}) if symbol else {}
        active_key=f"{symbol}|{side}" if symbol and side else ""
        if active_key in smart_keys and name=="max_dca": return 0
        if active_key in smart_keys and name=="unlimited_dca": return False
        if blocked_side and side==blocked_side and name=="take_profit_enabled": return False
        if blocked_side and side==blocked_side and name=="max_dca": return -1
        if name in {"entry_margin_usd","entry_notional_usd","dca_distance","dca_margin_usd","max_dca","take_profit"}:
            legacy_key={"entry_margin_usd":"entryMarginUsd","entry_notional_usd":"entryNotionalUsd","dca_distance":"dcaDistance","dca_margin_usd":"dcaMarginUsd","max_dca":"maxDca","take_profit":"takeProfit"}[name]
            if legacy_key in override: return override[legacy_key]
            if side in {"LONG","SHORT"}: return _side_value(base,override,side,name)
            if name=="entry_margin_usd": return base.entry_margin_long_usd
            if name=="entry_notional_usd": return base.entry_notional_long_usd
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
        "entryNotionalLongUsd":_side_value(settings,override,"LONG","entry_notional_usd"),
        "entryNotionalShortUsd":_side_value(settings,override,"SHORT","entry_notional_usd"),
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


class _ExactStateMapRef:
    """Keep ``multiBbPositions`` as an exact snapshot, not a recursive map merge.

    Firestore ``set(..., merge=True)`` recursively merges nested maps.  The
    runtime treats ``multiBbPositions`` as a complete snapshot: removed legs
    must disappear and fresh cycles must not inherit nested fields from an old
    cycle.  Merging the explicit top-level field paths preserves the normal
    sibling-field merge while replacing this map value atomically.
    """
    def __init__(self, ref: Any): self._ref = ref
    def set(self, row: dict[str, Any], merge: Any = True):
        payload = dict(row)
        if merge is True and "multiBbPositions" in payload:
            return self._ref.set(payload, merge=list(payload.keys()))
        return self._ref.set(payload, merge=merge)
    def __getattr__(self, name: str) -> Any: return getattr(self._ref, name)


class _CoreWriteProxy:
    """Augment core writes and atomically stamp new Smart Rescue LONG cycles."""
    def __init__(self,ref:Any,extra_report:dict[str,Any],settings:MultiBbConfig|None=None,timestamp_ms:int=0):
        self._ref=ref; self._extra_report=extra_report; self._settings=settings; self._timestamp_ms=int(timestamp_ms)
        self._smart_started_keys:set[str]=set()
    def _stamp_smart_rescue(self,payload:dict[str,Any])->None:
        settings=self._settings
        if settings is None or not settings.smart_rescue_enabled or not isinstance(payload.get("multiBbPositions"),dict): return
        state=dict(payload["multiBbPositions"]); changed=False
        # Detect only genuinely new LONG cycles created in this execution tick.
        # Existing/adopted/recovered positions must never be retrofitted merely
        # because the user enabled Smart Rescue while they were already open.
        for key,row in state.items():
            if not str(key).endswith("|LONG") or not isinstance(row,dict): continue
            if isinstance(row.get("smartRescue"),dict): continue
            if _integer(row.get("cycleStartedAtMs")) != self._timestamp_ms: continue
            if row.get("adoptedExisting") or row.get("recoveredFromSelectedOpenPosition"): continue
            self._smart_started_keys.add(str(key))
        for key in tuple(self._smart_started_keys):
            row=state.get(key)
            if not isinstance(row,dict) or isinstance(row.get("smartRescue"),dict): continue
            entry=_finite(row.get("lastKnownEntry"),_finite(row.get("lastBotFillPrice")))
            if entry<=0: continue
            updated=dict(row)
            leverage=max(1,_integer(row.get("leverage"),settings.minimum_leverage))
            start_margin=(settings.entry_notional_long_usd/leverage
                if settings.entry_sizing_mode=="notional" else settings.entry_margin_long_usd)
            updated["smartRescue"]=build_smart_rescue_position_state(
                initial_entry_price=entry,start_margin_usd=start_margin,
                rescue_range_percent=settings.smart_rescue_range_percent,dca_count=settings.smart_rescue_dca_count,
                order_growth_multiplier=settings.smart_rescue_order_growth_multiplier,
                trailing_recovery_percent=settings.smart_rescue_trailing_recovery_percent,
                config_version=settings.version)
            updated["smartRescueStartedAtMs"]=self._timestamp_ms
            state[key]=updated; changed=True
        if changed: payload["multiBbPositions"]=state
    def set(self,row:dict[str,Any],merge:bool=True):
        payload=dict(row); self._stamp_smart_rescue(payload)
        if isinstance(payload.get("multiBbReport"),dict): payload["multiBbReport"]={**payload["multiBbReport"],**self._extra_report}
        return self._ref.set(payload,merge=merge)
    def __getattr__(self,name:str)->Any: return getattr(self._ref,name)


def run_multi_bb_step(*,settings:MultiBbConfig,**kwargs:Any)->dict[str,Any]:
    _sync_core_hooks()
    client=kwargs["client"]; ref=kwargs["ref"]; runtime_ref=_ExactStateMapRef(ref); raw_state=kwargs["raw_state"]; uid=kwargs["uid"]
    account=kwargs["account"]; positions=kwargs["positions"]; open_orders=kwargs["open_orders"]
    timestamp_ms=kwargs["timestamp_ms"]; dry_run=bool(kwargs.get("dry_run",False)); order_budget=kwargs.get("order_budget"); before_order=kwargs.get("before_order")

    def guarded_before_order(intent:Any)->Any:
        assert_order_allowed(runtime_ref,intent,client=client)
        if before_order is not None:
            try: return before_order(intent)
            except TypeError: return before_order(intent,None)
        return None

    # User-configured Stoploss is the safety exit and therefore evaluates before
    # Portfolio TP, Profit Lock, Smart Rescue, normal TP, DCA and refill.
    stop_loss = run_stop_loss_gate(
        client=client, ref=runtime_ref, raw_state=raw_state, settings=settings, uid=uid,
        account=account, positions=positions, open_orders=open_orders, timestamp_ms=timestamp_ms,
        dry_run=dry_run, order_budget=order_budget, before_order=guarded_before_order,
    )
    if stop_loss.handled:
        report={"engine":ENGINE,"configVersion":settings.version,"status":"simulated" if dry_run else "running",
            "action":"STOP_LOSS","entryStatus":str(stop_loss.report.get("status","WAITING")),
            "entryReason":"Stoploss heeft absolute safety-prioriteit op TP, DCA en nieuwe entries",
            "ordersSent":stop_loss.orders_sent,"actions":stop_loss.report.get("actions",[]),
            "stopLoss":stop_loss.report,"stopLossEnabled":True}
        if not dry_run: ref.set({"multiBbReport":report,"stopLossReport":stop_loss.report},merge=True)
        return report

    # Profit Lock Ladder owns the cycle exit while enabled. Existing TP settings
    # stay persisted but cannot close the LONG and accidentally leave its hedge naked.
    effective_tp_mode = "OFF" if settings.profit_lock_ladder_enabled else settings.take_profit_mode
    gate=portfolio_cycle_gate(client=client,ref=runtime_ref,raw_state=raw_state,uid=uid,account=account,positions=positions,
        open_orders=open_orders,timestamp_ms=timestamp_ms,take_profit_mode=effective_tp_mode,
        portfolio_tp_percent=settings.portfolio_tp_percent,portfolio_tp_input_mode=settings.portfolio_tp_input_mode,
        portfolio_tp_value=settings.portfolio_tp_value,portfolio_tp_base_mode=settings.portfolio_tp_base_mode,
        portfolio_tp_custom_base_equity=settings.portfolio_tp_custom_base_equity,config_version=settings.version,
        dry_run=dry_run,order_budget=order_budget,before_order=before_order)
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

    profit_lock = run_profit_lock_ladder_gate(client=client,ref=runtime_ref,raw_state=raw_state,settings=settings,uid=uid,
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

    smart_rescue=run_smart_rescue_gate(client=client,ref=runtime_ref,raw_state=raw_state,settings=settings,uid=uid,
        account=account,positions=positions,open_orders=open_orders,timestamp_ms=timestamp_ms,dry_run=dry_run,
        order_budget=order_budget,before_order=guarded_before_order)
    if smart_rescue.get("stateChanged"):
        raw_state={**raw_state,"multiBbPositions":smart_rescue.get("state",raw_state.get("multiBbPositions",{}))}
    if smart_rescue.get("handled"):
        report={"engine":ENGINE,"configVersion":settings.version,"status":"simulated" if dry_run else "running",
            "action":"SMART_RESCUE_DCA","entryStatus":"SMART_RESCUE_EXECUTED" if not dry_run else "SMART_RESCUE_SIMULATED",
            "entryReason":"Smart Rescue trailing-herstel activeerde maximaal één rescue per positie",
            "ordersSent":int(smart_rescue.get("ordersSent",0)),"actions":smart_rescue.get("actions",[]),
            "smartRescue":smart_rescue,"portfolioCycle":cycle_snapshot}
        if not dry_run: ref.set({"multiBbReport":report},merge=True)
        return report

    blocked_side=str(kwargs.get("dynamic_hedge_blocked_side","")).upper()
    if settings.profit_lock_ladder_enabled:
        blocked_side="SHORT"
    blocked_count=sum(1 for row in positions if str(row.get("positionSide","")).upper()==blocked_side and abs(_finite(row.get("positionAmt",0)))>0) if blocked_side in {"LONG","SHORT"} else 0
    core_kwargs=dict(kwargs); core_kwargs.pop("dynamic_hedge_blocked_side",None); core_kwargs["before_order"]=guarded_before_order
    core_kwargs.update({"raw_state":raw_state,"account":account,"positions":positions,"open_orders":open_orders,"order_budget":order_budget})
    smart_keys=smart_rescue_active_keys(raw_state)
    runtime_settings=replace(settings,take_profit_mode="OFF") if settings.profit_lock_ladder_enabled else settings
    extra={"pairOverrideCount":len(settings.pair_overrides),"takeProfitMode":settings.take_profit_mode,
        "dynamicHedgeBlockedSide":blocked_side or None,
        "entryMarginLongUsd":settings.entry_margin_long_usd,"entryMarginShortUsd":settings.entry_margin_short_usd,
        "longDcaDistance":settings.long_dca_distance,"shortDcaDistance":settings.short_dca_distance,
        "maxDcaLong":settings.max_dca_long,"maxDcaShort":settings.max_dca_short,
        "longTakeProfitValue":settings.long_take_profit_value,"shortTakeProfitValue":settings.short_take_profit_value,
        "portfolioCycle":cycle_snapshot,"profitLockLadderEnabled":settings.profit_lock_ladder_enabled,
        "takeProfitSuppressedByProfitLock":settings.profit_lock_ladder_enabled,
        "profitLockLadder":profit_lock.report,
        "smartRescueEnabled":settings.smart_rescue_enabled,
        "smartRescueRangePercent":settings.smart_rescue_range_percent,
        "smartRescueDcaCount":settings.smart_rescue_dca_count,
        "smartRescueOrderGrowthMultiplier":settings.smart_rescue_order_growth_multiplier,
        "smartRescueTrailingRecoveryPercent":settings.smart_rescue_trailing_recovery_percent,
        "stopLossEnabled":settings.stop_loss_enabled,"stopLossMode":settings.stop_loss_mode,
        "stopLossLong":settings.stop_loss_long,"stopLossShort":settings.stop_loss_short,
        "maximumLeverage":settings.maximum_leverage}
    core_kwargs["ref"]=_CoreWriteProxy(runtime_ref,extra,settings=settings,timestamp_ms=timestamp_ms)
    try: report=_core.run_multi_bb_step(settings=_PairAwareSettings(runtime_settings,blocked_side,blocked_count,smart_keys),**core_kwargs)
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
