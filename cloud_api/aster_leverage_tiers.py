"""Single server-authoritative Aster leverage tier resolver for Strategy 2.

The same resolver powers entry planning, DCA tier transitions, diagnostics and
wizard previews.  It never invents exchange limits: callers must supply the
signed ``/fapi/v3/leverageBracket`` response for the account/symbol.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aster_gateway import AsterValidationError, LeverageBracket, maximum_allowed_leverage


def _d(value: Any, default: str = "0") -> Decimal:
    try:
        out = Decimal(str(value))
        return out if out.is_finite() else Decimal(default)
    except Exception:
        return Decimal(default)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def bracket_rows(payload: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    wanted = str(symbol).upper().strip()
    for row in payload or []:
        if str(row.get("symbol", "")).upper() == wanted:
            rows = row.get("brackets") or []
            return [x for x in rows if isinstance(x, dict)]
    if payload and all(isinstance(row, dict) and "initialLeverage" in row for row in payload):
        return list(payload)
    return []


def normalized_tiers(payload: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    rows = bracket_rows(payload, symbol)
    tiers = []
    for row in rows:
        floor = _d(row.get("notionalFloor"))
        cap = _d(row.get("notionalCap"))
        leverage = _i(row.get("initialLeverage"))
        if floor < 0 or cap < 0 or leverage < 1:
            continue
        tiers.append({
            "floor": float(floor), "cap": float(cap), "maxLeverage": leverage,
            "maintenanceMarginRatio": float(_d(row.get("maintMarginRatio"))),
        })
    tiers.sort(key=lambda x: (x["floor"], x["cap"] if x["cap"] > 0 else float("inf")))
    if not tiers:
        raise AsterValidationError(f"{str(symbol).upper()}: Aster leverage tiers ontbreken")
    return tiers


def maximum_for_notional(payload: list[dict[str, Any]], symbol: str, notional: float | Decimal) -> int:
    rows = bracket_rows(payload, symbol)
    if not rows:
        raise AsterValidationError(f"{str(symbol).upper()}: Aster leverage tiers ontbreken")
    return maximum_allowed_leverage(_d(notional), [LeverageBracket.from_mapping(row) for row in rows])


def _levels(payload: list[dict[str, Any]], symbol: str) -> list[int]:
    rows = bracket_rows(payload, symbol)
    values = sorted({_i(row.get("initialLeverage")) for row in rows if _i(row.get("initialLeverage")) > 0}, reverse=True)
    if not values:
        raise AsterValidationError(f"{str(symbol).upper()}: Aster leverage tiers ontbreken")
    return values


def resolve_entry(payload: list[dict[str, Any]], symbol: str, *, configured_minimum: int,
                  entry_margin_usd: float, entry_notional_usd: float,
                  entry_sizing_mode: str) -> dict[str, Any]:
    """Choose the highest self-consistent Aster leverage for a brand-new leg.

    In margin sizing, notional depends on leverage, so every Aster tier maximum
    is tested against the notional it would create.  If Aster's safe maximum is
    below the configured minimum, the exchange maximum wins instead of stopping
    Strategy 2; this is surfaced as ``forcedBelowConfiguredMinimum``.
    """
    mode = str(entry_sizing_mode).lower().strip()
    if mode not in {"margin", "notional"}:
        raise ValueError("entry sizing mode is ongeldig")
    levels = _levels(payload, symbol)
    if mode == "notional":
        planned = _d(entry_notional_usd)
        allowed = maximum_for_notional(payload, symbol, planned)
        chosen = min(max(levels), allowed)
        return {"leverage": chosen, "orderNotional": float(planned), "projectedNotional": float(planned),
                "exchangeMaxLeverage": allowed, "configuredMinimum": int(configured_minimum),
                "forcedBelowConfiguredMinimum": chosen < int(configured_minimum)}
    margin = _d(entry_margin_usd)
    if margin <= 0:
        raise ValueError("entry margin moet positief zijn")
    for chosen in levels:
        planned = margin * chosen
        allowed = maximum_for_notional(payload, symbol, planned)
        if chosen <= allowed:
            return {"leverage": chosen, "orderNotional": float(planned), "projectedNotional": float(planned),
                    "exchangeMaxLeverage": allowed, "configuredMinimum": int(configured_minimum),
                    "forcedBelowConfiguredMinimum": chosen < int(configured_minimum)}
    raise AsterValidationError(f"{str(symbol).upper()}: geen zelf-consistente Aster leverage tier voor entry")


def resolve_dca(payload: list[dict[str, Any]], symbol: str, *, current_notional: float,
                current_leverage: int, dca_margin_usd: float, configured_minimum: int) -> dict[str, Any]:
    """Resolve a DCA against the *projected total* contract notional.

    Leverage can stay equal or step down, never silently step up.  The returned
    ``additionalMarginRequired`` covers both the new DCA and any extra margin
    needed because the entire existing contract moves to a lower leverage.
    """
    existing = max(Decimal("0"), _d(current_notional))
    old_lev = max(1, int(current_leverage))
    margin = _d(dca_margin_usd)
    if margin <= 0:
        raise ValueError("DCA margin moet positief zijn")
    levels = [level for level in _levels(payload, symbol) if level <= old_lev]
    if old_lev not in levels:
        levels.append(old_lev)
    levels = sorted(set(levels), reverse=True)
    for chosen in levels:
        order_notional = margin * chosen
        projected = existing + order_notional
        allowed = maximum_for_notional(payload, symbol, projected)
        if chosen > allowed:
            continue
        current_margin = existing / old_lev
        projected_margin = projected / chosen
        additional = max(Decimal("0"), projected_margin - current_margin)
        return {"leverage": chosen, "previousLeverage": old_lev,
                "orderNotional": float(order_notional), "projectedNotional": float(projected),
                "exchangeMaxLeverage": allowed, "configuredMinimum": int(configured_minimum),
                "forcedBelowConfiguredMinimum": chosen < int(configured_minimum),
                "tierReduction": chosen < old_lev, "additionalMarginRequired": float(additional)}
    raise AsterValidationError(f"{str(symbol).upper()}: geen geldige Aster leverage tier voor geprojecteerde DCA")


def tier_preview(payload: list[dict[str, Any]], symbol: str, *, configured_minimum: int,
                 entry_margin_usd: float, entry_notional_usd: float, entry_sizing_mode: str,
                 dca_margin_usd: float, current_notional: float = 0.0,
                 current_leverage: int = 0) -> dict[str, Any]:
    tiers = normalized_tiers(payload, symbol)
    if current_notional > 0 and current_leverage > 0:
        base_notional = float(current_notional); base_leverage = int(current_leverage)
        entry = None
    else:
        entry = resolve_entry(payload, symbol, configured_minimum=configured_minimum,
                              entry_margin_usd=entry_margin_usd, entry_notional_usd=entry_notional_usd,
                              entry_sizing_mode=entry_sizing_mode)
        base_notional = float(entry["projectedNotional"]); base_leverage = int(entry["leverage"])
    next_tier = next((row for row in tiers if row["floor"] > base_notional and row["maxLeverage"] < base_leverage), None)
    estimated = None
    if next_tier is not None:
        simulated_notional = base_notional; simulated_leverage = base_leverage
        for count in range(1, 501):
            step = resolve_dca(payload, symbol, current_notional=simulated_notional,
                               current_leverage=simulated_leverage, dca_margin_usd=dca_margin_usd,
                               configured_minimum=configured_minimum)
            simulated_notional = float(step["projectedNotional"])
            if int(step["leverage"]) < base_leverage:
                estimated = count; break
            simulated_leverage = int(step["leverage"])
    return {"symbol": str(symbol).upper(), "source": "/fapi/v3/leverageBracket", "tiers": tiers,
            "currentNotional": float(current_notional), "currentLeverage": int(current_leverage),
            "entryPlan": entry, "nextTier": next_tier, "estimatedDcasToNextTier": estimated,
            "configuredMinimum": int(configured_minimum)}
