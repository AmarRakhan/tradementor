"""Conservative margin-reserve estimate for Portfolio Noodhedge.

This module is pure and performs no exchange I/O. It estimates the initial
margin needed to neutralise the current per-symbol LONG/SHORT quantity delta,
then adds explicit execution headroom. The estimate is intentionally
conservative: when leverage evidence is missing it assumes 1x instead of
pretending the hedge is cheap.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

RESERVE_MULTIPLIER = Decimal("1.25")
TECHNICAL_TRIGGER_MULTIPLIER = Decimal("1.50")
MIN_EXECUTION_BUFFER_USD = Decimal("0.25")


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    return result if result.is_finite() else Decimal("0")


@dataclass(frozen=True)
class EmergencyMarginEstimate:
    hedge_notional_usd: Decimal
    estimated_initial_margin_usd: Decimal
    reserve_usd: Decimal
    technical_trigger_available_usd: Decimal
    available_balance_usd: Decimal
    headroom_usd: Decimal
    feasible_now: bool
    technical_override: bool
    symbol_count: int

    def public_dict(self) -> dict[str, Any]:
        return {
            "estimatedHedgeNotionalUsd": float(self.hedge_notional_usd),
            "estimatedHedgeMarginUsd": float(self.estimated_initial_margin_usd),
            "hedgeReserveUsd": float(self.reserve_usd),
            "technicalTriggerAvailableUsd": float(self.technical_trigger_available_usd),
            "availableBalanceUsd": float(self.available_balance_usd),
            "hedgeHeadroomUsd": float(self.headroom_usd),
            "hedgeFeasibleNow": self.feasible_now,
            "technicalSafetyOverride": self.technical_override,
            "hedgeReserveSymbolCount": self.symbol_count,
        }


def estimate_emergency_margin(rows: list[dict[str, Any]], available_balance: Any) -> EmergencyMarginEstimate:
    per_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", "")).upper().strip()
        quantity = abs(_decimal(row.get("positionAmt")))
        if not symbol or side not in {"LONG", "SHORT"} or quantity <= 0:
            continue
        bucket = per_symbol.setdefault(symbol, {
            "LONG": Decimal("0"), "SHORT": Decimal("0"),
            "mark": Decimal("0"), "leverages": [],
        })
        bucket[side] += quantity
        mark = _decimal(row.get("markPrice"))
        if mark > 0:
            bucket["mark"] = mark
        leverage = _decimal(row.get("leverage"))
        if leverage > 0:
            bucket["leverages"].append(leverage)

    hedge_notional = Decimal("0")
    initial_margin = Decimal("0")
    required_symbols = 0
    for bucket in per_symbol.values():
        delta = abs(bucket["LONG"] - bucket["SHORT"])
        if delta <= 0:
            continue
        required_symbols += 1
        mark = bucket["mark"]
        # Missing mark data cannot be treated as a zero-cost hedge. Use a
        # deliberately impossible reserve below by charging the full available
        # balance plus the minimum execution buffer.
        if mark <= 0:
            available = max(Decimal("0"), _decimal(available_balance))
            reserve = available + MIN_EXECUTION_BUFFER_USD
            return EmergencyMarginEstimate(
                hedge_notional_usd=Decimal("0"),
                estimated_initial_margin_usd=reserve,
                reserve_usd=reserve,
                technical_trigger_available_usd=reserve * TECHNICAL_TRIGGER_MULTIPLIER,
                available_balance_usd=available,
                headroom_usd=available - reserve,
                feasible_now=False,
                technical_override=True,
                symbol_count=required_symbols,
            )
        leverage_values = bucket["leverages"]
        leverage = min(leverage_values) if leverage_values else Decimal("1")
        notional = delta * mark
        hedge_notional += notional
        initial_margin += notional / max(Decimal("1"), leverage)

    available = max(Decimal("0"), _decimal(available_balance))
    if required_symbols == 0:
        return EmergencyMarginEstimate(
            hedge_notional_usd=Decimal("0"), estimated_initial_margin_usd=Decimal("0"),
            reserve_usd=Decimal("0"), technical_trigger_available_usd=Decimal("0"),
            available_balance_usd=available, headroom_usd=available,
            feasible_now=True, technical_override=False, symbol_count=0,
        )

    reserve = max(initial_margin * RESERVE_MULTIPLIER, initial_margin + MIN_EXECUTION_BUFFER_USD)
    technical_trigger = reserve * TECHNICAL_TRIGGER_MULTIPLIER
    headroom = available - reserve
    return EmergencyMarginEstimate(
        hedge_notional_usd=hedge_notional,
        estimated_initial_margin_usd=initial_margin,
        reserve_usd=reserve,
        technical_trigger_available_usd=technical_trigger,
        available_balance_usd=available,
        headroom_usd=headroom,
        feasible_now=available >= reserve,
        technical_override=available <= technical_trigger,
        symbol_count=required_symbols,
    )
