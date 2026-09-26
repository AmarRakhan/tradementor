"""Pure planning helpers for owner-only Legacy Hedge Recovery.

This module is intentionally side-effect free. It converts one requested real
margin amount per side into one exchange-valid coin quantity and previews the
weighted entry-price effect for LONG and SHORT. Order submission, Firestore
state and recovery live in aster_legacy_hedge_scale_extension.py.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN
import hashlib
import math
from typing import Any

from aster_gateway import ContractRules


EVENT_TYPE = "LEGACY_HEDGE_SCALE"
DEFAULT_TAKER_FEE_RATE = 0.0005
EPSILON = 1e-12


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def _decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Ongeldige numerieke waarde") from exc
    if not parsed.is_finite():
        raise ValueError("Numerieke waarde moet eindig zijn")
    return parsed


def parity_tolerance(rule: ContractRules) -> float:
    step = abs(_number(rule.market_quantity_step))
    return max(EPSILON, step / 1000.0 if step > 0 else EPSILON)


def weighted_entry(old_qty: Any, old_entry: Any, added_qty: Any, execution_price: Any) -> float:
    oq = _number(old_qty)
    oe = _number(old_entry)
    aq = _number(added_qty)
    ep = _number(execution_price)
    if oq <= 0 or oe <= 0 or aq < 0 or ep <= 0:
        raise ValueError("Entry-preview mist geldige quantity of prijs")
    total = oq + aq
    if total <= 0:
        raise ValueError("Totale quantity moet positief zijn")
    return ((oq * oe) + (aq * ep)) / total


def entry_effect(side: str, current_entry: Any, new_entry: Any) -> str:
    current = _number(current_entry)
    new = _number(new_entry)
    if current <= 0 or new <= 0:
        return "VRIJWEL GELIJK"
    tolerance = max(1e-12, abs(current) * 1e-9)
    delta = new - current
    if abs(delta) <= tolerance:
        return "VRIJWEL GELIJK"
    normalized = str(side).upper().strip()
    if normalized == "LONG":
        return "GUNSTIGER" if delta < 0 else "ONGUNSTIGER"
    if normalized == "SHORT":
        return "GUNSTIGER" if delta > 0 else "ONGUNSTIGER"
    raise ValueError("Positiezijde moet LONG of SHORT zijn")


def break_even_distance(side: str, current_price: Any, break_even_price: Any) -> dict[str, Any]:
    """Return the required percentage move from current price to one leg break-even."""
    current = _number(current_price)
    target = _number(break_even_price)
    normalized = str(side).upper().strip()
    if normalized not in {"LONG", "SHORT"}:
        raise ValueError("Positiezijde moet LONG of SHORT zijn")
    if current <= 0 or target <= 0:
        raise ValueError("Break-evenafstand mist een geldige actuele koers of break-evenprijs")

    if normalized == "LONG":
        reached = current + EPSILON >= target
        distance = 0.0 if reached else ((target / current) - 1.0) * 100.0
        direction = "REACHED" if reached else "UP"
    else:
        reached = current <= target + EPSILON
        distance = 0.0 if reached else ((current - target) / current) * 100.0
        direction = "REACHED" if reached else "DOWN"

    if abs(distance) < 1e-10:
        distance = 0.0
    return {
        "distancePct": max(0.0, distance),
        "direction": direction,
        "reached": reached,
    }


def break_even_distance_change(old_distance: Any, new_distance: Any, *, old_reached: bool = False) -> dict[str, Any]:
    """Describe relative distance improvement against the original situation."""
    old = max(0.0, _number(old_distance))
    new = max(0.0, _number(new_distance))
    if old_reached or old <= 1e-12:
        return {"kind": "ALREADY_REACHED", "relativePct": None}
    delta = old - new
    tolerance = max(1e-10, old * 1e-9)
    if abs(delta) <= tolerance:
        return {"kind": "UNCHANGED", "relativePct": 0.0}
    if delta > 0:
        relative = min(100.0, max(0.0, delta / old * 100.0))
        return {"kind": "CLOSER", "relativePct": relative}
    relative = max(0.0, (new - old) / old * 100.0)
    return {"kind": "FARTHER", "relativePct": relative}


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def stable_scale_intent_id(
    uid: str,
    symbol: str,
    operation_id: str,
    side: str,
    stage: str,
    quantity: Any,
) -> str:
    raw = f"{uid}|{symbol}|{operation_id}|{side}|{stage}|{quantity}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    suffix = "l" if str(side).upper() == "LONG" else "s"
    return f"lhs-{digest}-{suffix}"


def plan_legacy_hedge_scale(
    *,
    symbol: str,
    margin_per_side_usd: Any,
    available_balance: Any,
    current_long_qty: Any,
    current_short_qty: Any,
    long_entry: Any,
    short_entry: Any,
    long_execution_price: Any,
    short_execution_price: Any,
    long_leverage: Any,
    short_leverage: Any,
    rules: ContractRules,
    taker_fee_rate: Any = DEFAULT_TAKER_FEE_RATE,
    current_price: Any | None = None,
    long_break_even: Any | None = None,
    short_break_even: Any | None = None,
) -> dict[str, Any]:
    """Build a fail-closed quote using one common added quantity for both legs."""
    margin = _number(margin_per_side_usd)
    available = _number(available_balance, -1.0)
    long_qty = _number(current_long_qty)
    short_qty = _number(current_short_qty)
    long_px = _number(long_execution_price)
    short_px = _number(short_execution_price)
    long_lev = _number(long_leverage)
    short_lev = _number(short_leverage)
    fee_rate = _number(taker_fee_rate, -1.0)

    if margin <= 0:
        raise ValueError("Bedrag per zijde moet groter dan 0 USD zijn")
    if available < 0:
        raise ValueError("Actuele Available to Trade is niet betrouwbaar beschikbaar")
    if long_qty <= 0 or short_qty <= 0:
        raise ValueError("LONG en SHORT moeten beide open zijn")
    tolerance = parity_tolerance(rules)
    if abs(long_qty - short_qty) > tolerance:
        raise ValueError("Hedge-lock is niet exact 1:1; vergroot pas nadat quantity is gereconcileerd")
    if long_px <= 0 or short_px <= 0:
        raise ValueError("Actuele executionprijs is niet betrouwbaar beschikbaar")
    if long_lev < 1 or short_lev < 1:
        raise ValueError("Actuele leverage is niet betrouwbaar beschikbaar")
    if fee_rate < 0 or fee_rate > 0.05:
        raise ValueError("Fee-rate voor preview is ongeldig")

    raw_long = _decimal(margin) * _decimal(long_lev) / _decimal(long_px)
    raw_short = _decimal(margin) * _decimal(short_lev) / _decimal(short_px)
    common_raw = min(raw_long, raw_short)
    quantity = _floor_to_step(common_raw, rules.market_quantity_step)
    quantity = rules.market_quantity(quantity, min(_decimal(long_px), _decimal(short_px)))
    if quantity <= 0:
        raise ValueError("Bedrag per zijde resulteert na exchange-afronding in 0 quantity")

    q = float(quantity)
    long_margin = q * long_px / long_lev
    short_margin = q * short_px / short_lev
    total_margin = long_margin + short_margin
    estimated_fees = q * (long_px + short_px) * fee_rate
    required_available = total_margin + estimated_fees
    if required_available > available + 1e-9:
        raise ValueError(
            f"Onvoldoende Available to Trade: nodig circa USD {required_available:.2f}, "
            f"beschikbaar USD {available:.2f}"
        )

    long_after_entry = weighted_entry(long_qty, long_entry, q, long_px)
    short_after_entry = weighted_entry(short_qty, short_entry, q, short_px)
    long_after_qty = long_qty + q
    short_after_qty = short_qty + q

    current_px = _number(current_price)
    if current_px <= 0:
        current_px = (long_px + short_px) / 2.0
    long_break_even_now = _number(long_break_even)
    if long_break_even_now <= 0:
        long_break_even_now = _number(long_entry)
    short_break_even_now = _number(short_break_even)
    if short_break_even_now <= 0:
        short_break_even_now = _number(short_entry)
    if current_px <= 0 or long_break_even_now <= 0 or short_break_even_now <= 0:
        raise ValueError("Break-evenpreview mist betrouwbare actuele prijs- of positiegegevens")

    # When Aster supplies breakEvenPrice it may already include accumulated
    # fee/funding effects. Use that as the current basis; otherwise entryPrice.
    # The post-scale break-even remains an estimate because the new fills/fees
    # do not exist yet.
    long_break_even_after = weighted_entry(long_qty, long_break_even_now, q, long_px)
    short_break_even_after = weighted_entry(short_qty, short_break_even_now, q, short_px)
    long_before_distance = break_even_distance("LONG", current_px, long_break_even_now)
    long_after_distance = break_even_distance("LONG", current_px, long_break_even_after)
    short_before_distance = break_even_distance("SHORT", current_px, short_break_even_now)
    short_after_distance = break_even_distance("SHORT", current_px, short_break_even_after)
    long_change = break_even_distance_change(
        long_before_distance["distancePct"],
        long_after_distance["distancePct"],
        old_reached=bool(long_before_distance["reached"]),
    )
    short_change = break_even_distance_change(
        short_before_distance["distancePct"],
        short_after_distance["distancePct"],
        old_reached=bool(short_before_distance["reached"]),
    )

    return {
        "eventType": EVENT_TYPE,
        "symbol": str(symbol).upper().strip(),
        "requestedMarginPerSideUsd": margin,
        "availableBalance": available,
        "extraQuantity": q,
        "marketQuantityStep": float(rules.market_quantity_step),
        "estimatedLongMarginUsd": long_margin,
        "estimatedShortMarginUsd": short_margin,
        "estimatedTotalMarginUsd": total_margin,
        "estimatedFeesUsd": estimated_fees,
        "estimatedAvailableDebitUsd": required_available,
        "availableAfterEstimate": max(0.0, available - required_available),
        "hedgeRatioAfter": 100.0,
        "quantityInvariant": "ABS(LONG_QTY)==ABS(SHORT_QTY)",
        "long": {
            "side": "LONG",
            "currentQuantity": long_qty,
            "addedQuantity": q,
            "quantityAfter": long_after_qty,
            "currentEntry": _number(long_entry),
            "executionPrice": long_px,
            "estimatedEntryAfter": long_after_entry,
            "entryEffect": entry_effect("LONG", long_entry, long_after_entry),
            "leverage": long_lev,
            "currentPrice": current_px,
            "currentBreakEven": long_break_even_now,
            "estimatedBreakEvenAfter": long_break_even_after,
            "breakEvenDistanceBeforePct": long_before_distance["distancePct"],
            "breakEvenDistanceAfterPct": long_after_distance["distancePct"],
            "breakEvenDirectionBefore": long_before_distance["direction"],
            "breakEvenDirectionAfter": long_after_distance["direction"],
            "breakEvenReachedBefore": long_before_distance["reached"],
            "breakEvenReachedAfter": long_after_distance["reached"],
            "distanceChangeKind": long_change["kind"],
            "distanceChangePct": long_change["relativePct"],
        },
        "short": {
            "side": "SHORT",
            "currentQuantity": short_qty,
            "addedQuantity": q,
            "quantityAfter": short_after_qty,
            "currentEntry": _number(short_entry),
            "executionPrice": short_px,
            "estimatedEntryAfter": short_after_entry,
            "entryEffect": entry_effect("SHORT", short_entry, short_after_entry),
            "leverage": short_lev,
            "currentPrice": current_px,
            "currentBreakEven": short_break_even_now,
            "estimatedBreakEvenAfter": short_break_even_after,
            "breakEvenDistanceBeforePct": short_before_distance["distancePct"],
            "breakEvenDistanceAfterPct": short_after_distance["distancePct"],
            "breakEvenDirectionBefore": short_before_distance["direction"],
            "breakEvenDirectionAfter": short_after_distance["direction"],
            "breakEvenReachedBefore": short_before_distance["reached"],
            "breakEvenReachedAfter": short_after_distance["reached"],
            "distanceChangeKind": short_change["kind"],
            "distanceChangePct": short_change["relativePct"],
        },
        "pairResultNote": (
            "Bestaand pair-resultaat blijft bij uitvoering grotendeels behouden; "
            "entries en exposure veranderen."
        ),
    }


def parity_repair_action(
    *,
    pre_long_qty: Any,
    pre_short_qty: Any,
    current_long_qty: Any,
    current_short_qty: Any,
    step: Any,
) -> dict[str, Any] | None:
    """Return the smallest OPEN required to restore equal newly-added quantity."""
    pre_long = _number(pre_long_qty)
    pre_short = _number(pre_short_qty)
    current_long = _number(current_long_qty)
    current_short = _number(current_short_qty)
    step_value = max(EPSILON, _number(step))
    long_added = max(0.0, current_long - pre_long)
    short_added = max(0.0, current_short - pre_short)
    delta = long_added - short_added
    if abs(delta) < max(EPSILON, step_value / 1000.0):
        return None
    if delta > 0:
        return {"side": "SHORT", "action": "OPEN", "quantity": abs(delta)}
    return {"side": "LONG", "action": "OPEN", "quantity": abs(delta)}


def excess_rollback_action(
    *,
    pre_long_qty: Any,
    pre_short_qty: Any,
    current_long_qty: Any,
    current_short_qty: Any,
    step: Any,
) -> dict[str, Any] | None:
    """Return a CLOSE that removes only newly-added excess, never legacy quantity."""
    repair = parity_repair_action(
        pre_long_qty=pre_long_qty,
        pre_short_qty=pre_short_qty,
        current_long_qty=current_long_qty,
        current_short_qty=current_short_qty,
        step=step,
    )
    if repair is None:
        return None
    opposite = "LONG" if repair["side"] == "SHORT" else "SHORT"
    return {"side": opposite, "action": "CLOSE", "quantity": repair["quantity"]}
