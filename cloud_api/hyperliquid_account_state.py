"""Normalize Hyperliquid account data into the economic values shown by the exchange UI."""
from __future__ import annotations

from typing import Any


def _number(value: Any) -> float:
    try:
        result = float(value or 0)
        return result if result == result else 0.0
    except (TypeError, ValueError):
        return 0.0


def _is_unified(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() == "unifiedaccount"
    if isinstance(value, dict):
        candidate = value.get("type") or value.get("userAbstraction") or value.get("abstraction")
        return str(candidate or "").strip().lower() == "unifiedaccount"
    return False


def _usdc_balance(spot_state: dict[str, Any]) -> dict[str, Any]:
    for row in spot_state.get("balances", []) or []:
        if str(row.get("coin", "")).upper() == "USDC" or str(row.get("token", "")) == "0":
            return row
    return {}


def normalize_hyperliquid_account_state(
    clearing_state: dict[str, Any],
    spot_state: dict[str, Any],
    user_abstraction: Any,
    active_asset_data: dict[str, Any] | None = None,
    *,
    asset: str = "BTC",
) -> dict[str, Any]:
    """Return one exchange-truth snapshot for dashboards and strategy risk checks.

    Unified accounts keep their economic portfolio value in the spot USDC ledger,
    while per-asset buying power is supplied by ``activeAssetData``. Legacy/default
    accounts retain the clearinghouse ``accountValue``/``withdrawable`` mapping.
    """
    margin = clearing_state.get("marginSummary", {}) or {}
    positions = [
        row for row in (clearing_state.get("assetPositions", []) or [])
        if abs(_number((row.get("position", {}) or {}).get("szi"))) > 0
    ]
    unified = _is_unified(user_abstraction)
    usdc = _usdc_balance(spot_state)
    portfolio = _number(usdc.get("total")) if unified else _number(margin.get("accountValue"))
    if portfolio <= 0:
        portfolio = _number(margin.get("accountValue")) or _number(usdc.get("total"))

    values = (active_asset_data or {}).get("availableToTrade", []) or []
    available_long = _number(values[0]) if len(values) > 0 else 0.0
    available_short = _number(values[1]) if len(values) > 1 else available_long
    if not unified or (available_long <= 0 and available_short <= 0):
        fallback = _number(clearing_state.get("withdrawable"))
        available_long = available_long or fallback
        available_short = available_short or fallback

    unrealized = sum(_number((row.get("position", {}) or {}).get("unrealizedPnl")) for row in positions)
    maintenance = _number(clearing_state.get("crossMaintenanceMarginUsed"))
    total_notional = _number(margin.get("totalNtlPos"))
    leverage = total_notional / portfolio if portfolio > 0 else 0.0
    conservative = min(available_long, available_short) if available_long > 0 and available_short > 0 else max(available_long, available_short)

    return {
        "accountMode": "unifiedAccount" if unified else "defaultAccount",
        "portfolioValue": portfolio,
        "availableToTrade": available_long,
        "availableToTradeLong": available_long,
        "availableToTradeShort": available_short,
        "conservativeAvailableToTrade": conservative,
        "availableAsset": asset.upper(),
        "unrealizedPnl": unrealized,
        "maintenanceMargin": maintenance,
        "unifiedAccountLeverage": leverage,
        "totalNotionalPosition": total_notional,
        "totalMarginUsed": _number(margin.get("totalMarginUsed")),
        "activeTradeCapital": _number(margin.get("totalMarginUsed")),
        "activePositionCount": len(positions),
        "assetPositions": clearing_state.get("assetPositions", []) or [],
        "source": "hyperliquid_exchange_state",
    }


def direction_available(state: dict[str, Any], short: bool) -> float:
    return _number(state.get("availableToTradeShort" if short else "availableToTradeLong"))
