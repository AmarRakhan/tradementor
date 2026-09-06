from __future__ import annotations

"""Pair-aware facade for the proven Multi BB runtime.

The original engine is preserved verbatim in ``aster_multi_bb_core.py``. This
module adds persistent per-symbol setting overrides while preserving every
existing execution, reconciliation and monkeypatch contract.
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

ENGINE = _core.ENGINE

max_contract_leverage = _core.max_contract_leverage
rank_top_volume = _core.rank_top_volume

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}USDT$")
_MAX_PAIR_DCA = 500

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


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").upper().replace("/", "").replace("_", "").replace("-", "").strip()
    return symbol if _SYMBOL_RE.fullmatch(symbol) else ""


def _clean_pair_override(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    if raw.get("enabled") is False:
        return {}

    if "minimumLeverage" in raw:
        value = int(round(_finite(raw.get("minimumLeverage"))))
        if not 1 <= value <= 300:
            raise ValueError("Pair minimum leverage moet tussen 1x en 300x liggen")
        out["minimumLeverage"] = value
    if "entryMarginUsd" in raw:
        value = _finite(raw.get("entryMarginUsd"))
        if value <= 0:
            raise ValueError("Pair instapmargin moet positief zijn")
        out["entryMarginUsd"] = value
    if "entryNotionalUsd" in raw:
        value = _finite(raw.get("entryNotionalUsd"))
        if value <= 0:
            raise ValueError("Pair instapnotional moet positief zijn")
        out["entryNotionalUsd"] = value
    if "dcaDistance" in raw:
        value = _finite(raw.get("dcaDistance"))
        if not .0001 <= value <= .50:
            raise ValueError("Pair DCA-afstand moet tussen 0,01% en 50% liggen")
        out["dcaDistance"] = value
    if "dcaMarginUsd" in raw:
        value = _finite(raw.get("dcaMarginUsd"))
        if value <= 0:
            raise ValueError("Pair DCA-margin moet positief zijn")
        out["dcaMarginUsd"] = value
    if "maxDca" in raw:
        value = int(round(_finite(raw.get("maxDca"))))
        if not 0 <= value <= _MAX_PAIR_DCA:
            raise ValueError(f"Pair max DCA moet tussen 0 en {_MAX_PAIR_DCA} liggen")
        out["maxDca"] = value
    if "unlimitedDca" in raw:
        out["unlimitedDca"] = bool(raw.get("unlimitedDca"))
    if "takeProfit" in raw:
        value = _finite(raw.get("takeProfit"))
        if value <= 0:
            raise ValueError("Pair Take Profit moet een positief percentage zijn")
        out["takeProfit"] = value
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
    """Established config plus sparse per-symbol overrides."""

    pair_overrides: dict[str, dict[str, Any]] = field(default_factory=dict, compare=False)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "MultiBbConfig":
        source = raw or {}
        base = _core.MultiBbConfig.from_mapping(source)
        values = {item.name: getattr(base, item.name) for item in fields(_core.MultiBbConfig)}
        values["pair_overrides"] = _parse_pair_overrides(source.get("pairOverrides"))
        return cls(**values).validated()

    def public_dict(self) -> dict[str, Any]:
        payload = super().public_dict()
        payload["pairOverrides"] = {symbol: {"enabled": True, **dict(values)} for symbol, values in sorted(self.pair_overrides.items())}
        return payload


_ATTR_TO_KEY = {
    "minimum_leverage": "minimumLeverage",
    "entry_margin_usd": "entryMarginUsd",
    "entry_notional_usd": "entryNotionalUsd",
    "dca_distance": "dcaDistance",
    "dca_margin_usd": "dcaMarginUsd",
    "max_dca": "maxDca",
    "unlimited_dca": "unlimitedDca",
    "take_profit": "takeProfit",
    "take_profit_enabled": "takeProfitEnabled",
    "short_start_multiplier": "shortStartMultiplier",
}


def _symbol_from_execution_stack() -> str:
    """Resolve the symbol currently being handled by the unchanged core loop."""
    frame = sys._getframe(2)
    for _ in range(12):
        if frame is None:
            break
        direct = _normalize_symbol(frame.f_locals.get("symbol"))
        if direct:
            return direct
        row = frame.f_locals.get("row")
        if isinstance(row, dict):
            from_row = _normalize_symbol(row.get("symbol"))
            if from_row:
                return from_row
        ranked_row = frame.f_locals.get("ranked_row")
        if isinstance(ranked_row, dict):
            from_rank = _normalize_symbol(ranked_row.get("symbol"))
            if from_rank:
                return from_rank
        frame = frame.f_back
    return ""


class _PairAwareSettings:
    def __init__(self, base: MultiBbConfig):
        object.__setattr__(self, "_base", base)

    def __getattr__(self, name: str) -> Any:
        base: MultiBbConfig = object.__getattribute__(self, "_base")
        key = _ATTR_TO_KEY.get(name)
        if key:
            symbol = _symbol_from_execution_stack()
            override = base.pair_overrides.get(symbol, {}) if symbol else {}
            if key in override:
                return override[key]
        return getattr(base, name)


def effective_pair_settings(settings: MultiBbConfig, symbol: str) -> dict[str, Any]:
    normalized = _normalize_symbol(symbol)
    override = settings.pair_overrides.get(normalized, {})
    base = settings.public_dict()
    base.pop("pairOverrides", None)
    return {**base, **override, "symbol": normalized, "custom": bool(override)}


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
    report = _core.run_multi_bb_step(settings=_PairAwareSettings(settings), **kwargs)
    report["pairOverrideCount"] = len(settings.pair_overrides)
    return report


def __getattr__(name: str) -> Any:
    """Keep all untouched public/private imports backward compatible."""
    return getattr(_core, name)
