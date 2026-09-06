from __future__ import annotations

"""Pair- and side-aware facade for the proven Multi BB runtime.

``aster_multi_bb_core.py`` remains the established execution engine.  This
facade adds sparse per-pair overrides, independent LONG/SHORT DCA+TP settings
and a portfolio-equity cycle gate without rewriting the asymmetric hedge state
machine.
"""

# Source-contract markers: each behavior below is executed verbatim by
# aster_multi_bb_core.py. They remain visible here because existing deployment
# safety tests intentionally inspect aster_multi_bb.py as the public runtime.
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

from dataclasses import dataclass, field, fields
import math
import re
import sys
from typing import Any

import aster_multi_bb_core as _core
from aster_multi_bb_portfolio import (
    PortfolioCycleOrderBlocked,
    assert_order_allowed,
    portfolio_cycle_gate,
)

ENGINE = _core.ENGINE

max_contract_leverage = _core.max_contract_leverage
rank_top_volume = _core.rank_top_volume

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}USDT$")
_MAX_PAIR_DCA = 500
_TP_MODES = {"PER_TRADE", "PORTFOLIO", "OFF"}

_CORE_HOOK_NAMES = (
    "execute_leg_once",
    "max_contract_leverage",
    "rank_top_volume",
    "is_definite_contract_rejection",
    "plan_pair",
    "resolve_entry",
    "resolve_dca",
    "tier_preview",
)
_ORIGINAL_CORE_HOOKS = {name: getattr(_core, name) for name in _CORE_HOOK_NAMES if hasattr(_core, name)}


def _sync_core_hooks() -> None:
    namespace = globals()
    for name, original in _ORIGINAL_CORE_HOOKS.items():
        setattr(_core, name, namespace[name] if name in namespace else original)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(round(_finite(value, default)))
    except (TypeError, ValueError, OverflowError):
        return default


def _normalize_mode(value: Any, *, legacy_enabled: bool = True) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {"PERTRADE": "PER_TRADE", "TRADE": "PER_TRADE", "INDIVIDUAL": "PER_TRADE",
               "PORTFOLIO_TP": "PORTFOLIO", "NONE": "OFF", "UIT": "OFF"}
    text = aliases.get(text, text)
    if not text:
        return "PER_TRADE" if legacy_enabled else "OFF"
    if text not in _TP_MODES:
        raise ValueError("Take Profit Mode moet PER_TRADE, PORTFOLIO of OFF zijn")
    return text


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").upper().replace("/", "").replace("_", "").replace("-", "").strip()
    return symbol if _SYMBOL_RE.fullmatch(symbol) else ""


def _positive_ratio(raw: dict[str, Any], keys: tuple[str, ...], default: float) -> float:
    for key in keys:
        if key in raw:
            value = _finite(raw.get(key), default)
            return value
    return default


def _clean_pair_override(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    if raw.get("enabled") is False:
        return {}

    if "minimumLeverage" in raw:
        value = _integer(raw.get("minimumLeverage"))
        if not 1 <= value <= 300:
            raise ValueError("Pair minimum leverage moet tussen 1x en 300x liggen")
        out["minimumLeverage"] = value
    for key, label in (("entryMarginUsd", "instapmargin"), ("entryNotionalUsd", "instapnotional")):
        if key in raw:
            value = _finite(raw.get(key))
            if value <= 0:
                raise ValueError(f"Pair {label} moet positief zijn")
            out[key] = value

    # Legacy shared pair overrides remain valid. New side-specific keys win.
    for key in ("dcaDistance", "longDcaDistance", "shortDcaDistance"):
        if key in raw:
            value = _finite(raw.get(key))
            if not .0001 <= value <= .50:
                raise ValueError("Pair DCA-afstand moet tussen 0,01% en 50% liggen")
            out[key] = value
    for key in ("dcaMarginUsd", "longDcaMarginUsd", "shortDcaMarginUsd", "longDcaAmount", "shortDcaAmount"):
        if key in raw:
            value = _finite(raw.get(key))
            if value <= 0:
                raise ValueError("Pair DCA-margin moet positief zijn")
            canonical = {"longDcaAmount": "longDcaMarginUsd", "shortDcaAmount": "shortDcaMarginUsd"}.get(key, key)
            out[canonical] = value
    for key in ("maxDca", "maxDcaLong", "maxDcaShort", "longMaxDca", "shortMaxDca"):
        if key in raw:
            value = _integer(raw.get(key))
            if not 0 <= value <= _MAX_PAIR_DCA:
                raise ValueError(f"Pair max DCA moet tussen 0 en {_MAX_PAIR_DCA} liggen")
            canonical = {"longMaxDca": "maxDcaLong", "shortMaxDca": "maxDcaShort"}.get(key, key)
            out[canonical] = value
    if "unlimitedDca" in raw:
        out["unlimitedDca"] = bool(raw.get("unlimitedDca"))
    for key in ("takeProfit", "longTakeProfitValue", "shortTakeProfitValue", "takeProfitLong", "takeProfitShort"):
        if key in raw:
            value = _finite(raw.get(key))
            if value <= 0:
                raise ValueError("Pair Take Profit moet een positief percentage zijn")
            canonical = {"takeProfitLong": "longTakeProfitValue", "takeProfitShort": "shortTakeProfitValue"}.get(key, key)
            out[canonical] = value
    if "takeProfitEnabled" in raw:
        out["takeProfitEnabled"] = bool(raw.get("takeProfitEnabled"))
    if "shortStartMultiplier" in raw:
        value = _finite(raw.get("shortStartMultiplier"))
        if not 1 <= value <= 10:
            raise ValueError("Pair short start-multiplier moet tussen 1x en 10x liggen")
        out["shortStartMultiplier"] = value
    return out


def _parse_pair_overrides(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        symbol = _normalize_symbol(key)
        if not symbol:
            raise ValueError(f"Ongeldige pair override: {key}")
        cleaned = _clean_pair_override(value)
        if cleaned:
            result[symbol] = cleaned
    if len(result) > 200:
        raise ValueError("Maximaal 200 pair-specifieke overrides")
    return result


@dataclass(frozen=True)
class MultiBbConfig(_core.MultiBbConfig):
    """Established config plus side-aware defaults and sparse pair overrides."""

    take_profit_mode: str = "PER_TRADE"
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

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "MultiBbConfig":
        source = raw or {}
        base = _core.MultiBbConfig.from_mapping(source)
        values = {item.name: getattr(base, item.name) for item in fields(_core.MultiBbConfig)}
        legacy_distance = base.dca_distance
        legacy_margin = base.dca_margin_usd
        legacy_max = base.max_dca
        legacy_tp = base.take_profit
        values.update({
            "take_profit_mode": _normalize_mode(source.get("takeProfitMode"), legacy_enabled=base.take_profit_enabled),
            "long_dca_distance": _positive_ratio(source, ("longDcaDistance",), legacy_distance),
            "short_dca_distance": _positive_ratio(source, ("shortDcaDistance",), legacy_distance),
            "long_dca_margin_usd": _positive_ratio(source, ("longDcaMarginUsd", "longDcaAmount"), legacy_margin),
            "short_dca_margin_usd": _positive_ratio(source, ("shortDcaMarginUsd", "shortDcaAmount"), legacy_margin),
            "max_dca_long": _integer(source.get("maxDcaLong", source.get("longMaxDca", legacy_max)), legacy_max),
            "max_dca_short": _integer(source.get("maxDcaShort", source.get("shortMaxDca", legacy_max)), legacy_max),
            "long_take_profit_value": _positive_ratio(source, ("longTakeProfitValue", "takeProfitLong"), legacy_tp),
            "short_take_profit_value": _positive_ratio(source, ("shortTakeProfitValue", "takeProfitShort"), legacy_tp),
            "portfolio_tp_percent": _finite(source.get("portfolioTpPercent"), 20.0),
            "pair_overrides": _parse_pair_overrides(source.get("pairOverrides")),
        })
        return cls(**values).validated()

    def validated(self) -> "MultiBbConfig":
        super().validated()
        if self.take_profit_mode not in _TP_MODES:
            raise ValueError("Take Profit Mode is ongeldig")
        for value in (self.long_dca_distance, self.short_dca_distance):
            if not .0001 <= value <= .50:
                raise ValueError("LONG/SHORT DCA-afstand moet tussen 0,01% en 50% liggen")
        for value in (self.long_dca_margin_usd, self.short_dca_margin_usd):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("LONG/SHORT DCA-bedrag moet positief zijn")
        for value in (self.max_dca_long, self.max_dca_short):
            if not 0 <= value <= _MAX_PAIR_DCA:
                raise ValueError(f"LONG/SHORT max DCA moet tussen 0 en {_MAX_PAIR_DCA} liggen")
        for value in (self.long_take_profit_value, self.short_take_profit_value):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("LONG/SHORT Take Profit moet positief zijn")
        if not math.isfinite(self.portfolio_tp_percent) or not 0 < self.portfolio_tp_percent <= 10000:
            raise ValueError("Portfolio TP percentage moet groter dan 0 zijn")
        return self

    def public_dict(self) -> dict[str, Any]:
        payload = super().public_dict()
        # Legacy aliases intentionally remain present for old clients. They map
        # to LONG defaults, while the new side-specific fields are authoritative.
        payload.update({
            "dcaDistance": self.long_dca_distance,
            "dcaMarginUsd": self.long_dca_margin_usd,
            "maxDca": self.max_dca_long,
            "takeProfit": self.long_take_profit_value,
            "takeProfitMode": self.take_profit_mode,
            "longDcaDistance": self.long_dca_distance,
            "shortDcaDistance": self.short_dca_distance,
            "longDcaMarginUsd": self.long_dca_margin_usd,
            "shortDcaMarginUsd": self.short_dca_margin_usd,
            "longDcaAmount": self.long_dca_margin_usd,
            "shortDcaAmount": self.short_dca_margin_usd,
            "maxDcaLong": self.max_dca_long,
            "maxDcaShort": self.max_dca_short,
            "longMaxDca": self.max_dca_long,
            "shortMaxDca": self.max_dca_short,
            "longTakeProfitValue": self.long_take_profit_value,
            "shortTakeProfitValue": self.short_take_profit_value,
            "takeProfitLong": self.long_take_profit_value,
            "takeProfitShort": self.short_take_profit_value,
            "portfolioTpPercent": self.portfolio_tp_percent,
        })
        payload["pairOverrides"] = {symbol: {"enabled": True, **dict(values)} for symbol, values in sorted(self.pair_overrides.items())}
        return payload


_SHARED_ATTR_TO_KEY = {
    "minimum_leverage": "minimumLeverage",
    "entry_margin_usd": "entryMarginUsd",
    "entry_notional_usd": "entryNotionalUsd",
    "unlimited_dca": "unlimitedDca",
    "short_start_multiplier": "shortStartMultiplier",
}


def _execution_context_from_stack() -> tuple[str, str]:
    frame = sys._getframe(2)
    symbol = ""
    side = ""
    for _ in range(14):
        if frame is None:
            break
        direct = _normalize_symbol(frame.f_locals.get("symbol"))
        if direct:
            symbol = direct
        local_side = str(frame.f_locals.get("side") or "").upper()
        if local_side in {"LONG", "SHORT"}:
            side = local_side
        row = frame.f_locals.get("row")
        if isinstance(row, dict):
            from_row = _normalize_symbol(row.get("symbol"))
            row_side = str(row.get("positionSide", "")).upper()
            if from_row:
                symbol = from_row
            if row_side in {"LONG", "SHORT"}:
                side = row_side
        key = str(frame.f_locals.get("key") or "")
        if "|" in key:
            key_symbol, key_side = key.rsplit("|", 1)
            normalized = _normalize_symbol(key_symbol)
            if normalized:
                symbol = normalized
            if key_side.upper() in {"LONG", "SHORT"}:
                side = key_side.upper()
        ranked_row = frame.f_locals.get("ranked_row")
        if isinstance(ranked_row, dict):
            from_rank = _normalize_symbol(ranked_row.get("symbol"))
            if from_rank:
                symbol = from_rank
        if symbol and side:
            return symbol, side
        frame = frame.f_back
    return symbol, side


def _side_value(base: MultiBbConfig, override: dict[str, Any], side: str, kind: str) -> Any:
    is_short = side == "SHORT"
    if kind == "dca_distance":
        specific = "shortDcaDistance" if is_short else "longDcaDistance"
        return override.get(specific, override.get("dcaDistance", base.short_dca_distance if is_short else base.long_dca_distance))
    if kind == "dca_margin_usd":
        specific = "shortDcaMarginUsd" if is_short else "longDcaMarginUsd"
        return override.get(specific, override.get("dcaMarginUsd", base.short_dca_margin_usd if is_short else base.long_dca_margin_usd))
    if kind == "max_dca":
        specific = "maxDcaShort" if is_short else "maxDcaLong"
        return override.get(specific, override.get("maxDca", base.max_dca_short if is_short else base.max_dca_long))
    if kind == "take_profit":
        specific = "shortTakeProfitValue" if is_short else "longTakeProfitValue"
        return override.get(specific, override.get("takeProfit", base.short_take_profit_value if is_short else base.long_take_profit_value))
    raise AttributeError(kind)


class _PairAwareSettings:
    def __init__(self, base: MultiBbConfig):
        object.__setattr__(self, "_base", base)

    def __getattr__(self, name: str) -> Any:
        base: MultiBbConfig = object.__getattribute__(self, "_base")
        symbol, side = _execution_context_from_stack()
        override = base.pair_overrides.get(symbol, {}) if symbol else {}
        if name in {"dca_distance", "dca_margin_usd", "max_dca", "take_profit"} and side in {"LONG", "SHORT"}:
            return _side_value(base, override, side, name)
        if name == "take_profit_enabled":
            if base.take_profit_mode != "PER_TRADE":
                return False
            return bool(override.get("takeProfitEnabled", base.take_profit_enabled))
        key = _SHARED_ATTR_TO_KEY.get(name)
        if key and key in override:
            return override[key]
        return getattr(base, name)


def effective_pair_settings(settings: MultiBbConfig, symbol: str) -> dict[str, Any]:
    normalized = _normalize_symbol(symbol)
    override = settings.pair_overrides.get(normalized, {})
    base = settings.public_dict()
    base.pop("pairOverrides", None)
    result = {**base, **override, "symbol": normalized, "custom": bool(override)}
    result.update({
        "longDcaDistance": _side_value(settings, override, "LONG", "dca_distance"),
        "shortDcaDistance": _side_value(settings, override, "SHORT", "dca_distance"),
        "longDcaMarginUsd": _side_value(settings, override, "LONG", "dca_margin_usd"),
        "shortDcaMarginUsd": _side_value(settings, override, "SHORT", "dca_margin_usd"),
        "maxDcaLong": _side_value(settings, override, "LONG", "max_dca"),
        "maxDcaShort": _side_value(settings, override, "SHORT", "max_dca"),
        "longTakeProfitValue": _side_value(settings, override, "LONG", "take_profit"),
        "shortTakeProfitValue": _side_value(settings, override, "SHORT", "take_profit"),
        "individualTpActive": settings.take_profit_mode == "PER_TRADE" and bool(override.get("takeProfitEnabled", settings.take_profit_enabled)),
    })
    return result


def position_action_preview(*, row: dict[str, Any], state: dict[str, Any], settings: MultiBbConfig, account_equity: float = 0.0) -> dict[str, Any]:
    return _core.position_action_preview(
        row=row,
        state=state,
        settings=_PairAwareSettings(settings),
        account_equity=account_equity,
    )


def leverage_tier_preview(*, client: Any, symbol: str, settings: MultiBbConfig) -> dict[str, Any]:
    return _core.leverage_tier_preview(client=client, symbol=symbol, settings=_PairAwareSettings(settings))


def run_multi_bb_step(*, settings: MultiBbConfig, **kwargs: Any) -> dict[str, Any]:
    _sync_core_hooks()
    client = kwargs["client"]
    ref = kwargs["ref"]
    raw_state = kwargs["raw_state"]
    uid = kwargs["uid"]
    account = kwargs["account"]
    positions = kwargs["positions"]
    open_orders = kwargs["open_orders"]
    timestamp_ms = kwargs["timestamp_ms"]
    dry_run = bool(kwargs.get("dry_run", False))
    order_budget = kwargs.get("order_budget")
    before_order = kwargs.get("before_order")

    gate = portfolio_cycle_gate(
        client=client, ref=ref, raw_state=raw_state, uid=uid, account=account,
        positions=positions, open_orders=open_orders, timestamp_ms=timestamp_ms,
        take_profit_mode=settings.take_profit_mode, portfolio_tp_percent=settings.portfolio_tp_percent,
        dry_run=dry_run, order_budget=order_budget, before_order=before_order,
    )
    cycle_snapshot = gate.report
    if gate.handled and not gate.restart:
        report = {"engine": ENGINE, "configVersion": settings.version,
                  "status": "simulated" if dry_run else "portfolio-tp-executing",
                  "action": "PORTFOLIO_TP", "entryStatus": str(cycle_snapshot.get("cycleStatus", "PORTFOLIO_TP_EXECUTING")),
                  "entryReason": "Portfolio Take Profit heeft absolute uitvoeringsprioriteit",
                  "pairOverrideCount": len(settings.pair_overrides), "portfolioCycle": cycle_snapshot,
                  **cycle_snapshot}
        if not dry_run:
            ref.set({"multiBbReport": report}, merge=True)
        return report

    def guarded_before_order(intent: Any) -> Any:
        assert_order_allowed(ref, intent, client=client)
        if before_order is not None:
            try:
                return before_order(intent)
            except TypeError:
                return before_order(intent, None)
        return None

    core_kwargs = dict(kwargs)
    core_kwargs["before_order"] = guarded_before_order
    if gate.restart:
        core_kwargs.update({
            "raw_state": gate.raw_state,
            "account": gate.account,
            "positions": gate.positions,
            "open_orders": gate.open_orders,
            "order_budget": max(0, (15 if order_budget is None else int(order_budget)) - gate.orders_sent),
        })
    try:
        report = _core.run_multi_bb_step(settings=_PairAwareSettings(settings), **core_kwargs)
    except PortfolioCycleOrderBlocked as exc:
        report = {"status": "waiting", "action": "PORTFOLIO_CYCLE_GUARD", "ordersSent": 0,
                  "entryStatus": "PORTFOLIO_CYCLE_BLOCKED", "entryReason": str(exc), "actions": []}
    report["pairOverrideCount"] = len(settings.pair_overrides)
    report["takeProfitMode"] = settings.take_profit_mode
    report["longDcaDistance"] = settings.long_dca_distance
    report["shortDcaDistance"] = settings.short_dca_distance
    report["maxDcaLong"] = settings.max_dca_long
    report["maxDcaShort"] = settings.max_dca_short
    report["longTakeProfitValue"] = settings.long_take_profit_value
    report["shortTakeProfitValue"] = settings.short_take_profit_value
    report["portfolioCycle"] = cycle_snapshot
    if gate.restart:
        report["portfolioRestart"] = True
        report["previousPortfolioExitOrders"] = gate.orders_sent
    if not dry_run:
        ref.set({"multiBbReport": report}, merge=True)
    return report


def __getattr__(name: str) -> Any:
    """Keep all untouched public/private imports backward compatible."""
    return getattr(_core, name)
