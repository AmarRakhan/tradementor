"""Read-only, fail-closed evidence gate for an eventual canonical reconciler handoff.

This is NOT a live authorization or a new order route. A read-only Firestore
transaction cannot lock a subsequent exchange submit; consumers must still
revalidate claims under existing account coordination immediately pre-order.
"""
from decimal import Decimal, InvalidOperation
from short_recovery_firestore_mock import decode


def confirmed_reduction_proof(*, db, transactional, owner_ref, claim_ref,
                              ledger_ref, control_ref, account, symbol, cycle):
    if not all(isinstance(x, str) and x for x in (account, symbol, cycle)):
        return False

    @transactional
    def evaluate(tx):
        owner = owner_ref.get(transaction=tx).to_dict()
        claim = claim_ref.get(transaction=tx).to_dict()
        ledger_doc = ledger_ref.get(transaction=tx).to_dict()
        control = control_ref.get(transaction=tx).to_dict()
        if not all(isinstance(row, dict) for row in (owner, claim, ledger_doc, control)):
            return False
        if (owner.get('account'), owner.get('symbol'), owner.get('cycleId')) != (account, symbol, cycle):
            return False
        if (owner.get('ownerSide'), owner.get('ownershipVerified'), owner.get('cycleConfirmed')) != ('SHORT', True, True):
            return False
        if owner.get('state') not in ('PARTIAL', 'FINAL_PENDING'):
            return False
        if (claim.get('account'), claim.get('symbol'), claim.get('cycle')) != (account, symbol, cycle):
            return False
        if claim.get('side') != 'SHORT' or claim.get('action') != 'CLOSE' or claim.get('state') not in ('PARTIAL', 'PARTIAL_TERMINAL'):
            return False
        from short_recovery_order_claim_shadow import canonical_intent_id
        try:
            expected = canonical_intent_id(account=account, symbol=symbol, cycle=cycle,
                                           side='SHORT', action='CLOSE', step=claim.get('step'))
        except ValueError:
            return False
        if claim.get('intentId') != expected:
            return False
        if (control.get('account') != account or control.get('enabled') is not True
                or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False):
            return False
        if (ledger_doc.get('account'), ledger_doc.get('symbol')) != (account, symbol):
            return False
        try:
            ledger = decode(ledger_doc)
            remaining = sum((a.remaining for a in ledger.allocations if a.cycle_id == cycle), Decimal(0))
            confirmed = Decimal(str(claim.get('executedQty')))
            return confirmed.is_finite() and confirmed > 0 and remaining > 0
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return False
    try:
        return evaluate(db.transaction()) is True
    except Exception:
        return False
