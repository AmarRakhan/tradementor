"""Offline marker-first permission gate, no executor or production integration."""
from short_recovery_registry_shadow import register
from short_recovery_firestore_mock import decode, encode

def prepare(*, db, transactional, marker_ref, ledger_ref, owner_ref, account, symbol, cycle):
    outcome=register(db=db,transactional=transactional,marker_ref=marker_ref,ledger_ref=ledger_ref,owner_ref=owner_ref,account=account,symbol=symbol,cycle=cycle)
    if outcome not in ('REGISTERED','ALREADY_REGISTERED'):
        return {'status':'BLOCKED_MARKER','reason':outcome,'ordersSent':0}
    @transactional
    def verify(tx):
        marker=marker_ref.get(transaction=tx).to_dict()
        owner=owner_ref.get(transaction=tx).to_dict()
        ledger=ledger_ref.get(transaction=tx).to_dict()
        if not isinstance(marker,dict) or (marker.get('account'),marker.get('symbol'),marker.get('cycleId'),marker.get('state'))!=(account,symbol,cycle,'SUSPECT'):
            return 'BLOCKED_MARKER'
        if not isinstance(owner,dict) or (owner.get('account'),owner.get('symbol'),owner.get('cycleId'))!=(account,symbol,cycle) or owner.get('ownershipVerified') is not True or owner.get('cycleConfirmed') is not True:
            return 'BLOCKED_OWNER'
        if not isinstance(ledger,dict) or (ledger.get('account'),ledger.get('symbol'))!=(account,symbol):
            return 'BLOCKED_LEDGER'
        return 'SHADOW_READY'
    return {'status':verify(db.transaction()),'ordersSent':0}

def book_mock_fill(*,db,transactional,marker_ref,ledger_ref,owner_ref,fill,splits,account,symbol,cycle,authorization_mode="LEGACY_MOCK_TEST"):
    """Validate marker, owner and ledger in one multi-document mock transaction."""
    from short_recovery_mock_storage_boundary import isolated_storage_only
    if authorization_mode != 'LEGACY_MOCK_TEST' or not isolated_storage_only(db):
        return 'BLOCKED_INDEPENDENT_EXECUTION_AUTHORIZATION'
    if (fill.account,fill.symbol)!=(account,symbol):return 'BLOCKED_SCOPE'
    @transactional
    def apply(tx):
        marker=marker_ref.get(transaction=tx).to_dict()
        if not isinstance(marker,dict) or (marker.get('account'),marker.get('symbol'),marker.get('cycleId'),marker.get('state'))!=(account,symbol,cycle,'SUSPECT'):
            return 'BLOCKED_MARKER'
        owner=owner_ref.get(transaction=tx).to_dict()
        if not isinstance(owner,dict) or (owner.get('account'),owner.get('symbol'),owner.get('cycleId'))!=(account,symbol,cycle) or owner.get('ownerSide')!='SHORT' or owner.get('ownershipVerified') is not True or owner.get('cycleConfirmed') is not True or owner.get('state') not in ('PARTIAL','FINAL_PENDING'):
            return 'BLOCKED_OWNERSHIP'
        payload=ledger_ref.get(transaction=tx).to_dict()
        if not isinstance(payload,dict) or (payload.get('account'),payload.get('symbol'))!=(account,symbol):return 'BLOCKED_LEDGER'
        ledger=decode(payload)
        if fill.execution_id in ledger.seen:return 'ALREADY_APPLIED'
        if any(c!=cycle for _,c,_ in splits):return 'BLOCKED_CYCLE'
        tx.set(ledger_ref,encode(ledger.apply(fill,tuple(splits))))
        return 'APPLIED'
    return apply(db.transaction())
