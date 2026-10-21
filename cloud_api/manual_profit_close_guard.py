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


def bulk_profit_close_block_reason(
    uid: str, symbol: str, side: str, strategy2_state: Any,
    *, strategy2_exists: bool = True, managed_check: Callable[..., bool],
) -> str | None:
    """Return a Dutch reason when a bulk profit close must not touch this leg.

    Raises (never returns None) when protection status cannot be established:
    managed_check errors (AutoHedgeCloseBlocked) and BulkProtectionUnreliable.
    """
    symbol = str(symbol).upper().strip()
    side = str(side).upper().strip()
    if side != "SHORT":
        return "Bulk Close Profits sluit alleen SHORT-posities; LONG vereist een geverifieerde hedgekoppeling"
    if managed_check(account_uid=uid, symbol=symbol):
        return "Deze positie valt onder Auto Hedge; bulk Close Profits sluit haar niet"
    if focus_airbag_protected(strategy2_state, exists=strategy2_exists, symbol=symbol, side=side):
        return "Deze positie is een Focus Airbag-hedge; bulk Close Profits sluit haar niet"
    return None
