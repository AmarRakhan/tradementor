"""OFFLINE terminal SHORT quantity completion using existing claim and fence.

Financial PnL/fees/funding remain UNSETTLED. This is neither a TP settlement
nor permission to submit a new order. Existing separate rehedge reservation
still requires a verified new-cycle lease, owner and independent order readback.
"""
from decimal import Decimal,InvalidOperation
from short_recovery_standalone_offline import RECOVERY
from short_recovery_standalone_execution_evidence_offline import inspect_terminal_short_close_offline


def finalize_short_quantity_cycle_offline(*,mock_only,db,transactional,client,
        selector_ref,position_ref,claim_ref,coordination_ref,control_ref,
        account,symbol,cycle,step,long_qty):
    if mock_only is not True or getattr(client,'offline_mock_only',False) is not True:
        return 'BLOCKED_OFFLINE_ONLY'
    old=claim_ref.get(transaction=db.transaction()).to_dict()
    position=position_ref.get(transaction=db.transaction()).to_dict()
    try:
        if not isinstance(position,dict) or type(step) is not int or step!=position['steps']:
            return 'BLOCKED_FINAL_STEP'
        original=Decimal(str(position['originalShortQty']))
        closed=Decimal(str(position['confirmedClosed']))
        long=Decimal(str(long_qty))
        qty=Decimal(str(old['offlineTerminalQty']))
        if (not all(v.is_finite() for v in (original,closed,long,qty)) or
            original<=0 or closed!=original or long<=0 or qty<=0):
            return 'BLOCKED_FINAL_QUANTITY'
    except (KeyError,TypeError,ValueError,InvalidOperation):
        return 'BLOCKED_FINAL_QUANTITY'
    evidence=inspect_terminal_short_close_offline(client=client,account=account,
        symbol=symbol,cycle=cycle,step=step,claim=old,expected_quantity=qty)
    if evidence.get('status')!='ORDER_EXECUTION_VERIFIED_UNSETTLED':
        return evidence.get('status','BLOCKED_ORDER_READBACK')
    try:
        def inventory():
            acct=client.account_information()
            orders=client.open_orders(symbol)
            positions=client.position_risk(symbol)
            if (not isinstance(acct,dict) or acct.get('account')!=account or
                acct.get('hedgeMode') is not True or orders!=[] or
                not isinstance(positions,list)):return None
            sides={}
            for p in positions:
                if not isinstance(p,dict) or p.get('symbol')!=symbol:continue
                side=p.get('positionSide')
                if side not in ('LONG','SHORT') or side in sides:return None
                sides[side]=Decimal(str(p['positionAmt']))
            if set(sides)!=set(('LONG','SHORT')):return None
            if not all(v.is_finite() for v in sides.values()):return None
            return (sides['LONG'],sides['SHORT'])
        before=inventory();after=inventory()
        if before!=(long,Decimal(0)) or after!=before:
            return 'BLOCKED_FINAL_INVENTORY'
    except Exception:
        return 'BLOCKED_FINAL_INVENTORY'

    @transactional
    def complete(tx):
        selector=selector_ref.get(transaction=tx).to_dict()
        pos=position_ref.get(transaction=tx).to_dict()
        claim=claim_ref.get(transaction=tx).to_dict()
        coord=coordination_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        if (not isinstance(selector,dict) or
            (selector.get('account'),selector.get('activeStrategy'),selector.get('offlineOnly'))
            !=(account,RECOVERY,True)):return 'BLOCKED_STRATEGY'
        if (not isinstance(control,dict) or control.get('account')!=account or
            control.get('enabled') is not True or
            control.get('emergencyStop') is not False or
            control.get('closeAllActive') is not False):return 'BLOCKED_STOP'
        if pos!=position or claim!=old:return 'BLOCKED_CONCURRENT_CHANGE'
        if (pos.get('account'),pos.get('symbol'),pos.get('cycle'),
            pos.get('pending'),pos.get('offlineOnly'))!=(account,symbol,cycle,True,True):
            return 'BLOCKED_POSITION'
        if (claim.get('offlineOrderTerminalVerified') is not True or
            claim.get('offlineFundingStatus')!='UNRECONCILED' or
            claim.get('offlineFinancialSettlement')!='PENDING' or
            claim.get('offlineNextClaimAuthorized') is not False or
            tuple(tuple(x) for x in claim.get('offlineTerminalExecutions',[]))
            !=evidence['executionFinancials']):return 'BLOCKED_EXECUTION'
        fence=coord.get('recoveryFenceReservation') if isinstance(coord,dict) else None
        if (not isinstance(fence,dict) or
            (fence.get('account'),fence.get('symbol'),fence.get('cycle'),
             fence.get('intentId'),fence.get('state')) !=
            (account,symbol,cycle,evidence['intentId'],
             'RECOVERY_SUBMITTING_RECONCILE_ONLY') or
            coord.get('lease') is not None):return 'BLOCKED_FENCE'
        tx.set(claim_ref,{**claim,'state':'CLOSED','terminalVerified':True,
            'quantityTerminalOnly':True,'executedQty':str(qty),'financialVerified':False,
            'financialSettlement':'UNRECONCILED',
            'offlineNextClaimAuthorized':False})
        tx.set(position_ref,{**pos,'state':'FINAL_SHORT_FILLED_OFFLINE',
            'pending':False,'financialSettlement':'UNRECONCILED'})
        # Fence is not silently erased; rehedge needs a distinct, audited
        # transition to a new lease and must not be implicitly authorized.
        return 'QUANTITY_CYCLE_TERMINAL_UNSETTLED_FENCE_LOCKED'
    try:return complete(db.transaction())
    except Exception:return 'BLOCKED_TRANSACTION'
