from __future__ import annotations

"""Pair-aware facade for the proven Multi BB runtime.

The original engine is preserved verbatim in ``aster_multi_bb_core.py``.  This
module adds one deliberately narrow capability: persistent per-symbol setting
overrides.  The execution algorithm, reconciliation, ownership checks and order
submission paths remain the existing implementation.
"""

from dataclasses import dataclass, field, fields
import math
import re
import sys
from typing import Any

import aster_multi_bb_core as _core

ENGINE = _core.ENGINE

# Public helpers that do not depend on settings can be re-exported directly.
max_contract_leverage = _core.max_contract_leverage
rank_top_volume = _core.rank_top_volume

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}USDT$")
_MAX_PAIR_DCA = 500


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
    """The established config plus sparse per-symbol overrides.

    Missing fields always inherit the base Strategy 2 setting.  This makes the
    precedence explicit: pair override -> base setting -> engine default.
    """

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
    """Resolve the symbol currently being handled by the unchanged core loop.

    The core already keeps ``symbol`` or the current position ``row`` local in
    every price/order decision. Looking only a few frames upward therefore lets
    the facade select the correct sparse override without modifying the proven
    order/reconciliation implementation.
    """
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
    """Public deterministic pair view used by tests and UI diagnostics."""
    normalized = _normalize_symbol(symbol)
    override = settings.pair_overrides.get(normalized, {})
    base = settings.public_dict()
    base.pop("pairOverrides", None)
    return {**base, **override, "symbol": normalized, "custom": bool(override)}


def position_action_preview(*, row: dict[str, Any], state: dict[str, Any], settings: MultiBbConfig, account_equity: float = 0.0) -> dict[str, Any]:
    """Preview DCA/TP using the same effective pair settings as execution."""
    return _core.position_action_preview(
        row=row,
        state=state,
        settings=_PairAwareSettings(settings),
        account_equity=account_equity,
    )


def leverage_tier_preview(client: Any, symbol: str, settings: MultiBbConfig) -> dict[str, Any]:
    """Leverage preview also honors pair entry/DCA overrides."""
    return _core.leverage_tier_preview(client, symbol, _PairAwareSettings(settings))


def run_multi_bb_step(*, settings: MultiBbConfig, **kwargs: Any) -> dict[str, Any]:
    """Execute the existing engine with pair-aware values for per-symbol fields."""
    report = _core.run_multi_bb_step(settings=_PairAwareSettings(settings), **kwargs)
    report["pairOverrideCount"] = len(settings.pair_overrides)
    return report


def __getattr__(name: str) -> Any:
    """Keep all untouched public/private imports backward compatible."""
    return getattr(_core, name)
