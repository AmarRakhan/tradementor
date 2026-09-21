"""Strategy-level symbol ownership helpers for the shared Aster account."""
from __future__ import annotations
from typing import Any


OWNERS = {"ASTER", "SNIPER"}


def normalize_symbol(value: Any) -> str:
    symbol = str(value or "").upper().strip()
    return symbol if symbol.endswith("USDT") and len(symbol) <= 32 else ""


def strategy2_active_symbols(raw: dict[str, Any] | None) -> set[str]:
    raw = raw or {}
    result: set[str] = set()
    for row in raw.get("ownedLegs", []) if isinstance(raw.get("ownedLegs"), list) else []:
        if isinstance(row, dict):
            symbol = normalize_symbol(row.get("symbol"))
            if symbol:
                result.add(symbol)
    for row in raw.get("pendingReopens", []) if isinstance(raw.get("pendingReopens"), list) else []:
        if isinstance(row, dict):
            symbol = normalize_symbol(row.get("symbol"))
            if symbol:
                result.add(symbol)
    queue = raw.get("orderQueueState") if isinstance(raw.get("orderQueueState"), dict) else {}
    intent = queue.get("currentIntent") if isinstance(queue.get("currentIntent"), dict) else {}
    symbol = normalize_symbol(intent.get("symbol"))
    if symbol:
        result.add(symbol)
    return result


def sniper_active_symbols(raw: dict[str, Any] | None) -> set[str]:
    raw = raw or {}
    result: set[str] = set()
    for row in raw.get("activeTrades", []) if isinstance(raw.get("activeTrades"), list) else []:
        if isinstance(row, dict):
            symbol = normalize_symbol(row.get("symbol"))
            if symbol:
                result.add(symbol)
    intent = raw.get("pendingIntent") if isinstance(raw.get("pendingIntent"), dict) else {}
    symbol = normalize_symbol(intent.get("symbol"))
    if symbol:
        result.add(symbol)
    return result


def ownership_intersection(strategy2: dict[str, Any] | None, sniper: dict[str, Any] | None) -> set[str]:
    return strategy2_active_symbols(strategy2) & sniper_active_symbols(sniper)


def owner_can_claim(owner: str, symbol: str, strategy2: dict[str, Any] | None, sniper: dict[str, Any] | None) -> bool:
    owner = str(owner).upper()
    symbol = normalize_symbol(symbol)
    if owner not in OWNERS or not symbol:
        return False
    if owner == "ASTER":
        return symbol not in sniper_active_symbols(sniper)
    return symbol not in strategy2_active_symbols(strategy2)
