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

Build 629 (Amar 23-10, keuze B): settings changes apply AT ONCE to running ladders, and the LADDER measures from
the hedge's live average entry (the profit the user sees), so a hedge already past steps sells them in one
catch-up order. Nothing sold is bought back within a cycle (ceiling = last target + new protected quantity).
Switching the feature off clears the record: the engine then restores the legacy 1:1 hedge.

Build 623 (Amar 23-10): both sides. ``direction="DOWN"`` = protected LONG / SHORT hedge (original),
``direction="UP"`` = protected SHORT / LONG hedge reduced while the price rises. ``long_qty`` is the
PROTECTED leg, ``short_qty``/``short_entry`` the HEDGE leg. A REFILL record with ``anchorAtMark``
(set by Re-Hedge All) is still recorded, but since build 629 the ladder measures from the live hedge entry.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from short_recovery_ladder import normalize_settings, plan, profitable_after_fees

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


def _below_exchange_minimum(qty: Decimal, price: Decimal, step: Decimal, min_qty: Any, min_notional: Any) -> bool:
    """True when ``qty`` can not be sent as one Aster order (below the step, the minimum quantity or notional)."""
    floored = (qty / step).to_integral_value(rounding="ROUND_DOWN") * step if step > 0 else qty
    mq, mn = _d(min_qty), _d(min_notional)
    return floored <= 0 or (mq > 0 and floored < mq) or (mn > 0 and floored * price < mn)


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
        "totalPct": cfg["totalPct"],
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
    start_at_mark: bool = False,
    direction: str = "DOWN",
) -> dict[str, Any]:
    """Return {override, record, event}.

    ``start_at_mark``: for a pair that was already hedged before the user switched SHORT afbouwen ON, the
    FIRST cycle anchors at the current mark instead of the old SHORT entry (decision Amar 22-10 19:45), so
    switching ON never triggers a burst of catch-up reductions. Later cycles use the SHORT entry. ``override`` is a Decimal SHORT target or None (legacy 1:1)."""
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
        # Build 631 (Amar 23-10): a hedge that misses less than one Aster minimum order (e.g. after the 90% reopen or
        # an aborted close-all) can never reach exact 1:1. That counts as hedged: start the cycle on the hedge as it
        # is, instead of waiting forever (afbouw never restarted and the engine retried an impossible order).
        gap = long_q - short_q
        gap_below_minimum = short_q > 0 and gap > 0 and _below_exchange_minimum(gap, price, step, min_qty, min_notional)
        if (_same(short_q, long_q, step) or gap_below_minimum) and _d(short_entry) > 0:
            rehedge_all = bool(rec and rec.get("anchorAtMark"))
            at_mark = (start_at_mark and rec is None) or rehedge_all
            reason = "REHEDGE_ALL_AT_MARK" if rehedge_all else ("ANCHOR_AT_SWITCH_ON" if at_mark else (
                "HEDGED_GAP_BELOW_MINIMUM" if gap_below_minimum else "HEDGED_1_TO_1"))
            new = _start_cycle(rec, long_q=long_q, short_q=short_q, short_entry=price if at_mark else _d(short_entry),
                               cfg=cfg, reason=reason)
            new["direction"] = direction
            return {"override": short_q, "record": new, "event": "CYCLE_STARTED"}
        return {"override": None, "record": rec, "event": "WAIT_FOR_1_TO_1"}

    if phase == PHASE_REOPEN_CLOSE:
        if short_q <= (step / 2 if step > 0 else Decimal(0)):
            rec.update(phase=PHASE_REOPEN_OPEN, lastTarget=rec["reopenQty"])
            return {"override": min(long_q, _d(rec["reopenQty"])), "record": rec, "event": "CLOSED_ALL_REOPEN_90"}
        # Amar 23-10 (kernregel): never close a hedge at a loss. The close-all was decided when the hedge was in
        # profit, but the hedge may have been refilled since (e.g. at a worse price): re-check against the CURRENT
        # hedge entry on every tick. Not profitable -> abort the close-all (no order), back to REFILL: the pair is
        # made 1:1 again by buying only, and a new cycle anchors on that hedge entry.
        if not profitable_after_fees(direction=str(rec.get("direction") or direction), hedge_entry=_d(short_entry),
                                     price=price):
            keep = min(long_q, short_q)
            rec.update(phase=PHASE_REFILL, reopenQty=None, lastTarget=str(keep))
            return {"override": keep, "record": rec, "event": "CLOSE_ALL_ABORTED_NOT_PROFITABLE"}
        rec["lastTarget"] = "0"
        return {"override": Decimal(0), "record": rec, "event": "CLOSING_ALL"}

    if phase == PHASE_REOPEN_OPEN:
        reopen = min(long_q, _d(rec.get("reopenQty")))
        if _same(short_q, reopen, step) and _d(short_entry) > 0:
            new = _start_cycle(rec, long_q=long_q, short_q=short_q, short_entry=_d(short_entry), cfg=cfg,
                               reason="REOPENED_90")
            new["direction"] = direction
            return {"override": short_q, "record": new, "event": "CYCLE_STARTED_AFTER_REOPEN"}
        rec["lastTarget"] = str(reopen)
        return {"override": reopen, "record": rec, "event": "REOPENING_90"}

    # LADDER
    # Build 629 (Amar 23-10, keuze B): the CURRENT settings apply at once to every running ladder (no snapshot
    # per cycle any more), and the ladder measures from the hedge's own live average entry, i.e. exactly the
    # profit the user sees on the hedge. A pair that is already past steps under the new settings sells them
    # now (one catch-up order); past the last step it sells the whole hedge and is re-hedged 1:1.
    base = _d(rec.get("base"))
    growth = max(Decimal(0), long_q - _d(rec.get("longAtStart")))
    cap = base + growth
    live = {"enabled": True, "steps": cfg["steps"], "totalPct": cfg["totalPct"]}
    settings_changed = (str(rec.get("totalPct")) != str(cfg["totalPct"])
                        or int(rec.get("steps") or 0) != int(cfg["steps"]))
    entry = _d(short_entry)
    anchor = entry if entry > 0 else _d(rec.get("anchor"))
    # Steps of an older setting mean something else: recount on the new grid. The ceiling below still
    # guarantees that nothing already sold is bought back.
    previous = 0 if settings_changed else int(rec.get("stepsReached") or 0)
    decision = plan(long_qty=cap, short_qty=min(short_q, cap), base=base, anchor=anchor, mark=price,
                    settings=live, previous_steps=previous, qty_step=step,
                    min_qty=min_qty, min_notional=min_notional, reopen_basis_qty=long_q,
                    direction=str(rec.get("direction") or direction), hedge_entry=entry)
    rec.update(stepsReached=int(decision["stepsReached"]), steps=cfg["steps"], totalPct=cfg["totalPct"],
               stepPct=cfg["stepPct"], anchor=_txt(anchor) if anchor > 0 else rec.get("anchor"))
    # Never buy back within a cycle (also not after a settings change): the hedge only grows with new
    # protected quantity (DCA) since the last confirmed target; refilling is for cycle end / Re-Hedge All.
    last = _d(rec.get("lastTarget"), str(short_q))
    long_at_last = _d(rec.get("longAtLastTarget"), str(rec.get("longAtStart") or long_q))
    ceiling = last + max(Decimal(0), long_q - long_at_last)
    target = min(long_q, decision["targetShort"], ceiling)
    rec["longAtLastTarget"] = _txt(long_q)
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

    if action == "HOLD" and decision["reason"] == "OVER_HEDGED_LEFT_TO_AUTO_HEDGE":
        # Over-covered (own position on the hedge side): no target, the engine never sells it (vangnet).
        return {"override": None, "record": rec, "event": "OVER_COVERED_HOLD"}

    if action == "HOLD" and decision["reason"] == "STEP_WAIT_PROFIT_AFTER_FEES":
        keep = min(long_q, short_q)
        rec["lastTarget"] = str(keep)
        return {"override": keep, "record": rec, "event": "STEP_WAIT_PROFIT_AFTER_FEES"}

    rec["lastTarget"] = str(target)
    return {"override": target, "record": rec, "event": "STEP_REDUCE" if action == "REDUCE_SHORT" else "LADDER_HOLD"}


def public_unwind(pair: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Compact UNWIND view of an Auto Hedge pair for labels (live record first, else test mode)."""
    pair = pair or {}
    for field, mode in (("shortRecovery", "LIVE"), ("shortRecoveryShadow", "TEST")):
        rec = pair.get(field)
        if not isinstance(rec, Mapping) or not rec.get("phase"):
            continue
        long_q = _d(pair.get("currentProtectedQty"))
        target = _d(rec.get("lastTarget"), "-1")
        hedge_pct = None
        if long_q > 0 and target >= 0:
            hedge_pct = float(min(Decimal(100), target / long_q * 100).quantize(Decimal("0.1")))
        return {
            "mode": mode,
            "phase": str(rec.get("phase")),
            "stepsReached": int(_d(rec.get("stepsReached"))),
            "steps": int(_d(rec.get("steps"))),
            "cycleId": int(_d(rec.get("cycleId"))),
            "hedgePct": hedge_pct,
            "hedgeSide": str(pair.get("hedgeSide") or "SHORT").upper(),
            "lastEvent": str(rec.get("lastEvent") or ""),
        }
    return None
