"""Pure, fail-closed Money Grabber portfolio-round and protected-pair domain.

No function in this module places an exchange order.  It produces validated,
idempotent intents that the Strategy-2 execution adapter must reconcile with
real positions, orders and fills before changing persistent state.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal
import math

PairState = Literal["FREE", "PROTECTION_PENDING", "PARTIAL_PROTECTION",
    "FULL_PROTECTION_PENDING", "LOCKED", "PAIR_CLOSE_PENDING", "PAIR_CLOSING",
    "COOLDOWN", "RECOVERY", "CLOSED"]
RoundState = Literal["PREVIEW", "ACTIVE", "ROUND_CLOSE_PENDING", "ROUND_CLOSING",
    "RECOVERY", "CLOSED"]
Side = Literal["LONG", "SHORT"]

BLOCKED_PAIR_STATES = frozenset({"PROTECTION_PENDING", "PARTIAL_PROTECTION",
    "FULL_PROTECTION_PENDING", "LOCKED", "PAIR_CLOSE_PENDING", "PAIR_CLOSING",
    "COOLDOWN", "RECOVERY"})


def _finite_positive(value: float, label: str, *, allow_zero: bool = False) -> float:
    if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{label} moet een geldig positief getal zijn")
    return value


@dataclass(frozen=True)
class NetValueEvidence:
    visible_equity: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    paid_fees: float = 0.0
    expected_exit_fees: float = 0.0
    funding: float = 0.0
    other_costs: float = 0.0
    spread_cost: float = 0.0
    slippage_buffer: float = 0.0
    fresh: bool = False
    reliable: bool = False
    captured_at_ms: int = 0

    def expected_net_close_value(self) -> float:
        if not self.fresh or not self.reliable or self.captured_at_ms <= 0:
            raise ValueError("Netto accountwaarde is niet fris en betrouwbaar bewezen")
        _finite_positive(self.visible_equity, "Exchange-equity", allow_zero=True)
        costs = self.expected_exit_fees + self.other_costs + self.spread_cost + self.slippage_buffer
        for value in (self.realized_pnl, self.unrealized_pnl, self.paid_fees,
                      self.expected_exit_fees, self.funding, self.other_costs,
                      self.spread_cost, self.slippage_buffer):
            if not math.isfinite(value): raise ValueError("Financieel bewijs bevat een ongeldige waarde")
        # Equity already includes current realized/unrealized P&L and paid costs.
        return self.visible_equity - costs


@dataclass(frozen=True)
class Round:
    account_id: str
    round_id: str
    status: RoundState
    start_net_value: float
    target_ratio: float
    target_net_value: float
    started_at_ms: int
    consecutive_target_proofs: int = 0
    close_intent_id: str = ""


@dataclass(frozen=True)
class ProtectedPair:
    account_id: str
    round_id: str
    symbol: str
    original_side: Side
    status: PairState = "FREE"
    original_notional: float = 0.0
    protection_notional: float = 0.0
    residual_notional: float = 0.0
    intent_id: str = ""
    cooldown_scans: int = 0

    @property
    def protection_side(self) -> Side:
        return "SHORT" if self.original_side == "LONG" else "LONG"


@dataclass(frozen=True)
class Intent:
    intent_id: str
    kind: Literal["PAIR_PROTECTION_RISK_REDUCING", "CLOSE_PROTECTED_PAIR", "CLOSE_ALL_ROUND"]
    account_id: str
    round_id: str
    symbol: str = ""
    side: Side | None = None
    target_notional: float = 0.0
    reduce_only: bool = False
    reason: str = ""


def start_round(*, account_id: str, round_id: str, target_ratio: float,
                evidence: NetValueEvidence, activation_confirmed: bool,
                ownership_reliable: bool, hedge_mode: bool,
                orders_known: bool, contracts_known: bool,
                protection_margin_sufficient: bool, now_ms: int) -> Round:
    if not activation_confirmed: raise ValueError("De Money Grabber-activatiepreview is nog niet bevestigd")
    if not all((ownership_reliable, hedge_mode, orders_known, contracts_known,
                protection_margin_sufficient)):
        raise ValueError("Money Grabber-ronde fail-closed: veiligheidsbewijs is onvolledig")
    if not account_id or not round_id or now_ms <= 0: raise ValueError("Account-, ronde- of tijdidentiteit ontbreekt")
    if not math.isfinite(target_ratio) or not 0 < target_ratio <= .50:
        raise ValueError("Rondedoel moet tussen 0 en 50% liggen")
    start = evidence.expected_net_close_value()
    if start <= 0: raise ValueError("Netto startwaarde moet positief zijn")
    return Round(account_id, round_id, "ACTIVE", start, target_ratio,
                 start * (1 + target_ratio), now_ms)


def adverse_move(side: Side, weighted_entry: float, mark_price: float) -> float:
    _finite_positive(weighted_entry, "Gewogen entry")
    _finite_positive(mark_price, "Markprijs")
    return max(0.0, (weighted_entry-mark_price)/weighted_entry if side == "LONG"
               else (mark_price-weighted_entry)/weighted_entry)


def normal_action_allowed(pair: ProtectedPair, action: str) -> bool:
    if action not in {"ENTRY", "DCA", "TAKE_PROFIT", "AUTO_REOPEN"}: return True
    return pair.status not in BLOCKED_PAIR_STATES


def plan_protection(*, pair: ProtectedPair, original_notional: float,
                    weighted_entry: float, mark_price: float,
                    first_threshold: float, first_ratio: float,
                    full_threshold: float, full_ratio: float,
                    hedge_mode: bool, ownership_reliable: bool,
                    exchange_reliable: bool, orders_known: bool,
                    contract_known: bool, margin_sufficient: bool,
                    intent_id: str) -> Intent | None:
    if pair.status not in {"FREE", "PARTIAL_PROTECTION"}: return None
    if not all((hedge_mode, ownership_reliable, exchange_reliable, orders_known,
                contract_known, margin_sufficient)):
        return None
    _finite_positive(original_notional, "Werkelijk gevulde oorspronkelijke notional")
    move = adverse_move(pair.original_side, weighted_entry, mark_price)
    ratio = full_ratio if move >= full_threshold else first_ratio if move >= first_threshold else 0.0
    if ratio == 0: return None
    if not 0 < first_threshold < full_threshold or not 0 < first_ratio <= full_ratio <= 1:
        raise ValueError("Ongeldige Money Grabber-beschermingsconfiguratie")
    target = original_notional * ratio
    missing = max(0.0, target - pair.protection_notional)
    if missing <= 1e-9: return None
    if not intent_id: raise ValueError("Protection-intentie mist een unieke ID")
    return Intent(intent_id, "PAIR_PROTECTION_RISK_REDUCING", pair.account_id,
                  pair.round_id, pair.symbol, pair.protection_side, missing, False,
                  f"{ratio:.0%} tegenbescherming op hetzelfde symbool")


def apply_protection_fill(pair: ProtectedPair, intent: Intent, *, fill_notional: float,
                          original_notional: float, full_ratio: float) -> ProtectedPair:
    if intent.kind != "PAIR_PROTECTION_RISK_REDUCING" or intent.account_id != pair.account_id \
            or intent.round_id != pair.round_id or intent.symbol != pair.symbol \
            or intent.side != pair.protection_side:
        raise ValueError("Protection-fill hoort niet bij dit account, deze ronde en dit symbool")
    _finite_positive(fill_notional, "Werkelijke protection-fill")
    total = pair.protection_notional + fill_notional
    maximum = original_notional * full_ratio
    tolerance = max(1e-8, original_notional * 1e-6)
    if total > maximum + tolerance: raise ValueError("Protection-fill overschrijdt de ingestelde ratio")
    residual = max(0.0, original_notional-total)
    status: PairState = "LOCKED" if total >= maximum-tolerance else "PARTIAL_PROTECTION"
    return replace(pair, status=status, original_notional=original_notional,
                   protection_notional=total, residual_notional=residual,
                   intent_id=intent.intent_id)


def plan_pair_close(*, pair: ProtectedPair, original_pnl: float, protection_pnl: float,
                    funding: float, paid_fees: float, expected_exit_fees: float,
                    slippage_buffer: float, other_costs: float, minimum_buffer: float,
                    reliable: bool, intent_id: str) -> Intent | None:
    if pair.status not in {"PARTIAL_PROTECTION", "LOCKED"} or not reliable: return None
    net = original_pnl + protection_pnl + funding - paid_fees - expected_exit_fees - slippage_buffer - other_costs
    if not all(math.isfinite(x) for x in (net, minimum_buffer)) or net <= max(.01, minimum_buffer): return None
    return Intent(intent_id, "CLOSE_PROTECTED_PAIR", pair.account_id, pair.round_id,
                  pair.symbol, target_notional=pair.original_notional+pair.protection_notional,
                  reduce_only=True, reason=f"Gezamenlijke nettowinst {net:.8f} boven buffer")


def observe_round_target(round_state: Round, evidence: NetValueEvidence, *,
                         close_buffer: float, intent_id: str) -> tuple[Round, Intent | None]:
    if round_state.status != "ACTIVE": return round_state, None
    net = evidence.expected_net_close_value()
    reached = net >= round_state.target_net_value + max(0.0, close_buffer)
    proofs = round_state.consecutive_target_proofs + 1 if reached else 0
    updated = replace(round_state, consecutive_target_proofs=proofs)
    if proofs < 2: return updated, None
    intent = Intent(intent_id, "CLOSE_ALL_ROUND", round_state.account_id,
                    round_state.round_id, reduce_only=True,
                    reason="Netto rondedoel tweemaal fris en betrouwbaar bewezen")
    return replace(updated, status="ROUND_CLOSE_PENDING", close_intent_id=intent_id), intent


def complete_round(round_state: Round, *, positions_zero: bool, orders_zero: bool,
                   final_evidence: NetValueEvidence) -> tuple[Round, float]:
    if round_state.status not in {"ROUND_CLOSE_PENDING", "ROUND_CLOSING"}:
        raise ValueError("Ronde staat niet in afsluiting")
    if not positions_zero or not orders_zero:
        raise ValueError("Een ronde kan niet sluiten terwijl posities of relevante orders bestaan")
    end = final_evidence.expected_net_close_value()
    return replace(round_state, status="CLOSED"), end
