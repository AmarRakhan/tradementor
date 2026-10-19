"""Offline CAS activation of a new SHORT hedge cycle after independently verified fills.

Uses the existing canonical rehedge claim and shared account fence. No network
client is created, no orders are placed, and no financial settlement is asserted.
"""
from decimal import Decimal, InvalidOperation
from short_recovery_standalone_offline import RECOVERY
from short_recovery_order_claim_shadow import canonical_intent_id


def activate_verified_rehedge_offline(*, db, transactional, client,
        selector_ref, position_ref, open_claim_ref, coordination_ref, control_ref,
        account, symbol, old_cycle, new_cycle, steps, step_pct):
    if getattr(client, 'offline_mock_only', False) is not True or old_cycle == new_cycle:
        return 'BLOCKED_OFFLINE_OR_CYCLE'
    try:
        intent=canonical_intent_id(account=account,symbol=symbol,cycle=new_cycle,
                                  side='SHORT',action='OPEN',step=0)
        if type(steps) is not int or steps<1 or steps>100:
            return 'BLOCKED_STEPS'
        pct=Decimal(str(step_pct))
        if not pct.is_finite() or pct<=0:
            return 'BLOCKED_STEP_PCT'
        claim=open_claim_ref.get(transaction=db.transaction()).to_dict()
        if not isinstance(claim,dict) or (claim.get('account'),claim.get('symbol'),
            claim.get('cycle'),claim.get('intentId'),claim.get('side'),
            claim.get('action'),claim.get('step'),claim.get('state'))!=(
                account,symbol,new_cycle,intent,'SHORT','OPEN',0,'SUBMITTING'):
            return 'BLOCKED_OPEN_CLAIM'
        order_id=str(claim.get('orderId') or '')
        if not order_id:
            return 'BLOCKED_OPEN_ORDER_ID'
        def read():
            order=client.query_order(symbol,intent)
            fills=client.user_trades(symbol,limit=500)
            acct=client.account_information()
            positions=client.position_risk(symbol)
            orders=client.open_orders(symbol)
            if (not isinstance(order,dict) or order.get('clientOrderId')!=intent
                or order.get('symbol')!=symbol or str(order.get('orderId'))!=order_id
                or order.get('status')!='FILLED' or not isinstance(fills,list)
                or not fills or len(fills)>=500 or not isinstance(acct,dict)
                or acct.get('account')!=account or acct.get('hedgeMode') is not True
                or not isinstance(positions,list) or orders!=[]):
                return None
            # If the exchange exposes side fields, contradictory direction
            # evidence must never activate a new SHORT hedge.
            if order.get('side') not in (None,'SELL') or order.get('positionSide') not in (None,'SHORT'):
                return None
            if any(isinstance(fill,dict) and (
                    fill.get('side') not in (None,'SELL') or
                    fill.get('positionSide') not in (None,'SHORT'))
                   for fill in fills):
                return None
            sides={}
            for p in positions:
                if not isinstance(p,dict) or p.get('symbol')!=symbol:continue
                side=p.get('positionSide')
                if side not in ('LONG','SHORT') or side in sides:return None
                sides[side]=Decimal(str(p['positionAmt']))
            if set(sides)!=set(('LONG','SHORT')):return None
            if sides['LONG']<=0 or sides['LONG']!=sides['SHORT']:return None
            seen=set();qty=Decimal(0);cost=Decimal(0)
            for fill in fills:
                if not isinstance(fill,dict) or str(fill.get('orderId'))!=order_id or fill.get('symbol')!=symbol:
                    return None
                fid=str(fill.get('id') or '')
                q=Decimal(str(fill['qty']));price=Decimal(str(fill['price']))
                if not fid or fid in seen or not all(v.is_finite() and v>0 for v in (q,price)):
                    return None
                seen.add(fid);qty+=q;cost+=q*price
            executed=Decimal(str(order['executedQty']))
            if not executed.is_finite() or qty!=executed or qty!=sides['SHORT']:
                return None
            return (str(qty),str(cost/qty),tuple(sorted(seen)))
        first=read();second=read()
        if first is None or second!=first:
            return 'BLOCKED_INDEPENDENT_REHEDGE_FILL'
    except (TypeError,ValueError,KeyError,InvalidOperation,ArithmeticError,AttributeError):
        return 'BLOCKED_INDEPENDENT_REHEDGE_FILL'
    @transactional
    def activate(tx):
        selector=selector_ref.get(transaction=tx).to_dict()
        position=position_ref.get(transaction=tx).to_dict()
        current=open_claim_ref.get(transaction=tx).to_dict()
        coord=coordination_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        if (not isinstance(selector,dict) or
            (selector.get('account'),selector.get('activeStrategy'),selector.get('offlineOnly'))
            !=(account,RECOVERY,True)):
            return 'BLOCKED_STRATEGY'
        if (not isinstance(control,dict) or control.get('account')!=account
            or control.get('enabled') is not True
            or control.get('emergencyStop') is not False
            or control.get('closeAllActive') is not False):
            return 'BLOCKED_STOP'
        if (not isinstance(position,dict) or
            (position.get('account'),position.get('symbol'),position.get('cycle'),
             position.get('state'),position.get('offlineOnly'))
            !=(account,symbol,old_cycle,'FINAL_SHORT_FILLED_OFFLINE',True)
            or position.get('financialSettlement')!='UNRECONCILED'):
            return 'BLOCKED_PRIOR_CYCLE'
        if current!=claim:
            return 'BLOCKED_CLAIM_CHANGED'
        fence=coord.get('recoveryFenceReservation') if isinstance(coord,dict) else None
        if (not isinstance(fence,dict) or
            (fence.get('account'),fence.get('symbol'),fence.get('cycle'),
             fence.get('previousCycle'),fence.get('intentId'),fence.get('state'))!=
            (account,symbol,new_cycle,old_cycle,intent,'REHEDGE_SUBMITTING_RECONCILE_ONLY')):
            return 'BLOCKED_REHEDGE_FENCE'
        tx.set(open_claim_ref,{**current,'state':'FILLED_QUANTITY_OFFLINE',
            'executedQty':first[0],'verifiedFillIds':list(first[2]),
            'anchorPrice':first[1],'financialSettlement':'UNRECONCILED'})
        tx.set(position_ref,{**position,'cycle':new_cycle,'state':'RECOVERY_ACTIVE_OFFLINE',
            'originalShortQty':first[0],'longQty':first[0],'anchor':first[1],
            'steps':steps,'stepPct':str(pct),'confirmedClosed':'0',
            'pending':False,'financialSettlement':'UNRECONCILED'})
        # Fence stays locked pending canonical reconciliation; no second order right.
        return 'NEW_CYCLE_FILL_VERIFIED_FENCE_LOCKED'
    try:
        return activate(db.transaction())
    except Exception:
        return 'BLOCKED_TRANSACTION'
