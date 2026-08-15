"""Pure public status contracts for Aster strategy ownership and operation.

These helpers never read exchange data, write state, or submit orders.  They
make the distinction between an engine switch, entry eligibility, existing
position management, and market-data health explicit for every caller.
"""
from __future__ import annotations

from typing import Any, Iterable


def proven_owned_rows(rows: Iterable[Any], *, strategy_id: str, engine_type: str) -> list[dict[str, Any]]:
    """Return only rows whose persisted identity explicitly proves ownership."""
    result: list[dict[str, Any]] = []
    for value in rows:
        if not isinstance(value, dict):
            continue
        stored_strategy = str(value.get("strategy_id", value.get("strategyId", ""))).strip()
        stored_engine = str(value.get("engine_type", value.get("engineType", ""))).strip()
        symbol = str(value.get("symbol", "")).strip().upper()
        side = str(value.get("side", "")).strip().upper()
        if stored_strategy != strategy_id or stored_engine != engine_type:
            continue
        if not symbol or side not in {"LONG", "SHORT"}:
            continue
        result.append(value)
    return result


def position_count_contract(rows: Iterable[dict[str, Any]], *, scope: str) -> dict[str, Any]:
    values = list(rows)
    symbols = {str(row.get("symbol", "")).strip().upper() for row in values if str(row.get("symbol", "")).strip()}
    long_legs = sum(1 for row in values if str(row.get("side", "")).upper() == "LONG")
    short_legs = sum(1 for row in values if str(row.get("side", "")).upper() == "SHORT")
    return {
        "scope": scope,
        "ownershipProven": True,
        "uniqueMarketCount": len(symbols),
        "positionLegCount": len(values),
        "longLegs": long_legs,
        "shortLegs": short_legs,
    }


def operating_status_contract(*, enabled: bool, monitor: bool, runtime_enabled: bool,
                              owned_leg_count: int, universe: dict[str, Any],
                              exchange_data_fresh: bool = True) -> dict[str, Any]:
    stale = bool(universe.get("stale", True))
    selected = int(universe.get("selectedMarketCount") or 0)
    market_blocked = bool(universe.get("entryBlocked", True))
    market_reason = str(universe.get("entryBlockReason") or "")
    market_state = "STALE" if stale else "MISSING" if selected < 1 else "BLOCKED" if market_blocked else "READY"

    if not enabled:
        entry_state, entry_reason = "BLOCKED_BOT_OFF", "Strategy 2 staat uit; nieuwe instappen zijn geblokkeerd"
    elif not runtime_enabled:
        entry_state, entry_reason = "BLOCKED_RUNTIME", "De centrale Strategy-2-uitvoeringspoort staat uit"
    elif market_blocked:
        entry_state, entry_reason = "BLOCKED_MARKET_DATA", market_reason
    else:
        entry_state, entry_reason = "ALLOWED", ""

    if monitor and owned_leg_count and exchange_data_fresh:
        management_state = "FULL" if enabled else "SAFE_EXISTING_ONLY"
        management_reason = ("Bestaande bewezen Strategy-2-posities worden volledig beheerd" if enabled else
            "Bot uit: bestaande bewezen Strategy-2-posities blijven veilig gemonitord; nieuwe instappen blijven uit")
    elif monitor and owned_leg_count:
        management_state = "UNCONFIRMED"
        management_reason = ("Positiebeheer staat ingeschakeld, maar actuele uitvoering kon door Aster "
            "niet worden bevestigd; exchange-side bescherming blijft onafhankelijk actief")
    elif owned_leg_count:
        management_state = "PAUSED"
        management_reason = "Bestaande Strategy-2-posities zijn bewezen, maar monitoring staat uit"
    else:
        management_state = "IDLE"
        management_reason = "Geen bewezen Strategy-2-posities om te beheren"

    return {
        "bot": {"state": "ON" if enabled else "OFF", "enabled": enabled},
        "newEntries": {"state": entry_state, "blocked": entry_state != "ALLOWED", "reason": entry_reason},
        "existingPositionManagement": {"state": management_state, "monitor": monitor,
            "exchangeConfirmed": exchange_data_fresh, "reason": management_reason},
        "marketData": {"state": market_state, "stale": stale, "reason": market_reason},
    }
