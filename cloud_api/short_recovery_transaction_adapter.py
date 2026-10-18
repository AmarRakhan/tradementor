"""Order-free injected Firestore transaction seam for confirmed SHORT fills.

Requires caller-supplied reference, db and transaction decorator. No global client,
production reference or exchange imports; never invokes the order executor.
"""
from short_recovery_ledger import Ledger, Allocation, Fill
from short_recovery_firestore_mock import encode, decode


def record_confirmed_fill(*, db, transactional, ref, fill: Fill, splits, verified_owner: bool,
                          account: str, symbol: str, authorization_mode="LEGACY_MOCK_TEST"):
    if authorization_mode != 'LEGACY_MOCK_TEST':return 'BLOCKED_INDEPENDENT_EXECUTION_AUTHORIZATION'
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


def record_confirmed_fill_owned(*, db, transactional, ledger_ref, ownership_ref,
                                fill: Fill, splits, account: str, symbol: str, cycle_id: str, authorization_mode="LEGACY_MOCK_TEST"):
    """Fail-closed mock seam: reread ownership and inventory in one transaction.

    Not connected to production. Caller must supply true serializable Firestore
    transactions for multi-document read/write atomicity; mock tests are not proof.
    """
    if authorization_mode != 'LEGACY_MOCK_TEST':return 'BLOCKED_INDEPENDENT_EXECUTION_AUTHORIZATION'
    if not account or not symbol or not cycle_id or (fill.account,fill.symbol)!=(account,symbol):
        return 'BLOCKED_SCOPE'
    transaction=db.transaction()
    @transactional
    def apply(txn):
        owner_snapshot=ownership_ref.get(transaction=txn)
        owner=owner_snapshot.to_dict() if owner_snapshot.exists else None
        if not isinstance(owner,dict) or owner.get('account')!=account or owner.get('symbol')!=symbol or owner.get('cycleId')!=cycle_id or owner.get('ownerSide')!='SHORT' or owner.get('cycleConfirmed') is not True or owner.get('ownershipVerified') is not True or owner.get('state') not in ('PARTIAL','FINAL_PENDING'):
            return 'BLOCKED_OWNERSHIP'
        ledger_snapshot=ledger_ref.get(transaction=txn)
        payload=ledger_snapshot.to_dict() if ledger_snapshot.exists else None
        if not payload or (payload.get('account'),payload.get('symbol'))!=(account,symbol):
            return 'BLOCKED_MISSING_LEDGER'
        ledger=decode(payload)
        if fill.execution_id in ledger.seen:return 'ALREADY_APPLIED'
        if any(c != cycle_id for _,c,_ in splits):return 'BLOCKED_CYCLE_MISMATCH'
        updated=ledger.apply(fill,tuple(splits))
        txn.set(ledger_ref,encode(updated))
        return 'APPLIED'
    return apply(transaction)
