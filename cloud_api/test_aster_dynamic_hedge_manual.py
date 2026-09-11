from __future__ import annotations

import pytest

from aster_dynamic_hedge_manual import (
    ManualActionMismatch,
    begin_manual_action,
    complete_manual_action,
    fail_manual_action,
    position_quantities,
    validate_manual_close_scope,
)


class FakeSnapshot:
    def __init__(self, data): self.data = data
    def to_dict(self): return dict(self.data)


class FakeRef:
    def __init__(self, data=None): self.data = dict(data or {}); self.writes = []
    def get(self): return FakeSnapshot(self.data)
    def set(self, value, merge=False):
        if merge: self.data.update(value)
        else: self.data = dict(value)
        self.writes.append(dict(value))


def row(symbol, side, qty):
    return {"symbol": symbol, "positionSide": side, "positionAmt": qty if side == "LONG" else -qty}


def test_position_quantities_keeps_dual_side_separate():
    out = position_quantities([row("BTCUSDT", "LONG", 2), row("BTCUSDT", "SHORT", 3)])
    assert out[("BTCUSDT", "LONG")] == 2
    assert out[("BTCUSDT", "SHORT")] == 3


def test_close_long_cannot_change_short_leg():
    before = [row("BTCUSDT", "LONG", 2), row("BTCUSDT", "SHORT", 3)]
    after = [row("BTCUSDT", "LONG", 1), row("BTCUSDT", "SHORT", 3)]
    proof = validate_manual_close_scope(before, after, "LONG")
    assert proof["validated"] is True
    assert proof["changed"] == [{"symbol": "BTCUSDT", "side": "LONG", "before": 2.0, "after": 1.0}]


def test_close_long_rejects_any_short_change():
    before = [row("BTCUSDT", "LONG", 2), row("BTCUSDT", "SHORT", 3)]
    after = [row("BTCUSDT", "LONG", 1), row("BTCUSDT", "SHORT", 2)]
    with pytest.raises(ManualActionMismatch):
        validate_manual_close_scope(before, after, "LONG")


def test_close_short_cannot_change_long_leg():
    before = [row("BTCUSDT", "LONG", 2), row("BTCUSDT", "SHORT", 3)]
    after = [row("BTCUSDT", "LONG", 2), row("BTCUSDT", "SHORT", 1)]
    proof = validate_manual_close_scope(before, after, "SHORT")
    assert proof["changed"][0]["side"] == "SHORT"


def test_close_short_rejects_any_long_change():
    before = [row("BTCUSDT", "LONG", 2), row("BTCUSDT", "SHORT", 3)]
    after = [row("BTCUSDT", "LONG", 1), row("BTCUSDT", "SHORT", 1)]
    with pytest.raises(ManualActionMismatch):
        validate_manual_close_scope(before, after, "SHORT")


def test_all_close_allows_only_reductions_never_new_exposure():
    before = [row("BTCUSDT", "LONG", 2), row("BTCUSDT", "SHORT", 3)]
    assert validate_manual_close_scope(before, [], "ALL")["validated"] is True
    with pytest.raises(ManualActionMismatch):
        validate_manual_close_scope(before, [row("BTCUSDT", "LONG", 2.1)], "ALL")


def test_disabled_dynamic_hedge_does_not_lock_manual_close():
    ref = FakeRef({"enabled": False, "ownershipState": "NORMAL"})
    guard = begin_manual_action(ref, "SHORT", [row("BTCUSDT", "SHORT", 2)])
    assert guard.active is False
    assert ref.writes == []


def test_enabled_dynamic_hedge_enters_manual_lock_before_close():
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    guard = begin_manual_action(ref, "SHORT", [row("BTCUSDT", "SHORT", 2)])
    assert guard.active is True
    assert ref.data["ownershipState"] == "MANUAL_ACTION_LOCK"
    assert ref.data["manualAction"]["status"] == "LOCKED"


def test_successful_manual_close_returns_to_adopting_not_active():
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    guard = begin_manual_action(ref, "LONG", [row("BTCUSDT", "LONG", 2), row("BTCUSDT", "SHORT", 3)])
    complete_manual_action(ref, guard, [row("BTCUSDT", "LONG", 1), row("BTCUSDT", "SHORT", 3)])
    assert ref.data["ownershipState"] == "ADOPTING"
    assert ref.data["stableReads"] == 0
    assert ref.data["manualAction"]["status"] == "EXCHANGE_CONFIRMED"


def test_mismatch_keeps_dynamic_hedge_locked():
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    guard = begin_manual_action(ref, "LONG", [row("BTCUSDT", "LONG", 2), row("BTCUSDT", "SHORT", 3)])
    with pytest.raises(ManualActionMismatch):
        complete_manual_action(ref, guard, [row("BTCUSDT", "LONG", 1), row("BTCUSDT", "SHORT", 2)])
    assert ref.data["ownershipState"] == "MANUAL_ACTION_LOCK"
    assert ref.data["manualAction"]["status"] == "MISMATCH"


def test_ambiguous_failure_keeps_dynamic_hedge_locked():
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    guard = begin_manual_action(ref, "SHORT", [row("BTCUSDT", "SHORT", 3)])
    fail_manual_action(ref, guard, "Aster timeout na submit")
    assert ref.data["ownershipState"] == "MANUAL_ACTION_LOCK"
    assert ref.data["manualAction"]["status"] == "UNCERTAIN"
