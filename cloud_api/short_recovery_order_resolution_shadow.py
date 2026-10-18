"""Offline confirmed order-resolution seam. Evidence is supplied by a mock, not exchange."""
from decimal import Decimal, InvalidOperation
from short_recovery_firestore_mock import decode, encode
from short_recovery_ledger import Fill

def resolve(*, db, transactional, claim_ref, ledger_ref, marker_ref, owner_ref, account, symbol, cycle, intent_id, event, evidence=None, execution_id=None, quantity=None, authorization_mode="LEGACY_MOCK_TEST"):
    if authorization_mode != 'LEGACY_MOCK_TEST':return 'BLOCKED_INDEPENDENT_EXECUTION_AUTHORIZATION'
    allowed={'UNKNOWN','LATE_ACK','LATE_FILL','CANCEL_REQUESTED','CANCEL_TERMINAL','NO_ORDER_TERMINAL','ACK','FILL'}
    if event not in allowed:return 'BLOCKED_EVENT'
    @transactional
    def step(tx):
        claim=claim_ref.get(transaction=tx).to_dict()
        marker=marker_ref.get(transaction=tx).to_dict()
        owner=owner_ref.get(transaction=tx).to_dict()
        raw=ledger_ref.get(transaction=tx).to_dict()
        if not isinstance(claim,dict) or (claim.get('account'),claim.get('symbol'),claim.get('cycle'),claim.get('intentId'))!=(account,symbol,cycle,intent_id):return 'BLOCKED_CLAIM'
        if not isinstance(marker,dict) or (marker.get('account'),marker.get('symbol'),marker.get('cycleId'),marker.get('state'))!=(account,symbol,cycle,'SUSPECT'):return 'BLOCKED_MARKER'
        if not isinstance(owner,dict) or (owner.get('account'),owner.get('symbol'),owner.get('cycleId'),owner.get('ownershipVerified'))!=(account,symbol,cycle,True) or owner.get('ownerSide')!='SHORT' or owner.get('cycleConfirmed') is not True or owner.get('state') not in ('PARTIAL','FINAL_PENDING'):return 'BLOCKED_OWNER'
        if not isinstance(raw,dict) or (raw.get('account'),raw.get('symbol'))!=(account,symbol):return 'BLOCKED_LEDGER'
        state=claim.get('state','RESERVED'); ledger=decode(raw)
        if event=='UNKNOWN':
            if state in ('CANCELLED','NO_ORDER','CLOSED','PARTIAL_TERMINAL'):return 'ALREADY_TERMINAL'
            tx.set(claim_ref,{**claim,'state':'UNKNOWN'});return 'BLOCKED_UNKNOWN'
        if event=='CANCEL_REQUESTED':
            if state in ('CANCELLED','NO_ORDER','CLOSED','PARTIAL_TERMINAL'):return 'ALREADY_TERMINAL'
            tx.set(claim_ref,{**claim,'state':'CANCEL_PENDING'});return 'WAIT_TERMINAL'
        if event=='ACK':
            if state in ('UNKNOWN','CANCEL_PENDING','CANCELLED','NO_ORDER','CLOSED','PARTIAL_TERMINAL'):return 'BLOCKED_UNKNOWN'
            if not isinstance(evidence,dict) or evidence.get('confirmed') is not True or not evidence.get('orderId'):return 'BLOCKED_NO_EVIDENCE'
            tx.set(claim_ref,{**claim,'state':'ACKED','orderId':evidence['orderId']});return 'ACKED'
        if event=='LATE_ACK':
            if not isinstance(evidence,dict) or evidence.get('confirmed') is not True or not evidence.get('orderId'):return 'BLOCKED_NO_EVIDENCE'
            if state in ('CANCELLED','NO_ORDER','CLOSED','PARTIAL_TERMINAL'):return 'BLOCKED_TERMINAL_CONFLICT'
            # A delayed readback cannot replace the bound exchange order while an earlier side is unresolved.
            if claim.get('orderId') and str(claim['orderId'])!=str(evidence['orderId']):return 'BLOCKED_ORDER_MISMATCH'
            tx.set(claim_ref,{**claim,'state':'ACKED','orderId':evidence['orderId']});return 'ACKED_RECOVERED'
        if event=='FILL' and state in ('CLOSED','CANCELLED','NO_ORDER','PARTIAL_TERMINAL'):return 'ALREADY_TERMINAL'
        if event=='FILL' and state not in ('ACKED','PARTIAL'):return 'BLOCKED_UNCONFIRMED'
        if event in ('LATE_FILL','FILL'):
            if not isinstance(evidence,dict) or evidence.get('confirmed') is not True or not evidence.get('orderId') or not execution_id or quantity is None:return 'BLOCKED_NO_EVIDENCE'
            if state in ('CANCELLED','NO_ORDER','CLOSED','PARTIAL_TERMINAL'):return 'BLOCKED_TERMINAL_CONFLICT'
            if claim.get('orderId') and claim['orderId']!=evidence['orderId']:return 'BLOCKED_ORDER_MISMATCH'
            if execution_id in ledger.seen:return 'ALREADY_APPLIED'
            # A legacy claim with booked fills but no cumulative amount cannot
            # safely infer the next total from zero. Require readback recovery.
            if state=='PARTIAL' and claim.get('executedQty') is None:
                return 'BLOCKED_LEGACY_EXECUTED_QTY_UNVERIFIED'
            # Exchange-confirmed fill economics must be explicit and tied to this
            # execution; absence is never implicitly treated as a zero cost.
            if evidence.get('readbackVerified') is not True or str(evidence.get('executionId')) != str(execution_id) or str(evidence.get('orderId')) != str(claim.get('orderId', evidence['orderId'])):
                return 'BLOCKED_FINANCIAL_EVIDENCE'
            try:
                if str(evidence.get('quantity')) != str(quantity):
                    return 'BLOCKED_FINANCIAL_EVIDENCE'
                pnl=Decimal(str(evidence['realizedPnl']))
                fee=Decimal(str(evidence['commission']))
                funding=Decimal(str(evidence['funding']))
                q=Decimal(str(quantity))
            except (KeyError, TypeError, ValueError, InvalidOperation):
                return 'BLOCKED_FINANCIAL_EVIDENCE'
            if any(not value.is_finite() for value in (pnl,fee,funding,q)) or fee<0:
                return 'BLOCKED_FINANCIAL_EVIDENCE'
            allocation=ledger.allocations[0]
            if not q.is_finite() or q<=0 or q>allocation.remaining or allocation.cycle_id!=cycle:return 'BLOCKED_QUANTITY'
            updated=ledger.apply(Fill(account,symbol,execution_id,evidence['orderId'],q,pnl,fee,funding),((allocation.zone_id,cycle,q),))
            tx.set(ledger_ref,encode(updated))
            tx.set(claim_ref,{**claim,'state':'CLOSED' if updated.allocations[0].remaining==0 else 'PARTIAL','orderId':evidence['orderId'],'executedQty':str(Decimal(str(claim.get('executedQty','0')))+q)})
            return 'FILL_APPLIED'
        if event in ('CANCEL_TERMINAL','NO_ORDER_TERMINAL'):
            if not isinstance(evidence,dict) or evidence.get('confirmed') is not True or evidence.get('noMoreFills') is not True or evidence.get('intentId')!=intent_id:
                return 'BLOCKED_NOT_TERMINAL'
            if state in ('CANCELLED','NO_ORDER','CLOSED','PARTIAL_TERMINAL'):return 'ALREADY_TERMINAL'
            if event=='NO_ORDER_TERMINAL' and (state not in ('RESERVED','UNKNOWN') or ledger.seen):return 'BLOCKED_NO_ORDER_CONFLICT'
            # A bound Aster order ID is evidence of an order, never proof of no order.
            if event=='NO_ORDER_TERMINAL' and claim.get('orderId'):return 'BLOCKED_KNOWN_ORDER_EXISTS'
            if event=='CANCEL_TERMINAL' and (state=='PARTIAL' or ledger.seen):
                # Partial executions must not be finalized by an unrelated order's terminal readback.
                if evidence.get('terminalReadbackVerified') is not True or not claim.get('orderId') or str(evidence.get('orderId'))!=str(claim['orderId']):
                    return 'BLOCKED_PARTIAL_TERMINAL_ORDER_PROOF'
                if evidence.get('orderStatus') not in ('CANCELED','EXPIRED'):
                    return 'BLOCKED_PARTIAL_NOT_CANCELLED'
                tx.set(claim_ref,{**claim,'state':'PARTIAL_TERMINAL'})
                return 'PARTIAL_TERMINAL_RECONCILE_REQUIRED'
            tx.set(claim_ref,{**claim,'state':'CANCELLED' if event=='CANCEL_TERMINAL' else 'NO_ORDER'})
            return 'TERMINAL_VERIFIED'
    return step(db.transaction())

def reconcile_pair_close(*, db, transactional, claim_refs, ledger_refs, control_ref,
                         account, symbol, cycle, readbacks, pair_ref, authorization_mode="LEGACY_MOCK_TEST"):
    """Offline atomic two-sided readback settlement; never submits replacement orders.

    Side-scoped claim and ledger refs are persisted independently. The pair row
    is a derived terminal gate, not a new runtime or order dispatcher.
    Readbacks are injected exchange-shaped evidence, not trusted by default.
    """
    if authorization_mode != 'LEGACY_MOCK_TEST':return 'BLOCKED_INDEPENDENT_EXECUTION_AUTHORIZATION'
    from short_recovery_ledger import d as finite, Fill
    sides=('LONG','SHORT')
    if set(claim_refs)!=set(sides) or set(ledger_refs)!=set(sides) or set(readbacks)!=set(sides):
        return 'BLOCKED_PAIR_SCOPE'
    @transactional
    def settle(tx):
        control=control_ref.get(transaction=tx).to_dict()
        pair=pair_ref.get(transaction=tx).to_dict()
        claims={side:claim_refs[side].get(transaction=tx).to_dict() for side in sides}
        raws={side:ledger_refs[side].get(transaction=tx).to_dict() for side in sides}
        if not isinstance(control,dict) or control.get('account')!=account or not isinstance(pair,dict) or (pair.get('account'),pair.get('symbol'),pair.get('cycle'))!=(account,symbol,cycle):
            return 'BLOCKED_PAIR_CONTROL'
        if pair.get('state')=='CLOSED':return 'ALREADY_PAIR_CLOSED'
        for side in sides:
            claim=claims[side];raw=raws[side]
            if not isinstance(claim,dict) or (claim.get('account'),claim.get('symbol'),claim.get('cycle'),claim.get('positionSide'))!=(account,symbol,cycle,side) or not claim.get('intentId') or not claim.get('orderId'):
                return 'BLOCKED_SIDE_CLAIM'
            if not isinstance(raw,dict) or (raw.get('account'),raw.get('symbol'))!=(account,symbol):return 'BLOCKED_SIDE_LEDGER'
            if claim.get('state') not in ('ACKED','PARTIAL','UNKNOWN','PARTIAL_TERMINAL','CLOSED'):
                return 'BLOCKED_SIDE_CLAIM'
        updates={};claimed={};trusted={}
        for side in sides:
            row=readbacks[side];claim=claims[side];ledger=decode(raws[side]);new=ledger
            if not isinstance(row,dict) or row.get('readbackVerified') is not True or row.get('positionSide')!=side or str(row.get('orderId'))!=str(claim['orderId']) or row.get('symbol')!=symbol:
                return 'BLOCKED_SIDE_READBACK'
            fills=row.get('fills')
            if not isinstance(fills,list) or row.get('fillsComplete') is not True:
                return 'BLOCKED_INCOMPLETE_FILLS'
            try:
                expected=finite(row['executedQty'])
                if expected<0:return 'BLOCKED_EXECUTED_QTY'
                # A late/stale readback must never regress the persisted
                # executed quantity, even when it omits already-seen fills.
                if claim.get('executedQty') is not None and expected<finite(claim['executedQty']):
                    return 'BLOCKED_EXECUTED_QTY_REGRESSION'
                total=Decimal(0);readback_net=Decimal(0);seen_page=set()
                replay_financials={}
                for fill in fills:
                    if not isinstance(fill,dict) or not fill.get('executionId') or fill['executionId'] in seen_page or str(fill.get('orderId'))!=str(claim['orderId']):return 'BLOCKED_FILL_IDENTITY'
                    seen_page.add(fill['executionId']);qty=finite(fill['quantity']);pnl=finite(fill['realizedPnl']);fee=finite(fill['commission']);funding=finite(fill['funding'])
                    if qty<=0 or fee<0 or fill.get('financialVerified') is not True or fill.get('fundingOwnershipVerified') is not True:return 'BLOCKED_FINANCIAL_EVIDENCE'
                    total+=qty
                    readback_net+=pnl-fee+funding
                    if fill['executionId'] in new.seen:
                        # The ledger stores net only; require persisted separate
                        # execution economics before trusting any replay change.
                        known=claim.get('executionFinancials')
                        if not isinstance(known,dict):return 'BLOCKED_FINANCIAL_REPLAY_PROVENANCE'
                        replay_financials[fill['executionId']]=[str(qty),str(pnl),str(fee),str(funding)]
                        continue
                    replay_financials[fill['executionId']]=[str(qty),str(pnl),str(fee),str(funding)]
                    owned=[a for a in new.allocations if a.cycle_id==cycle and a.remaining>0]
                    if len(owned)!=1:return 'BLOCKED_ALLOCATION'
                    item=owned[0]
                    new=new.apply(Fill(account,symbol,fill['executionId'],str(claim['orderId']),qty,pnl,fee,funding),((item.zone_id,cycle,qty),))
                # A replayed executionId is idempotent, but a modified quantity
                # must not silently replace its previously booked amount.
                booked_qty=sum((q for _,c,q,_ in new.booked if c==cycle),Decimal(0))
                booked_net=sum((net for _,c,_,net in new.booked if c==cycle),Decimal(0))
                if total!=expected or booked_qty!=expected:return 'BLOCKED_EXECUTION_INCOMPLETE'
                if booked_net!=readback_net:return 'BLOCKED_FINANCIAL_REPLAY_MISMATCH'
                known=claim.get('executionFinancials')
                # Every booked execution needs an individually persisted record.
                # Otherwise a legacy claim can silently acquire invented replay
                # provenance on the next partial fill.
                if (known is None and ledger.seen) or (known is not None and (
                        not isinstance(known,dict) or set(known)!=set(ledger.seen)
                        or any(known.get(k)!=v for k,v in replay_financials.items() if k in ledger.seen))):
                    return 'BLOCKED_FINANCIAL_REPLAY_PROVENANCE'
            except (KeyError,TypeError,ValueError,InvalidOperation):return 'BLOCKED_FINANCIAL_EVIDENCE'
            remaining=[a.remaining for a in new.allocations if a.cycle_id==cycle]
            if len(remaining)!=1:return 'BLOCKED_ALLOCATION'
            terminal=row.get('status')=='FILLED' and row.get('terminalVerified') is True and remaining[0]==0 and row.get('incomeHistoryComplete') is True
            updates[side]=new;trusted[side]=terminal
            claimed[side]={**claim,'state':'CLOSED' if terminal else 'UNKNOWN','executedQty':str(expected),'executionFinancials':replay_financials}
        for side in sides:
            if encode(updates[side])!=raws[side]:tx.set(ledger_refs[side],encode(updates[side]))
            if claimed[side]!=claims[side]:tx.set(claim_refs[side],claimed[side])
        # A stop does not erase confirmed fills; it prevents terminal authorization.
        done=all(trusted.values()) and control.get('enabled') is True and control.get('emergencyStop') is False and control.get('closeAllActive') is False and pair.get('fundingCycleVerified') is True
        tx.set(pair_ref,{**pair,'state':'CLOSED' if done else 'RECONCILE_REQUIRED'})
        return 'PAIR_CLOSED_VERIFIED' if done else 'PAIR_RECONCILE_REQUIRED'
    return settle(db.transaction())

def reconcile_pair_from_aster_mock(*, client, claim_refs, ledger_refs, control_ref, pair_ref,
                                   db, transactional, account, symbol, cycle, financial_proof=None,
                                   page_size=500):
    """Inject Aster GETs into canonical atomic settlement only with independent evidence.

    financial_proof is trusted only as an explicitly supplied, complete provenance
    map from the caller's separately verified income/cycle ownership procedure.
    Aster userTrades alone never certifies funding ownership.
    """
    from short_recovery_aster_readback_mock_adapter import inspect
    sides=('LONG','SHORT')
    @transactional
    def read_claims(tx):
        return {s:claim_refs[s].get(transaction=tx).to_dict() for s in sides}
    raw=read_claims(db.transaction())
    if any(not isinstance(raw[s],dict) or (raw[s].get('account'),raw[s].get('symbol'),raw[s].get('cycle'),raw[s].get('positionSide'))!=(account,symbol,cycle,s) or not raw[s].get('intentId') for s in sides):
        return 'BLOCKED_SIDE_CLAIM'
    if not isinstance(financial_proof,dict) or set(financial_proof)!=set(sides):
        return 'BLOCKED_FUNDING_CYCLE_PROOF'
    evidence={}
    for side in sides:
        proof=financial_proof[side]
        if not isinstance(proof,dict) or proof.get('cycleId')!=cycle or proof.get('incomeHistoryComplete') is not True or proof.get('ownershipVerified') is not True:
            return 'BLOCKED_FUNDING_CYCLE_PROOF'
        result=inspect(client,symbol=symbol,client_order_id=raw[side]['intentId'],page_size=page_size)
        if result.get('status')!='READBACK_PREVIEW':return result.get('status','BLOCKED_READBACK')
        if str(proof.get('orderId'))!=str(raw[side].get('orderId')):
            return 'BLOCKED_ORDER_MISMATCH'
        fills=[]
        verified=proof.get('executions')
        if not isinstance(verified,dict):return 'BLOCKED_FUNDING_CYCLE_PROOF'
        for fill in result['fills']:
            owned=verified.get(fill['executionId'])
            if not isinstance(owned,dict) or owned.get('fundingOwnershipVerified') is not True or owned.get('financialVerified') is not True:
                return 'BLOCKED_FUNDING_CYCLE_PROOF'
            try:funding=Decimal(str(owned['funding']))
            except (KeyError,TypeError,InvalidOperation,ValueError):return 'BLOCKED_FUNDING_CYCLE_PROOF'
            if not funding.is_finite():return 'BLOCKED_FUNDING_CYCLE_PROOF'
            fills.append({'orderId':fill['orderId'],'executionId':fill['executionId'],'quantity':str(fill['quantity']),
                          'realizedPnl':str(fill['realizedPnl']),'commission':str(fill['fee']),
                          'funding':str(funding),'financialVerified':True,'fundingOwnershipVerified':True})
        if set(verified)!=set(x['executionId'] for x in fills):return 'BLOCKED_FUNDING_CYCLE_PROOF'
        if proof.get('orderStatus')!=result['orderStatus'] or proof.get('executedQty') is None:
            return 'BLOCKED_TERMINAL_PROOF'
        # A caller's asserted quantity is not exchange proof: reconcile all
        # observed executions against the claimed terminal executed quantity.
        try:
            executed=Decimal(str(proof['executedQty']))
            if not executed.is_finite() or executed<0 or executed!=sum((Decimal(str(x['quantity'])) for x in fills),Decimal(0)):
                return 'BLOCKED_EXECUTION_INCOMPLETE'
        except (InvalidOperation,ValueError,TypeError):return 'BLOCKED_EXECUTION_INCOMPLETE'
        evidence[side]={'symbol':symbol,'positionSide':side,'orderId':raw[side]['orderId'],
                        'readbackVerified':True,'fillsComplete':True,'incomeHistoryComplete':True,
                        'terminalVerified':proof.get('terminalVerified') is True and result['orderStatus']=='FILLED',
                        'status':result['orderStatus'],'executedQty':str(proof['executedQty']),'fills':fills}
    return reconcile_pair_close(db=db,transactional=transactional,claim_refs=claim_refs,ledger_refs=ledger_refs,
                                control_ref=control_ref,pair_ref=pair_ref,account=account,symbol=symbol,cycle=cycle,readbacks=evidence)
