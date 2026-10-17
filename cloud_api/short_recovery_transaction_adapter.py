"""Order-free injected Firestore transaction seam for confirmed SHORT fills.

Requires caller-supplied reference, db and transaction decorator. No global client,
production reference or exchange imports; never invokes the order executor.
"""
from short_recovery_ledger import Ledger, Allocation, Fill
from short_recovery_firestore_mock import encode, decode


def record_confirmed_fill(*, db, transactional, ref, fill: Fill, splits, verified_owner: bool,
                          account: str, symbol: str):
    if not verified_owner or (fill.account, fill.symbol) != (account, symbol):
        return 'BLOCKED_OWNERSHIP'
    transaction = db.transaction()
    @transactional
    def apply(txn):
        snapshot = ref.get(transaction=txn)
        payload = snapshot.to_dict() if snapshot.exists else None
        if not payload or (payload.get('account'), payload.get('symbol')) != (account, symbol):
            return 'BLOCKED_MISSING_LEDGER'
        ledger = decode(payload)
        if fill.execution_id in ledger.seen:
            return 'ALREADY_APPLIED'
        next_ledger = ledger.apply(fill, tuple(splits))
        txn.set(ref, encode(next_ledger))
        return 'APPLIED'
    return apply(transaction)
