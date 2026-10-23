"""Hedge afbouwen (SHORT Recovery 2.0, both sides since build 623) — pure ladder arithmetic.

Build 623 (Amar 23-10): the same ladder for both sides. ``direction="DOWN"`` (default) is the
original case: a protected LONG with a SHORT hedge that is reduced while the price FALLS.
``direction="UP"`` mirrors it: a protected SHORT with a LONG hedge reduced while the price RISES.
In the functions below ``long_qty`` means the PROTECTED leg and ``short_qty`` the HEDGE leg.
A step is only sold when it is profitable AFTER fees (open + close fee on the hedge entry).

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
* A step reduction below the exchange minimum is NOT carried to the next step
  (decision Amar 22-10 17:03). Instead the whole SHORT is closed and 90% of the LONG
  is reopened (``FULL_CLOSE_REOPEN``, decision Amar 17:57): the SHORT always ends 10%
  below the LONG (never 81%, 72.9%, ...) and a new cycle starts on that reopened SHORT. If the 90% reopen is itself below the
  exchange minimum, the symbol is skipped (no order).
* At the final step an unsendable remainder does not block the cycle: the refill
  opens the gap up to the LONG, which ends in the same 1:1 state.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Mapping

DEFAULT_STEPS = 4
DEFAULT_TOTAL_PCT = Decimal("8")
MAX_STEPS = 100
REOPEN_FRACTION = Decimal("0.9")
DIRECTIONS = {"DOWN", "UP"}
# Conservative taker fee per order (open and close), fraction of notional.
DEFAULT_FEE_RATE = Decimal("0.0005")


def _direction(value: Any) -> str:
    text = str(value or "DOWN").upper()
    if text not in DIRECTIONS:
        raise ValueError("richting moet DOWN of UP zijn")
    return text


def hedge_side_for(protected_side: str) -> str:
    return "SHORT" if str(protected_side).upper() == "LONG" else "LONG"


def direction_for(protected_side: str) -> str:
    """A protected LONG has a SHORT hedge that is reduced on a falling price; a protected SHORT the mirror."""
    return "DOWN" if str(protected_side).upper() == "LONG" else "UP"


def profitable_after_fees(*, direction: Any, hedge_entry: Any, price: Any,
                          fee_rate: Any = DEFAULT_FEE_RATE) -> bool:
    """True when closing the hedge at ``price`` beats its entry by more than open + close fees."""
    try:
        entry = Decimal(str(hedge_entry))
        mark = Decimal(str(price))
        rate = Decimal(str(fee_rate))
    except (InvalidOperation, TypeError, ValueError):
        return False
    if not (entry.is_finite() and mark.is_finite() and rate.is_finite()) or entry <= 0 or mark <= 0:
        return False
    gross = entry - mark if _direction(direction) == "DOWN" else mark - entry
    return gross - (entry + mark) * rate > 0


def _dec(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{name} moet een getal zijn")
    if not result.is_finite():
        raise ValueError(f"{name} moet eindig zijn")
    return result


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def normalize_settings(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate user settings (decision Amar 18:02).

    The user chooses ON/OFF, the TOTAL drop over which the SHORT is reduced (``totalPct``) and the
    number of steps; the bot derives the distance per step (totalPct / steps). A legacy ``stepPct``
    (distance per step) is still accepted and converted: totalPct = stepPct * steps.
    """
    raw = raw or {}
    if not isinstance(raw, Mapping):
        raise ValueError("instellingen moeten een object zijn")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("enabled moet aan of uit zijn")
    steps = raw.get("steps", DEFAULT_STEPS)
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= MAX_STEPS:
        raise ValueError(f"aantal stappen moet een geheel getal van 1 t/m {MAX_STEPS} zijn")
    if raw.get("totalPct") is not None:
        total = _dec(raw.get("totalPct"), "totale daling")
    elif raw.get("stepPct") is not None:
        total = _dec(raw.get("stepPct"), "stapafstand") * steps
    else:
        total = DEFAULT_TOTAL_PCT
    if total <= 0:
        raise ValueError("totale daling moet groter dan 0% zijn")
    if total >= 100:
        raise ValueError("totale daling moet onder 100% liggen")
    return {"enabled": enabled, "steps": steps, "totalPct": _text(total),
            "stepPct": _text((total / Decimal(steps)).quantize(Decimal("1e-8")))}


def step_price(anchor: Any, k: int, n: int, total_pct: Any, direction: Any = "DOWN") -> Decimal:
    """Level of step k: anchor * (1 -/+ total * k / n / 100), always from the same anchor."""
    a = _dec(anchor, "anker")
    if a <= 0:
        raise ValueError("anker moet positief zijn")
    move = _dec(total_pct, "totale daling") * Decimal(k) / Decimal(n) / Decimal(100)
    return a * (Decimal(1) + move if _direction(direction) == "UP" else Decimal(1) - move)


def ladder(anchor: Any, settings: Mapping[str, Any], direction: Any = "DOWN") -> list[dict[str, Any]]:
    cfg = normalize_settings(settings)
    n = cfg["steps"]
    return [
        {
            "step": k,
            "price": step_price(anchor, k, n, cfg["totalPct"], direction),
            "remainingFraction": Decimal(n - k) / Decimal(n),
        }
        for k in range(1, n + 1)
    ]


def steps_reached(anchor: Any, mark: Any, settings: Mapping[str, Any], previous: int = 0,
                  direction: Any = "DOWN") -> int:
    """Highest step whose level the mark has touched; never lower than ``previous``."""
    cfg = normalize_settings(settings)
    n = cfg["steps"]
    up = _direction(direction) == "UP"
    price = _dec(mark, "koers")
    prior = max(0, min(n, int(previous or 0)))
    if price <= 0:
        return prior
    reached = 0
    for k in range(1, n + 1):
        level = step_price(anchor, k, n, cfg["totalPct"], direction)
        if (price >= level) if up else (price <= level):
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


def _below_minimum(qty: Decimal, price: Decimal, min_qty: Any, min_notional: Any) -> bool:
    mq = _dec(min_qty, "minimum")
    mn = _dec(min_notional, "minimum orderwaarde")
    return qty <= 0 or (mq > 0 and qty < mq) or (mn > 0 and qty * price < mn)


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
    reopen_basis_qty: Any = None,
    direction: Any = "DOWN",
    hedge_entry: Any = None,
    fee_rate: Any = DEFAULT_FEE_RATE,
) -> dict[str, Any]:
    """Decide the next action for one symbol. Never returns an order to OPEN beyond the protected leg.

    ``hedge_entry`` (average entry of the hedge leg) enables the after-fees guard: a step that would
    not be profitable after open + close fees waits (target unchanged) until the price is further.
    """
    cfg = normalize_settings(settings)
    n = cfg["steps"]
    long_q = max(Decimal(0), _dec(long_qty, "LONG"))
    short_q = max(Decimal(0), _dec(short_qty, "SHORT"))
    price = _dec(mark, "koers")
    k = steps_reached(anchor, price, cfg, previous_steps, direction)
    target = desired_short(long_q, base, k, n, qty_step)
    result: dict[str, Any] = {
        "stepsReached": k,
        "steps": n,
        "targetShort": target,
        "longQty": long_q,
        "shortQty": short_q,
    }
    if short_q > long_q:
        # Over-covered pair: never sold to straighten it (build 623 vangnet); nothing changes.
        result.update(action="HOLD", reason="OVER_HEDGED_LEFT_TO_AUTO_HEDGE", quantity=Decimal(0),
                      targetShort=short_q)
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
    if hedge_entry is not None and not profitable_after_fees(
            direction=direction, hedge_entry=hedge_entry, price=price, fee_rate=fee_rate):
        # Amar 23-10: never sell a step that is not profitable after fees; wait for a better price.
        result.update(action="HOLD", reason="STEP_WAIT_PROFIT_AFTER_FEES", quantity=Decimal(0),
                      targetShort=short_q)
        return result
    too_small = _below_minimum(qty, price, min_qty, min_notional)
    if too_small:
        if k >= n:
            # Final step: the refill opens up to the LONG, which yields the same 1:1 end state.
            result.update(action="CYCLE_COMPLETE", reason="FINAL_REMAINDER_BELOW_MINIMUM_REFILL", quantity=Decimal(0))
            return result
        # Reopen 90% of the basis (the runtime passes the LONG: the SHORT always ends 10% below the LONG).
        basis = short_q if reopen_basis_qty is None else max(Decimal(0), _dec(reopen_basis_qty, "basis terugzetten"))
        reopen = _floor(basis * REOPEN_FRACTION, step)
        if _below_minimum(short_q, price, min_qty, min_notional) or _below_minimum(reopen, price, min_qty, min_notional):
            result.update(action="HOLD", reason="BELOW_MINIMUM_EVEN_FOR_REOPEN_SKIP", quantity=Decimal(0))
            return result
        result.update(action="FULL_CLOSE_REOPEN", reason=f"STEP_{k}_BELOW_MINIMUM_CLOSE_ALL_REOPEN_90",
                      quantity=short_q, reopenQuantity=reopen)
        return result
    result.update(action="REDUCE_SHORT", reason=f"STEP_{k}_OF_{n}", quantity=qty)
    return result
