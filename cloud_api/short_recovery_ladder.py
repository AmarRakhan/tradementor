"""SHORT Recovery 2.0 — pure ladder arithmetic (no Firestore, no exchange, no orders).

Model (per symbol = per position; the bot never holds two LONGs in one symbol):

* A cycle starts when the Auto Hedge pair is exactly 1:1 hedged. The confirmed
  average SHORT entry is the fixed ``anchor``; the SHORT quantity at that moment
  is ``base``.
* Step k (1..n) is reached when the mark price is at or below
  ``anchor * (1 - k * stepPct / 100)``. All levels come from the same anchor.
* ``stepsReached`` only ever grows within a cycle: a bounce never re-adds SHORT.
* Released quantity after k steps = floor_to_step(base * k / n); after the last
  step it is the whole ``base``.
* Desired SHORT = max(0, LONG - released). SHORT can therefore never exceed the
  LONG, and new LONG quantity (DCA) stays fully hedged.
* A reduction below the exchange minimum is not sent: it carries into the next
  step. At the final step an unsendable remainder does not block the cycle: the
  refill simply opens the gap up to the LONG, which ends in the same 1:1 state.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Mapping

DEFAULT_STEPS = 4
DEFAULT_STEP_PCT = Decimal("2")
MAX_STEPS = 100


def _dec(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{name} moet een getal zijn")
    if not result.is_finite():
        raise ValueError(f"{name} moet eindig zijn")
    return result


def normalize_settings(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate user settings. Fully free choice of steps and distance."""
    raw = raw or {}
    if not isinstance(raw, Mapping):
        raise ValueError("instellingen moeten een object zijn")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("enabled moet aan of uit zijn")
    steps = raw.get("steps", DEFAULT_STEPS)
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= MAX_STEPS:
        raise ValueError(f"aantal stappen moet een geheel getal van 1 t/m {MAX_STEPS} zijn")
    step_pct = _dec(raw.get("stepPct", DEFAULT_STEP_PCT), "stapafstand")
    if step_pct <= 0:
        raise ValueError("stapafstand moet groter dan 0% zijn")
    if step_pct * steps >= 100:
        raise ValueError("laatste afbouwniveau moet boven 0 liggen (stappen × afstand < 100%)")
    return {"enabled": enabled, "steps": steps, "stepPct": format(step_pct.normalize(), "f")}


def step_price(anchor: Any, k: int, step_pct: Any) -> Decimal:
    a = _dec(anchor, "anker")
    if a <= 0:
        raise ValueError("anker moet positief zijn")
    return a * (Decimal(1) - Decimal(k) * _dec(step_pct, "stapafstand") / Decimal(100))


def ladder(anchor: Any, settings: Mapping[str, Any]) -> list[dict[str, Any]]:
    cfg = normalize_settings(settings)
    n = cfg["steps"]
    return [
        {
            "step": k,
            "price": step_price(anchor, k, cfg["stepPct"]),
            "remainingFraction": Decimal(n - k) / Decimal(n),
        }
        for k in range(1, n + 1)
    ]


def steps_reached(anchor: Any, mark: Any, settings: Mapping[str, Any], previous: int = 0) -> int:
    """Highest step whose level the mark has touched; never lower than ``previous``."""
    cfg = normalize_settings(settings)
    n = cfg["steps"]
    price = _dec(mark, "koers")
    prior = max(0, min(n, int(previous or 0)))
    if price <= 0:
        return prior
    reached = 0
    for k in range(1, n + 1):
        if price <= step_price(anchor, k, cfg["stepPct"]):
            reached = k
        else:
            break
    return max(prior, reached)


def _floor(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def released_quantity(base: Any, k: int, n: int, qty_step: Any) -> Decimal:
    b = _dec(base, "basis")
    if b <= 0 or k <= 0:
        return Decimal(0)
    if k >= n:
        return b
    return _floor(b * Decimal(k) / Decimal(n), _dec(qty_step, "stapgrootte"))


def desired_short(long_qty: Any, base: Any, k: int, n: int, qty_step: Any) -> Decimal:
    long_q = max(Decimal(0), _dec(long_qty, "LONG"))
    return max(Decimal(0), long_q - released_quantity(base, k, n, qty_step))


def plan(
    *,
    long_qty: Any,
    short_qty: Any,
    base: Any,
    anchor: Any,
    mark: Any,
    settings: Mapping[str, Any],
    previous_steps: int,
    qty_step: Any,
    min_qty: Any = 0,
    min_notional: Any = 0,
) -> dict[str, Any]:
    """Decide the next Recovery action for one symbol. Never returns an order to OPEN beyond the LONG."""
    cfg = normalize_settings(settings)
    n = cfg["steps"]
    long_q = max(Decimal(0), _dec(long_qty, "LONG"))
    short_q = max(Decimal(0), _dec(short_qty, "SHORT"))
    price = _dec(mark, "koers")
    k = steps_reached(anchor, price, cfg, previous_steps)
    target = desired_short(long_q, base, k, n, qty_step)
    result: dict[str, Any] = {
        "stepsReached": k,
        "steps": n,
        "targetShort": target,
        "longQty": long_q,
        "shortQty": short_q,
    }
    if short_q > long_q:
        # Over-hedged pair: the normal Auto Hedge REDUCE handles this; Recovery adds nothing.
        result.update(action="HOLD", reason="OVER_HEDGED_LEFT_TO_AUTO_HEDGE", quantity=Decimal(0))
        return result
    gap = short_q - target
    step = _dec(qty_step, "stapgrootte")
    if gap <= 0 or (step > 0 and gap < step):
        done = k >= n
        result.update(
            action="CYCLE_COMPLETE" if done else "HOLD",
            reason="LADDER_FINISHED_REFILL" if done else "AT_TARGET",
            quantity=Decimal(0),
        )
        return result
    qty = _floor(gap, step)
    too_small = (_dec(min_qty, "minimum") > 0 and qty < _dec(min_qty, "minimum")) or (
        _dec(min_notional, "minimum orderwaarde") > 0 and qty * price < _dec(min_notional, "minimum orderwaarde")
    )
    if too_small:
        if k >= n:
            # Final step: the refill opens up to the LONG, which yields the same 1:1 end state.
            result.update(action="CYCLE_COMPLETE", reason="FINAL_REMAINDER_BELOW_MINIMUM_REFILL", quantity=Decimal(0))
        else:
            result.update(action="HOLD", reason="BELOW_MINIMUM_CARRY_TO_NEXT_STEP", quantity=Decimal(0))
        return result
    result.update(action="REDUCE_SHORT", reason=f"STEP_{k}_OF_{n}", quantity=qty)
    return result
