"""Deterministic, finite work queues for one Strategy-3 scheduler tick.

The module is deliberately exchange- and Firestore-free.  The live runtime
uses it to assign stable action identities, preserve phase ordering and decide
which unfinished actions must survive in the next minute.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Callable, Iterable, Literal


ActionKind = Literal[
    "ASSIGN_PROTECTION", "PARTIAL_TP", "TRAILING_TP", "FULL_TP",
    "ADD_DCA", "OPEN_BASE",
]
OutcomeStatus = Literal["confirmed", "bookkeeping", "rejected", "uncertain"]

PHASE_PRIORITY: dict[str, int] = {
    "ASSIGN_PROTECTION": 10,
    "PARTIAL_TP": 20,
    "TRAILING_TP": 20,
    "FULL_TP": 20,
    "ADD_DCA": 30,
    "OPEN_BASE": 40,
}


@dataclass(frozen=True)
class Strategy3Action:
    kind: ActionKind
    symbol: str
    side: str
    cycle_id: str
    config_version: int
    generation: int = 0
    notional: float = 0.0
    reason: str = ""
    tick_id: str = ""

    @property
    def risk_increasing(self) -> bool:
        return self.kind in {"ADD_DCA", "OPEN_BASE"}

    @property
    def risk_reducing(self) -> bool:
        return self.kind in {"PARTIAL_TP", "TRAILING_TP", "FULL_TP"}

    @property
    def action_id(self) -> str:
        # generation is the DCA number, entry slot or close generation.  It
        # makes successive valid actions unique while retries stay identical.
        raw = "|".join((
            "aster-strategy-3", self.cycle_id, str(self.config_version),
            self.kind, self.symbol.upper(), self.side.upper(), str(self.generation),
        ))
        return "s3a-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @property
    def lock_key(self) -> str:
        return f"{self.symbol.upper()}|{self.side.upper()}"

    def public_dict(self) -> dict[str, Any]:
        return {
            "tickId": self.tick_id,
            "actionId": self.action_id,
            "kind": self.kind,
            "symbol": self.symbol.upper(),
            "side": self.side.upper(),
            "cycleId": self.cycle_id,
            "configVersion": self.config_version,
            "generation": self.generation,
            "notional": self.notional,
            "reason": self.reason,
            "riskIncreasing": self.risk_increasing,
        }


@dataclass(frozen=True)
class ActionOutcome:
    status: OutcomeStatus
    orders_sent: int = 0
    filled_quantity: float = 0.0
    reason: str = ""
    partial: bool = False


@dataclass
class WorkQueueResult:
    executed: list[Strategy3Action] = field(default_factory=list)
    rejected: list[Strategy3Action] = field(default_factory=list)
    uncertain: list[Strategy3Action] = field(default_factory=list)
    backlog: list[Strategy3Action] = field(default_factory=list)
    orders_sent: int = 0
    block_reason: str = ""
    refreshes: int = 0

    def count(self, *kinds: str) -> int:
        allowed = set(kinds)
        return sum(1 for action in self.executed if action.kind in allowed)


def ordered_actions(actions: Iterable[Strategy3Action]) -> list[Strategy3Action]:
    """Stable phase ordering with a deterministic tie-breaker."""
    return sorted(actions, key=lambda action: (
        PHASE_PRIORITY[action.kind], action.symbol.upper(), action.side.upper(),
        action.generation, action.action_id,
    ))


def run_finite_work_queue(
    actions: Iterable[Strategy3Action],
    *,
    execute: Callable[[Strategy3Action], ActionOutcome],
    refresh: Callable[[Strategy3Action], None],
    has_time: Callable[[], bool] = lambda: True,
    before_action: Callable[[Strategy3Action], bool] = lambda _action: True,
) -> WorkQueueResult:
    """Process a finite snapshot without an artificial action-count ceiling.

    The caller remains responsible for exchange/risk decisions.  A confirmed
    risk-increasing action is always followed by an authoritative refresh.
    An uncertain outcome stops all later work; no blind retry is performed.
    """
    queue = ordered_actions(actions)
    result = WorkQueueResult()
    for index, action in enumerate(queue):
        if not has_time():
            result.backlog.extend(queue[index:])
            result.block_reason = "Veilige ticklooptijd of rate-capaciteit is opgebruikt"
            break
        if not before_action(action):
            result.backlog.extend(queue[index:])
            result.block_reason = "Actuele exchange-, margin- of risicocontrole blokkeert vervolg"
            break
        outcome = execute(action)
        result.orders_sent += outcome.orders_sent
        if outcome.status == "rejected":
            result.rejected.append(action)
            continue
        if outcome.status == "uncertain":
            result.uncertain.append(action)
            result.backlog.extend(queue[index + 1:])
            result.block_reason = outcome.reason or "Orderuitkomst is onzeker; reconciliation vereist"
            break
        result.executed.append(action)
        if outcome.partial:
            result.uncertain.append(action)
            result.backlog.extend(queue[index + 1:])
            result.block_reason = outcome.reason or "Partial fill vereist reconciliation"
            break
        if action.risk_increasing:
            refresh(action)
            result.refreshes += 1
    return result


def merge_backlog(*groups: Iterable[Strategy3Action]) -> list[dict[str, Any]]:
    """Deduplicate a persisted backlog without changing priority order."""
    unique: dict[str, Strategy3Action] = {}
    for action in ordered_actions(item for group in groups for item in group):
        unique.setdefault(action.action_id, action)
    return [action.public_dict() for action in unique.values()]
