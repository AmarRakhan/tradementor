"""Fail-closed shadow classification for Recovery-suspect pairs; no live use."""
from short_recovery_gate import normalize_settings

def classify(*, settings, protected_sides, existing_skip_symbols, suspect_symbols, ownership_rows, account_id):
    if not account_id: raise ValueError('account scope required')
    config=normalize_settings(settings)
    legacy=set(existing_skip_symbols)
    skip=set(legacy)
    statuses={}
    if not config['enabled']:
        return {'status':'OFF','shadow_skip':skip,'pairs':statuses,'orders':0}
    for symbol in set(suspect_symbols):
        row=ownership_rows.get(symbol)
        if protected_sides.get(symbol)!='LONG':
            statuses[symbol]='BLOCKED_NO_LONG_OWNER'
        elif not isinstance(row,dict):
            statuses[symbol]='BLOCKED_MISSING_OWNERSHIP'
        elif row.get('account')!=account_id or row.get('symbol')!=symbol:
            statuses[symbol]='BLOCKED_SCOPE_MISMATCH'
        elif row.get('ownerSide')!='SHORT' or row.get('cycleConfirmed') is not True or row.get('ownershipVerified') is not True or row.get('state') not in {'PARTIAL','FINAL_PENDING'}:
            statuses[symbol]='BLOCKED_UNCERTAIN_OWNERSHIP'
        else:
            statuses[symbol]='SHADOW_VERIFIED_PARTIAL'
        # A suspected Recovery pair is NEVER given to legacy 1:1 topup in shadow,
        # even if its ownership is missing/revoked: require human/authoritative reconciliation.
        skip.add(symbol)
    return {'status':'SHADOW_ONLY','shadow_skip':skip,'pairs':statuses,'orders':0}
