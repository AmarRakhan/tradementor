"""Durable, account-scoped order queue primitives for Strategy 2.

This module is deliberately exchange and database agnostic.  The production
adapter owns persistence and Aster reconciliation; this core makes the order
budget, priority and uncertain-outcome rules deterministic and testable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum
import hashlib
from typing import Any, Iterable, Literal

MAX_ORDERS_PER_ACCOUNT_SCAN = 15
QUEUE_FEATURE_FLAG = "ASTER_STRATEGY2_ORDER_QUEUE_ENABLED"

ActionKind = Literal["RISK_REDUCE", "TAKE_PROFIT_CLOSE", "REOPEN", "DCA", "OPEN_BASE"]
Outcome = Literal["CONFIRMED", "REJECTED", "UNCERTAIN"]


class Priority(IntEnum):
    RISK_REDUCE = 1
    TAKE_PROFIT_CLOSE = 2
    REOPEN = 3
    DCA = 4
    OPEN_BASE = 5


@dataclass(frozen=True)
class QueueAction:
    kind: ActionKind
    symbol: str
    side: str
    cycle_id: str
    quantity: float = 0.0
    notional: float = 0.0
    package_id: str = ""
    source_cycle_id: str = ""
    reason: str = ""
    sequence: int = 0

    @property
    def priority(self) -> Priority:
        return Priority[self.kind]

    def idempotency_key(self, account_uid: str) -> str:
        material = "|".join((account_uid, self.kind, self.symbol.upper(), self.side.upper(),
                             self.cycle_id, self.package_id, str(self.sequence)))
        return "s2q-" + hashlib.sha256(material.encode()).hexdigest()[:28]


@dataclass
class PendingReopen:
    symbol: str
    side: str
    closed_cycle_id: str
    package_id: str
    notional: float
    created_scan_id: str
    reason: str = "ORDER_BUDGET_EXHAUSTED"
    cooldown_until_ms: int = 0
    attempts: int = 0


@dataclass
class QueueState:
    account_uid: str
    scan_id: str
    orders_used: int = 0
    halted_uncertain: bool = False
    uncertain_key: str = ""
    pending_reopens: list[PendingReopen] = field(default_factory=list)
    confirmed_keys: set[str] = field(default_factory=set)
    rejected_keys: set[str] = field(default_factory=set)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "QueueState":
        return cls(
            account_uid=str(value.get("account_uid", "")), scan_id=str(value.get("scan_id", "")),
            orders_used=int(value.get("orders_used", 0)),
            halted_uncertain=bool(value.get("halted_uncertain", False)),
            uncertain_key=str(value.get("uncertain_key", "")),
            pending_reopens=[PendingReopen(**item) for item in value.get("pending_reopens", [])],
            confirmed_keys=set(value.get("confirmed_keys", [])),
            rejected_keys=set(value.get("rejected_keys", [])),
        )

    def to_mapping(self) -> dict[str, Any]:
        result = asdict(self)
        result["confirmed_keys"] = sorted(self.confirmed_keys)
        result["rejected_keys"] = sorted(self.rejected_keys)
        return result

    @property
    def remaining(self) -> int:
        return max(0, MAX_ORDERS_PER_ACCOUNT_SCAN - self.orders_used)

    def may_send(self, action: QueueAction) -> bool:
        key = action.idempotency_key(self.account_uid)
        return not self.halted_uncertain and self.remaining > 0 and key not in self.confirmed_keys

    def record_sent_outcome(self, action: QueueAction, outcome: Outcome) -> None:
        """Record exactly one request that reached Aster.

        Validation failures must never call this method.  CONFIRMED includes a
        reliable complete or partial fill whose actual quantity is persisted by
        the adapter before processing another action.
        """
        if self.halted_uncertain:
            raise RuntimeError("account scan is halted pending exchange reconciliation")
        if self.remaining <= 0:
            raise RuntimeError("account scan order budget exhausted")
        key = action.idempotency_key(self.account_uid)
        if key in self.confirmed_keys:
            raise RuntimeError("confirmed action must not be sent twice")
        self.orders_used += 1
        if outcome == "CONFIRMED":
            self.confirmed_keys.add(key)
        elif outcome == "REJECTED":
            self.rejected_keys.add(key)
        elif outcome == "UNCERTAIN":
            self.halted_uncertain = True
            self.uncertain_key = key
        else:
            raise ValueError(f"unknown outcome: {outcome}")


def ordered_actions(*, risk: Iterable[QueueAction] = (), profits: Iterable[QueueAction] = (),
                    pending_reopens: Iterable[QueueAction] = (), dca: Iterable[QueueAction] = (),
                    entries: Iterable[QueueAction] = ()) -> list[QueueAction]:
    """Return the exact cross-category safety order.

    A reopen carried over because the prior scan had only one slot left is the
    highest non-emergency action in the next scan. Fresh risk reduction always
    remains first. Other profitable closes then precede DCA and new entries.
    Within a category the caller's stable ranking is retained.
    """
    groups = (risk, pending_reopens, profits, dca, entries)
    return [action for group in groups for action in group]


def pending_reopen_for(close: QueueAction, *, scan_id: str, base_notional: float) -> PendingReopen:
    if close.kind != "TAKE_PROFIT_CLOSE":
        raise ValueError("pending reopen requires a confirmed take-profit close")
    return PendingReopen(close.symbol, close.side, close.cycle_id,
                         close.package_id or close.idempotency_key("package"),
                         base_notional, scan_id)


def build_reopen(item: PendingReopen, *, sequence: int = 0) -> QueueAction:
    return QueueAction("REOPEN", item.symbol, item.side,
                       f"reopen-{item.closed_cycle_id}", notional=item.notional,
                       package_id=item.package_id, source_cycle_id=item.closed_cycle_id,
                       reason="PENDING_REOPEN", sequence=sequence)


def initial_build_actions(*, missing_long: int, missing_short: int, symbols: Iterable[str],
                          cycle_prefix: str, base_notional: float) -> list[QueueAction]:
    """Create a balanced deterministic build plan; budget is enforced on send."""
    available = list(dict.fromkeys(symbol.upper() for symbol in symbols if symbol))
    result: list[QueueAction] = []
    long_left, short_left = max(0, missing_long), max(0, missing_short)
    index = 0
    while available and (long_left or short_left):
        side = "LONG" if long_left >= short_left and long_left else "SHORT"
        symbol = available.pop(0)
        result.append(QueueAction("OPEN_BASE", symbol, side, f"{cycle_prefix}-{index}",
                                  notional=base_notional, sequence=index))
        long_left -= side == "LONG"
        short_left -= side == "SHORT"
        index += 1
    return result


def build_shadow_plan(*, state: QueueState, risk: Iterable[QueueAction] = (),
                      profits: Iterable[QueueAction] = (),
                      pending_reopens: Iterable[QueueAction] = (),
                      dca: Iterable[QueueAction] = (),
                      entries: Iterable[QueueAction] = ()) -> dict[str, Any]:
    """Return a strictly side-effect-free view of one account queue scan.

    The caller supplies already validated snapshot-derived candidates.  This
    function performs no exchange, database, lock or clock access and never
    mutates ``state``.  It is therefore safe for shadow comparison while the
    live account remains on the old runtime.
    """
    ordered = ordered_actions(risk=risk, profits=profits,
                              pending_reopens=pending_reopens, dca=dca,
                              entries=entries)
    remaining = state.remaining
    selected: list[QueueAction] = []
    if not state.halted_uncertain:
        for item in ordered:
            if len(selected) >= remaining:
                break
            key = item.idempotency_key(state.account_uid)
            if key in state.confirmed_keys:
                continue
            selected.append(item)
    counts = {kind: 0 for kind in ("RISK_REDUCE", "REOPEN", "TAKE_PROFIT_CLOSE", "DCA", "OPEN_BASE")}
    for item in selected:
        counts[item.kind] += 1
    account_ref = hashlib.sha256(state.account_uid.encode()).hexdigest()[:12]
    return {
        "readOnly": True,
        "accountRef": account_ref,
        "scanId": state.scan_id,
        "ordersAlreadyUsed": state.orders_used,
        "maximumOrders": MAX_ORDERS_PER_ACCOUNT_SCAN,
        "remainingBudget": remaining,
        "haltedUncertain": state.halted_uncertain,
        "candidateCount": len(ordered),
        "wouldSendCount": len(selected),
        "counts": counts,
        "actions": [{
            "priority": int(item.priority), "kind": item.kind,
            "symbol": item.symbol, "side": item.side,
            "cycleId": item.cycle_id,
            "packageId": item.package_id,
            "idempotencyKey": item.idempotency_key(state.account_uid),
        } for item in selected],
    }
