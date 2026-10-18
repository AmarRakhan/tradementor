"""Mock-only bridge from canonical transaction reservation to reconciler fence.
Never returns True for live transport. Its purpose is to test a denied top-up.
"""
from short_recovery_lease_fence_offline import reserve_offline_fence

def make_denial_fence(*, mock_only, db, transactional, refs, account, symbol, cycle, lease_token, now):
    if mock_only is not True:
        raise ValueError('OFFLINE_BRIDGE_REQUIRED')
    def fence(candidate_symbol, operation, intent_id):
        if candidate_symbol != symbol or operation != 'OPEN':
            return False
        # Record the result for inspection; this is never submit authorization.
        result = reserve_offline_fence(db=db, transactional=transactional,
            lease_ref=refs['lease'],owner_ref=refs['owner'],claim_ref=refs['claim'],
            ledger_ref=refs['ledger'],control_ref=refs['control'],account=account,
            symbol=symbol,cycle=cycle,lease_token=lease_token,intent_id=intent_id,now=now)
        # A denied/uncertain reservation cannot become a submission right.
        fence.last_result = result
        return False
    fence.last_result = 'NOT_RUN'
    return fence

def make_normal_hedge_mock_fence(*,mock_only,db,transactional,refs,account,symbol,lease_token,now):
    """Callback for the existing reconciler, with *mock-only* transport."""
    if mock_only is not True:raise ValueError('OFFLINE_BRIDGE_REQUIRED')
    from short_recovery_lease_fence_offline import reserve_normal_hedge_mock_only
    def fence(candidate_symbol,operation,intent_id):
        if candidate_symbol!=symbol or operation!='OPEN':
            fence.last_result='BLOCKED_INTENT_SCOPE';return False
        result=reserve_normal_hedge_mock_only(mock_only=True,db=db,transactional=transactional,
            coordination_ref=refs['lease'],owner_ref=refs['owner'],claim_ref=refs['claim'],
            control_ref=refs['control'],account=account,symbol=symbol,
            lease_token=lease_token,intent_id=intent_id,now=now)
        fence.last_result=result
        return result=='RESERVED_NORMAL_HEDGE_MOCK_ONLY'
    fence.last_result='NOT_RUN'
    return fence
