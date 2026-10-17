"""Read-only offline Recovery suspect discovery. Fail closed on incomplete inventory."""
from short_recovery_failclosed_shadow import classify

def discover(*, account_id, symbols, read_ledger, read_owner):
    if not account_id: raise ValueError('account required')
    suspects=set();owners={};errors={}
    for symbol in set(symbols):
        try:
            ledger=read_ledger(account_id,symbol)
            owner=read_owner(account_id,symbol)
        except Exception:
            # The caller cannot prove absence, so suppress only the affected symbol.
            suspects.add(symbol);errors[symbol]='UNAVAILABLE';continue
        if ledger is not None:
            if not isinstance(ledger,dict) or (ledger.get('account'),ledger.get('symbol'))!=(account_id,symbol):
                suspects.add(symbol);errors[symbol]='LEDGER_SCOPE_OR_FORMAT';continue
            suspects.add(symbol)
        if owner is not None:
            suspects.add(symbol)
            if isinstance(owner,dict) and (owner.get('account'),owner.get('symbol'))==(account_id,symbol):owners[symbol]=owner
            else:errors[symbol]='OWNER_SCOPE_OR_FORMAT'
    return {'suspects':suspects,'owners':owners,'errors':errors}

def preview(*,account_id,symbols,read_ledger,read_owner,settings,protected_sides,existing_skip_symbols):
    data=discover(account_id=account_id,symbols=symbols,read_ledger=read_ledger,read_owner=read_owner)
    route=classify(settings=settings,protected_sides=protected_sides,existing_skip_symbols=existing_skip_symbols,
                   suspect_symbols=data['suspects'],ownership_rows=data['owners'],account_id=account_id)
    return {**data,'routing':route}
