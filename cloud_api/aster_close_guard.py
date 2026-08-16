"""One fail-closed net-profit gate for every automatic Aster close order."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import math
import os


BLOCK_MESSAGE = "Sluiting geblokkeerd: verwacht nettoresultaat is niet positief"


class AsterCloseBlocked(RuntimeError):
    def __init__(self, event: dict[str, Any]):
        self.event = event
        super().__init__(f"{BLOCK_MESSAGE} ({event['blockReason']})")


@dataclass(frozen=True)
class CloseEvidence:
    account_uid: str
    symbol: str
    side: str
    caller: str
    reason: str
    quantity: float
    entry_price: float
    mark_price: float
    gross_pnl: float
    entry_fees: float
    close_fee: float
    funding: float
    slippage_buffer: float
    other_costs: float = 0.0
    ownership_reliable: bool = False
    fills_reliable: bool = False
    prices_reliable: bool = False
    costs_reliable: bool = False
    minimum_positive_buffer: float | None = None

    @property
    def expected_net(self) -> float:
        return self.gross_pnl + self.funding - self.entry_fees - self.close_fee - self.slippage_buffer - self.other_costs


def configured_minimum_positive_buffer() -> float:
    try:
        value = float(os.getenv("ASTER_MINIMUM_CLOSE_PROFIT_USD", "0.01"))
    except ValueError:
        value = 0.01
    return max(0.01, value)


def require_profitable_automatic_close(
    evidence: CloseEvidence | None,
    *,
    audit: Callable[[dict[str, Any]], None] | None = None,
) -> CloseEvidence:
    reliable = evidence is not None and all((
        evidence.account_uid, evidence.symbol, evidence.side, evidence.caller,
        evidence.quantity > 0, evidence.entry_price > 0, evidence.mark_price > 0,
        evidence.ownership_reliable, evidence.fills_reliable,
        evidence.prices_reliable, evidence.costs_reliable,
    ))
    values = () if evidence is None else (
        evidence.quantity, evidence.entry_price, evidence.mark_price, evidence.gross_pnl,
        evidence.entry_fees, evidence.close_fee, evidence.funding,
        evidence.slippage_buffer, evidence.other_costs, evidence.expected_net,
    )
    finite = bool(values) and all(math.isfinite(value) for value in values)
    minimum = configured_minimum_positive_buffer() if evidence is None else max(
        configured_minimum_positive_buffer(), evidence.minimum_positive_buffer or 0.0)
    expected = None if evidence is None or not finite else evidence.expected_net
    block_reason = "onvolledige of onbetrouwbare sluitgegevens"
    if reliable and finite and expected is not None and expected < minimum:
        block_reason = f"verwacht nettoresultaat {expected:.8f} is lager dan positieve buffer {minimum:.8f}"
    if reliable and finite and expected is not None and expected >= minimum:
        return evidence
    event = {
        "event": "AUTOMATIC_ASTER_CLOSE_BLOCKED",
        "accountUid": evidence.account_uid if evidence else "",
        "symbol": evidence.symbol if evidence else "",
        "side": evidence.side if evidence else "",
        "caller": evidence.caller if evidence else "unknown",
        "proposedQuantity": evidence.quantity if evidence else None,
        "grossPnl": evidence.gross_pnl if evidence else None,
        "entryFees": evidence.entry_fees if evidence else None,
        "closeFee": evidence.close_fee if evidence else None,
        "funding": evidence.funding if evidence else None,
        "slippageBuffer": evidence.slippage_buffer if evidence else None,
        "otherCosts": evidence.other_costs if evidence else None,
        "expectedNetResult": expected,
        "minimumPositiveBuffer": minimum,
        "originalReason": evidence.reason if evidence else "",
        "blockReason": block_reason,
        "message": BLOCK_MESSAGE,
    }
    if audit:
        audit(event)
    raise AsterCloseBlocked(event)
