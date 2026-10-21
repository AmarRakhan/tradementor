"""Pure protection check for the bulk Close Profits button (2.1). No I/O of its own.

The Auto Hedge lock reader is injected so the rule is unit-testable offline and
reader failures propagate (callers fail closed: no order is sent).

Focus Airbag contract (canonical writers: aster_strategy2_focus_multi/_live/_v2):
  * asterStrategy2/{uid}.ownedLegs is a list of OwnedLeg mappings. Every OwnedLeg has
    symbol, side (LONG|SHORT) and a non-empty string role (default "HARVEST").
    An airbag hedge leg has role "FOCUS_SLOT_AIRBAG:<slotId>".
  * focusLiveSlots[] carries one dict per focus slot; slot["airbag"] is a dict when
    that slot's main leg (slot["pair"], slot["side"]) has an airbag.
"Proven no airbag" and "cannot tell" are different outcomes: the latter raises
BulkProtectionUnreliable and the bulk close stops.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

AIRBAG_ROLE_PREFIX = "FOCUS_SLOT_AIRBAG:"
# Written only by Focus Airbag-capable engines (all of them also write ownedLegs).
FOCUS_STATE_KEYS = ("focusLiveSlots", "focusLiveState", "focusCycleState", "focusV2State")
_SIDES = {"LONG", "SHORT"}
_MISSING = object()


class BulkProtectionUnreliable(RuntimeError):
    """Protection data is missing or malformed: a bulk close must not proceed."""


def focus_airbag_protected(state: Any, *, exists: bool, symbol: str, side: str) -> bool:
    """True = leg is a Focus Airbag hedge/main leg; False = PROVEN not; raises if unknowable."""
    symbol = str(symbol).upper().strip()
    side = str(side).upper().strip()
    if not exists:
        return False  # no Strategy-2 document at all: Focus Airbag has never run
    if not isinstance(state, dict):
        raise BulkProtectionUnreliable("Strategy-2 status is geen geldig document")
    legs = state.get("ownedLegs", _MISSING)
    if legs is _MISSING:
        if any(key in state for key in FOCUS_STATE_KEYS):
            raise BulkProtectionUnreliable("Focus-status aanwezig maar ownedLegs ontbreekt")
        return False  # document exists, no focus state at all: proven no airbag
    if not isinstance(legs, list):
        raise BulkProtectionUnreliable("ownedLegs is geen lijst")
    protected = False
    for item in legs:
        if not isinstance(item, dict):
            raise BulkProtectionUnreliable("ownedLegs bevat een ongeldige rij")
        leg_symbol = str(item.get("symbol", "")).upper().strip()
        leg_side = str(item.get("side", "")).upper().strip()
        role = item.get("role")
        if not leg_symbol or leg_side not in _SIDES or not isinstance(role, str) or not role.strip():
            raise BulkProtectionUnreliable("ownedLegs-rij mist symbol, side of role")
        if leg_symbol == symbol and leg_side == side and role.upper().startswith(AIRBAG_ROLE_PREFIX):
            protected = True
    slots = state.get("focusLiveSlots", _MISSING)
    if slots is not _MISSING and not isinstance(slots, list):
        raise BulkProtectionUnreliable("focusLiveSlots is geen lijst")
    for slot in [] if slots is _MISSING else slots:
        if not isinstance(slot, dict):
            raise BulkProtectionUnreliable("focusLiveSlots bevat een ongeldige rij")
        if isinstance(slot.get("airbag"), dict):
            pair = str(slot.get("pair", "")).upper().strip()
            if not pair or str(slot.get("side", "")).upper().strip() not in _SIDES:
                raise BulkProtectionUnreliable("focus-slot met airbag mist pair of side")
            if pair == symbol:  # conservative: both legs of an airbag slot are protected
                protected = True
    return protected


PROTECTED_SUFFIX = "; bulk Close Profits sluit haar niet"   # frontend treats every reason with this suffix as a protected skip
UNRELIABLE_PREFIX = "Eigenaarschaps-/beschermingsgegevens ontbreken of zijn onbetrouwbaar"

RECOVERY_CYCLE_STATES = {"PARTIAL", "FINAL_PENDING"}          # canonical Recovery cycle states (short_recovery_gate)
EMERGENCY_STATUSES = {"OFF", "ARMED", "EXECUTING", "LOCKED"}  # aster_portfolio_emergency_hedge
EMERGENCY_BLOCKING = {"EXECUTING", "LOCKED"}


@dataclass(frozen=True)
class OwnershipContext:
    """Fresh copies of every document that can prove a protection/Recovery/claim owner.

    `*_exists=False` means the document is proven absent (system never configured).
    A read error never reaches this class: the reader raises BulkProtectionUnreliable.
    """
    pair: Any                      # asterPositionLossAutoHedge/{uid}/pairs/{SYMBOL}  ({} when absent)
    dynamic_hedge: Any             # users/{uid}/asterDynamicHedge/control
    dynamic_hedge_exists: bool
    emergency_hedge: Any           # aster_portfolio_emergency_hedges/{uid}
    emergency_hedge_exists: bool
    auto_hedge_settings: Any       # asterPositionLossAutoHedge/{uid}  (holds shortRecoveryPlan)
    auto_hedge_settings_exists: bool
    sniper: Any                    # asterSniper/{uid}
    sniper_exists: bool
    has_same_symbol_long: bool     # live exchange rows: a LONG leg exists on this symbol


def _norm_symbol(value: Any) -> str:
    return str(value or "").upper().strip()


def pair_recovery_reason(pair: Any) -> str | None:
    """Recovery cycle fields live in the Auto Hedge pair document (short_recovery_gate reads them there)."""
    if pair is None:
        return None
    if not isinstance(pair, dict):
        raise BulkProtectionUnreliable("Auto Hedge pair-document is ongeldig")
    state = pair.get("state")
    if state is not None and not isinstance(state, str):
        raise BulkProtectionUnreliable("Recovery-cyclusstatus is ongeldig")
    owner_side = pair.get("ownerSide")
    if (str(state or "").upper() in RECOVERY_CYCLE_STATES
            or (owner_side not in (None, "") and pair.get("cycleConfirmed") is True)):
        return "Deze positie valt onder een Short Recovery 2.0-cyclus" + PROTECTED_SUFFIX
    return None


def dynamic_hedge_reason(control: Any, exists: bool) -> str | None:
    if not exists:
        return None
    if not isinstance(control, dict):
        raise BulkProtectionUnreliable("Dynamic Hedge-status is geen geldig document")
    enabled = control.get("enabled", False)
    if not isinstance(enabled, bool):
        raise BulkProtectionUnreliable("Dynamic Hedge enabled-veld is ongeldig")
    if enabled or str(control.get("ownershipState", "")).upper() == "MANUAL_ACTION_LOCK":
        return "Dynamic Hedge is actief voor dit account" + PROTECTED_SUFFIX
    return None


def emergency_hedge_reason(doc: Any, exists: bool) -> str | None:
    if not exists:
        return None
    if not isinstance(doc, dict):
        raise BulkProtectionUnreliable("Noodhedge-status is geen geldig document")
    status = doc.get("status", "OFF")
    if not isinstance(status, str) or status not in EMERGENCY_STATUSES:
        raise BulkProtectionUnreliable("Noodhedge-status is onbekend")
    if status in EMERGENCY_BLOCKING:
        return f"Portfolio Noodhedge is {status}" + PROTECTED_SUFFIX
    return None


def recovery_plan_reason(settings: Any, exists: bool, has_same_symbol_long: bool) -> str | None:
    """Short Recovery 2.0 ownership of a SHORT is not persisted per leg yet (offline/shadow), so while
    the plan is enabled every SHORT that has a same-symbol LONG might be Recovery-owned: not provable
    -> excluded. Disabled / never configured -> Classic, unchanged behaviour."""
    from short_recovery_gate import resolve_existing_active_strategy
    if not exists:
        return None
    plan = settings.get("shortRecoveryPlan") if isinstance(settings, dict) else None
    if isinstance(plan, dict) and "enabled" in plan and not isinstance(plan["enabled"], bool):
        # the canonical resolver would read a non-bool flag as "off"; for a bulk SELL that is not proof
        raise BulkProtectionUnreliable("Short Recovery enabled-veld is ongeldig")
    outcome = resolve_existing_active_strategy(settings)
    if outcome == "BLOCKED_INVALID_ACTIVE_SETTINGS":
        raise BulkProtectionUnreliable("Short Recovery-instellingen zijn ongeldig")
    if outcome == "AUTO_HEDGE_SHORT_RECOVERY_2" and has_same_symbol_long:
        return "Short Recovery 2.0 is actief en kan deze SHORT beheren" + PROTECTED_SUFFIX
    return None


def inflight_claim_reason(symbol: str, strategy2_state: Any, strategy2_exists: bool,
                          sniper: Any, sniper_exists: bool) -> str | None:
    """Exclusive in-flight claims (aster_symbol_ownership): Strategy-2 pending reopen / current queue intent,
    Sniper pending intent and active Sniper trades."""
    symbol = _norm_symbol(symbol)

    def symbols_of(rows: Any, what: str) -> set[str]:
        if rows is None:
            return set()
        if not isinstance(rows, list):
            raise BulkProtectionUnreliable(f"{what} is geen lijst")
        found = set()
        for row in rows:
            if not isinstance(row, dict):
                raise BulkProtectionUnreliable(f"{what} bevat een ongeldige rij")
            found.add(_norm_symbol(row.get("symbol")))
        return found

    claimed: set[str] = set()
    if strategy2_exists:
        if not isinstance(strategy2_state, dict):
            raise BulkProtectionUnreliable("Strategy-2 status is geen geldig document")
        claimed |= symbols_of(strategy2_state.get("pendingReopens"), "pendingReopens")
        queue = strategy2_state.get("orderQueueState")
        if queue is not None:
            if not isinstance(queue, dict):
                raise BulkProtectionUnreliable("orderQueueState is ongeldig")
            intent = queue.get("currentIntent")
            if intent is not None:
                if not isinstance(intent, dict):
                    raise BulkProtectionUnreliable("currentIntent is ongeldig")
                claimed.add(_norm_symbol(intent.get("symbol")))
    if claimed and symbol in claimed:
        return "Een strategie heeft een order in uitvoering voor dit symbool" + PROTECTED_SUFFIX
    if sniper_exists:
        if not isinstance(sniper, dict):
            raise BulkProtectionUnreliable("Sniper-status is geen geldig document")
        sniper_claims = symbols_of(sniper.get("activeTrades"), "activeTrades")
        pending = sniper.get("pendingIntent")
        if pending is not None:
            if not isinstance(pending, dict):
                raise BulkProtectionUnreliable("pendingIntent is ongeldig")
            sniper_claims.add(_norm_symbol(pending.get("symbol")))
        if symbol in sniper_claims:
            return "Deze positie hoort bij een actieve Sniper-trade" + PROTECTED_SUFFIX
    return None


def bulk_profit_close_block_reason(
    uid: str, symbol: str, side: str, strategy2_state: Any,
    *, strategy2_exists: bool = True, managed_check: Callable[..., bool], ownership: OwnershipContext,
) -> str | None:
    """Return a Dutch reason when a bulk profit close must not touch this leg.

    Raises (never returns None) when ownership/protection cannot be established:
    managed_check errors (AutoHedgeCloseBlocked) and BulkProtectionUnreliable.
    `ownership` is mandatory so no caller can silently skip the cross-system checks.
    """
    symbol = _norm_symbol(symbol)
    side = str(side).upper().strip()
    if side != "SHORT":
        return "Bulk Close Profits sluit alleen SHORT-posities; LONG vereist een geverifieerde hedgekoppeling"
    if managed_check(account_uid=uid, symbol=symbol):
        return "Deze positie valt onder Auto Hedge" + PROTECTED_SUFFIX
    reason = pair_recovery_reason(ownership.pair)
    if reason:
        return reason
    if focus_airbag_protected(strategy2_state, exists=strategy2_exists, symbol=symbol, side=side):
        return "Deze positie is een Focus Airbag-hedge" + PROTECTED_SUFFIX
    return (
        dynamic_hedge_reason(ownership.dynamic_hedge, ownership.dynamic_hedge_exists)
        or emergency_hedge_reason(ownership.emergency_hedge, ownership.emergency_hedge_exists)
        or recovery_plan_reason(ownership.auto_hedge_settings, ownership.auto_hedge_settings_exists,
                                ownership.has_same_symbol_long)
        or inflight_claim_reason(symbol, strategy2_state, strategy2_exists, ownership.sniper, ownership.sniper_exists)
    )
