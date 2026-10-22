"""SHORT Recovery 2.0 — per-symbol cycle state machine (pure: no Firestore, no exchange, no orders).

It only decides the SHORT *target* the existing Auto Hedge engine must reconcile to. All orders
keep going through ``reconcile_auto_hedge`` (same lease, deterministic clientOrderId,
submit_order_once, fill confirmation). Returning ``override=None`` means legacy 1:1.

Phases of the per-pair ``shortRecovery`` record:

* (none) / REFILL — wait until the pair is exactly 1:1, then start a cycle: anchor = confirmed
  average SHORT entry, base = SHORT quantity, longAtStart = LONG quantity.
* LADDER — target = base - released(stepsReached) + LONG growth since the start, capped by LONG.
  A too-small step switches to REOPEN_CLOSE (after a margin pre-check for the reopen).
  Last step confirmed -> REFILL (legacy target = LONG -> 100% re-hedge -> new cycle).
* REOPEN_CLOSE — target 0 until the SHORT is confirmed flat, then REOPEN_OPEN.
* REOPEN_OPEN — target = reopenQty (90% of the LONG: always a 10% gap); once reached a new
  LADDER cycle starts on that reopened SHORT.

Settings changes apply from the next cycle (steps/stepPct are snapshotted at cycle start).
Switching the feature off clears the record: the engine then restores the legacy 1:1 hedge.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from short_recovery_ladder import normalize_settings, plan

PHASE_LADDER = "LADDER"
PHASE_REOPEN_CLOSE = "REOPEN_CLOSE"
PHASE_REOPEN_OPEN = "REOPEN_OPEN"
PHASE_REFILL = "REFILL"


def _d(value: Any, default: str = "0") -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)
    return result if result.is_finite() else Decimal(default)


def _same(a: Decimal, b: Decimal, step: Decimal) -> bool:
    tolerance = step / 2 if step > 0 else Decimal("1e-12")
    return abs(a - b) <= tolerance


def _txt(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if text not in {"-0", ""} else "0"


def _start_cycle(prior: Mapping[str, Any] | None, *, long_q: Decimal, short_q: Decimal,
                 short_entry: Decimal, cfg: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "cycleId": int(_d((prior or {}).get("cycleId"))) + 1,
        "phase": PHASE_LADDER,
        "anchor": _txt(short_entry),
        "base": _txt(short_q),
        "longAtStart": _txt(long_q),
        "stepsReached": 0,
        "steps": cfg["steps"],
        "stepPct": cfg["stepPct"],
        "startReason": reason,
        "reopenQty": None,
        "lastTarget": _txt(short_q),
    }


def decide(
    *,
    record: Mapping[str, Any] | None,
    settings: Mapping[str, Any] | None,
    long_qty: Any,
    short_qty: Any,
    short_entry: Any,
    mark: Any,
    has_pending_short_order: bool,
    qty_step: Any,
    min_qty: Any = 0,
    min_notional: Any = 0,
    available_balance: Any = None,
    leverage: Any = 1,
) -> dict[str, Any]:
    """Return {override, record, event}. ``override`` is a Decimal SHORT target or None (legacy 1:1)."""
    try:
        cfg = normalize_settings(settings or {})
    except ValueError:
        return {"override": None, "record": None, "event": "SETTINGS_INVALID_LEGACY_1_TO_1"}
    long_q = max(Decimal(0), _d(long_qty))
    short_q = max(Decimal(0), _d(short_qty))
    step = max(Decimal(0), _d(qty_step))
    price = _d(mark)
    rec = dict(record or {}) or None

    if not cfg["enabled"]:
        return {"override": None, "record": None, "event": "DISABLED_LEGACY_1_TO_1" if rec else "DISABLED"}
    if long_q <= 0:
        return {"override": None, "record": None, "event": "NO_LONG"}
    if price <= 0:
        return {"override": _d(rec["lastTarget"]) if rec and rec.get("lastTarget") is not None else None,
                "record": rec, "event": "MARK_UNAVAILABLE_HOLD"}
    if has_pending_short_order:
        # Never advance a phase while an order is still open; keep the last confirmed target.
        return {"override": _d(rec["lastTarget"]) if rec and rec.get("lastTarget") is not None else None,
                "record": rec, "event": "PENDING_ORDER_HOLD"}

    phase = (rec or {}).get("phase")

    if rec is None or phase == PHASE_REFILL:
        if _same(short_q, long_q, step) and _d(short_entry) > 0:
            new = _start_cycle(rec, long_q=long_q, short_q=short_q, short_entry=_d(short_entry), cfg=cfg,
                               reason="HEDGED_1_TO_1")
            return {"override": short_q, "record": new, "event": "CYCLE_STARTED"}
        return {"override": None, "record": rec, "event": "WAIT_FOR_1_TO_1"}

    if phase == PHASE_REOPEN_CLOSE:
        if short_q <= (step / 2 if step > 0 else Decimal(0)):
            rec.update(phase=PHASE_REOPEN_OPEN, lastTarget=rec["reopenQty"])
            return {"override": min(long_q, _d(rec["reopenQty"])), "record": rec, "event": "CLOSED_ALL_REOPEN_90"}
        rec["lastTarget"] = "0"
        return {"override": Decimal(0), "record": rec, "event": "CLOSING_ALL"}

    if phase == PHASE_REOPEN_OPEN:
        reopen = min(long_q, _d(rec.get("reopenQty")))
        if _same(short_q, reopen, step) and _d(short_entry) > 0:
            new = _start_cycle(rec, long_q=long_q, short_q=short_q, short_entry=_d(short_entry), cfg=cfg,
                               reason="REOPENED_90")
            return {"override": short_q, "record": new, "event": "CYCLE_STARTED_AFTER_REOPEN"}
        rec["lastTarget"] = str(reopen)
        return {"override": reopen, "record": rec, "event": "REOPENING_90"}

    # LADDER
    base = _d(rec.get("base"))
    growth = max(Decimal(0), long_q - _d(rec.get("longAtStart")))
    cap = base + growth
    snapshot = {"enabled": True, "steps": int(rec.get("steps") or cfg["steps"]),
                "stepPct": str(rec.get("stepPct") or cfg["stepPct"])}
    decision = plan(long_qty=cap, short_qty=min(short_q, cap), base=base, anchor=_d(rec.get("anchor")), mark=price,
                    settings=snapshot, previous_steps=int(rec.get("stepsReached") or 0), qty_step=step,
                    min_qty=min_qty, min_notional=min_notional, reopen_basis_qty=long_q)
    rec["stepsReached"] = max(int(rec.get("stepsReached") or 0), int(decision["stepsReached"]))
    target = min(long_q, decision["targetShort"])
    action = decision["action"]

    if action == "CYCLE_COMPLETE":
        rec.update(phase=PHASE_REFILL, lastTarget=str(long_q))
        return {"override": None, "record": rec, "event": "LADDER_DONE_REFILL_1_TO_1"}

    if action == "FULL_CLOSE_REOPEN":
        reopen = decision["reopenQuantity"]
        lev = max(Decimal(1), _d(leverage, "1"))
        if available_balance is None or reopen * price / lev > _d(available_balance):
            # Never close the whole SHORT unless the 90% reopen is affordable.
            keep = min(long_q, short_q)
            rec["lastTarget"] = str(keep)
            return {"override": keep, "record": rec, "event": "REOPEN_MARGIN_UNPROVEN_SKIP"}
        rec.update(phase=PHASE_REOPEN_CLOSE, reopenQty=str(reopen), lastTarget="0")
        return {"override": Decimal(0), "record": rec, "event": "STEP_TOO_SMALL_CLOSE_ALL"}

    if action == "HOLD" and decision["reason"] == "BELOW_MINIMUM_EVEN_FOR_REOPEN_SKIP":
        keep = min(long_q, short_q)
        rec["lastTarget"] = str(keep)
        return {"override": keep, "record": rec, "event": "SKIPPED_BELOW_MINIMUM"}

    rec["lastTarget"] = str(target)
    return {"override": target, "record": rec, "event": "STEP_REDUCE" if action == "REDUCE_SHORT" else "LADDER_HOLD"}
