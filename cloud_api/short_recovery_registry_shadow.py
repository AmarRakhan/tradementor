"""Offline, account-scoped durable Recovery marker; no live adapter."""
from short_recovery_multidoc_mock import Conflict
from short_recovery_suspect_discovery import preview

def register(*,db,transactional,marker_ref,ledger_ref,owner_ref,account,symbol,cycle):
    if not all((account,symbol,cycle)):return 'BLOCKED_SCOPE'
    @transactional
    def work(tx):
        marker=marker_ref.get(transaction=tx).to_dict()
        ledger=ledger_ref.get(transaction=tx).to_dict()
        owner=owner_ref.get(transaction=tx).to_dict()
        if not isinstance(ledger,dict) or (ledger.get('account'),ledger.get('symbol'))!=(account,symbol):return 'BLOCKED_LEDGER'
        if not isinstance(owner,dict) or (owner.get('account'),owner.get('symbol'),owner.get('cycleId'))!=(account,symbol,cycle) or owner.get('ownershipVerified') is not True or owner.get('cycleConfirmed') is not True:return 'BLOCKED_OWNER'
        if marker is not None:
            if (marker.get('account'),marker.get('symbol'))!=(account,symbol):return 'BLOCKED_MARKER_SCOPE'
            if marker.get('state')=='SUSPECT':return 'ALREADY_REGISTERED'
            return 'BLOCKED_EXISTING_MARKER'
        tx.set(marker_ref,{'account':account,'symbol':symbol,'cycleId':cycle,'state':'SUSPECT'})
        return 'REGISTERED'
    return work(db.transaction())

def discover_registry(*,account,symbols,read_marker,read_ledger,read_owner,settings,protected_sides,existing_skip_symbols):
    markers={};failed=set()
    for symbol in symbols:
        try:record=read_marker(account,symbol)
        except Exception:failed.add(symbol);continue
        if record is not None:
            markers[symbol]=record
    def ledger(a,s):
        if s in failed:return {'account':a,'symbol':s,'unavailable':True}
        if s in markers:return {'account':a,'symbol':s,'registrySuspect':True}
        return read_ledger(a,s)
    def owner(a,s):
        if s in failed:return None
        if s in markers:return markers[s] if markers[s].get('state')=='SUSPECT' and markers[s].get('account')==a and markers[s].get('symbol')==s else None
        return read_owner(a,s)
    result=preview(account_id=account,symbols=symbols,read_ledger=ledger,read_owner=owner,settings=settings,protected_sides=protected_sides,existing_skip_symbols=existing_skip_symbols)
    result['registryFailures']=failed
    return result
