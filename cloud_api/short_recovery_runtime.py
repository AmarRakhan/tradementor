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

from short_recovery_ladder import effective_parts, grid_released, grid_step, normalize_settings, plan, profitable_after_fees

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
        "sold": 0,
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

    if phase in (PHASE_REOPEN_CLOSE, PHASE_REOPEN_OPEN):
        # Build 634: the close-all / reopen-90 route is gone (small coins use fewer, larger grid parts). A record
        # still in such a phase goes back to 1:1 by buying only, and a fresh grid cycle starts from there.
        rec.update(phase=PHASE_REFILL, reopenQty=None, lastTarget=str(long_q))
        return {"override": None, "record": rec, "event": "REOPEN_PHASE_REPLACED_BY_GRID"}

    return _grid(rec=rec, cfg=cfg, long_q=long_q, short_q=short_q, entry=_d(short_entry), price=price, step=step,
                 min_qty=min_qty, min_notional=min_notional, direction=str(rec.get("direction") or direction))


def _grid(*, rec: dict[str, Any], cfg: Mapping[str, Any], long_q: Decimal, short_q: Decimal, entry: Decimal,
          price: Decimal, step: Decimal, min_qty: Any, min_notional: Any, direction: str) -> dict[str, Any]:
    """Build 634 (Amar 23-10): grid on the hedge inside one cycle (phase LADDER).

    Fixed levels from the cycle anchor. Away from the anchor: sell one more part per level (profit after fees
    only). Back towards the anchor ``rebuySteps`` levels above the last sold part: buy that part back. Everything
    sold and the price ``safetyNetPct`` beyond the last level: re-hedge 100% (vangnet), new cycle at that price.
    Settings apply at once; a changed grid keeps the hedge as it is and re-counts the sold parts on the new grid.
    """
    base = _d(rec.get("base"))
    growth = max(Decimal(0), long_q - _d(rec.get("longAtStart")))
    cap = base + growth                       # DCA after the cycle start stays fully hedged
    if short_q > cap + (step / 2 if step > 0 else Decimal(0)):
        return {"override": None, "record": rec, "event": "OVER_COVERED_HOLD"}
    anchor = _d(rec.get("anchor"))
    if anchor <= 0:
        anchor = entry if entry > 0 else price
    grid_key = f"{cfg['steps']}|{cfg['totalPct']}|{cfg['rebuySteps']}"
    regrid = rec.get("gridKey") != grid_key or rec.get("sold") is None or rec.get("gridParts") is None
    # The number of parts is fixed per cycle (decided at the anchor price), so it never jitters with the price.
    n = effective_parts(base, cfg["steps"], anchor, step, min_qty, min_notional) if regrid else int(rec["gridParts"])
    if n <= 0:
        rec.update(lastTarget=str(min(long_q, short_q)), steps=0, gridParts=0, gridKey=grid_key, sold=0)
        return {"override": None, "record": rec, "event": "SKIPPED_BELOW_MINIMUM"}
    if regrid:
        # New grid (or a pre-634 ladder record): keep the hedge as it is, count its sold parts on this grid.
        released = max(Decimal(0), cap - short_q)
        sold = int((released / base * n).to_integral_value()) if base > 0 else 0
        sold = max(0, min(n, sold))
    else:
        sold = max(0, min(n, int(rec.get("sold") or 0)))
    decision = grid_step(anchor=anchor, price=price, sold=sold, n=n, total_pct=cfg["totalPct"],
                         rebuy_steps=min(int(cfg["rebuySteps"]), n), safety_pct=cfg["safetyNetPct"],
                         direction=direction, hedge_entry=entry if entry > 0 else None)
    event = decision["event"]
    rec.update(anchor=_txt(anchor), gridKey=grid_key, gridParts=n, steps=n, totalPct=cfg["totalPct"],
               stepPct=cfg["stepPct"], rebuySteps=cfg["rebuySteps"], safetyNetPct=cfg["safetyNetPct"])
    if event == "SAFETY_NET_REHEDGE":
        rec.update(phase=PHASE_REFILL, anchorAtMark=True, sold=None, lastTarget=str(long_q))
        return {"override": None, "record": rec, "event": event}
    sold = decision["sold"]
    target = max(Decimal(0), min(long_q, cap - grid_released(base, sold, n, step)))
    rec.update(sold=sold, stepsReached=sold, lastTarget=_txt(target))
    return {"override": target, "record": rec, "event": event}


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
