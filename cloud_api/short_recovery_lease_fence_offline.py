"""Offline-only transactional fence read over canonical coordination and Recovery docs.
Not an exchange submit authorization: a commit/transport gap still exists.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_reconciler_proof import confirmed_reduction_proof

def check_fence(*, db, transactional, lease_ref, owner_ref, claim_ref, ledger_ref,
                control_ref, account, symbol, cycle, lease_token, now):
    if not isinstance(now,datetime) or not isinstance(lease_token,str) or not lease_token:
        return 'BLOCKED_LEASE_UNAVAILABLE'
    now=now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    @transactional
    def check(tx):
        coordination=lease_ref.get(transaction=tx).to_dict()
        owner=owner_ref.get(transaction=tx).to_dict()
        claim=claim_ref.get(transaction=tx).to_dict()
        ledger=ledger_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        if not isinstance(coordination,dict):return 'BLOCKED_LEASE_UNAVAILABLE'
        lease=coordination.get('lease')
        if not isinstance(lease,dict) or lease.get('token')!=lease_token:return 'BLOCKED_LEASE_STALE'
        until=lease.get('until')
        if not isinstance(until,datetime):return 'BLOCKED_LEASE_EXPIRED'
        until=until.replace(tzinfo=timezone.utc) if until.tzinfo is None else until.astimezone(timezone.utc)
        if until<=now:return 'BLOCKED_LEASE_EXPIRED'
        if not all(isinstance(row,dict) for row in (owner,claim,ledger,control)):
            return 'BLOCKED_RECOVERY_UNKNOWN'
        if control.get('account')!=account or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False:
            return 'BLOCKED_CONTROL'
        if (owner.get('account'),owner.get('symbol'),owner.get('cycleId'))!=(account,symbol,cycle):
            return 'BLOCKED_RECOVERY_UNKNOWN'
        if owner.get('cycleConfirmed') is not True or owner.get('ownershipVerified') is not True:
            return 'BLOCKED_RECOVERY_UNKNOWN'
        if owner.get('ownerSide')!='SHORT' or owner.get('state') not in ('PARTIAL','FINAL_PENDING'):
            return 'BLOCKED_RECOVERY_UNKNOWN'
        if (claim.get('account'),claim.get('symbol'),claim.get('cycle'))!=(account,symbol,cycle):
            return 'BLOCKED_RECOVERY_UNKNOWN'
        if claim.get('side')!='SHORT' or claim.get('action')!='CLOSE':
            return 'BLOCKED_RECOVERY_UNKNOWN'
        if claim.get('state') in ('RESERVED','SUBMITTING','ACKED','UNKNOWN','CANCEL_PENDING'):
            return 'BLOCKED_RECOVERY_UNRESOLVED'
        if claim.get('state') in ('PARTIAL','PARTIAL_TERMINAL'):
            # Known intentional reduction: never refill the SHORT through legacy Auto Hedge.
            return 'BLOCKED_RECOVERY_SHORT_TOPUP'
        return 'BLOCKED_RECOVERY_UNKNOWN'
    try:return check(db.transaction())
    except Exception:return 'BLOCKED_TRANSACTION_UNAVAILABLE'


def reserve_offline_fence(*, db, transactional, lease_ref, owner_ref, claim_ref, ledger_ref, control_ref, account, symbol, cycle, lease_token, intent_id, now):
    """Offline-only serializable reservation; never permits exchange transport."""
    if not isinstance(now, datetime) or not lease_token or not intent_id:
        return 'BLOCKED_FENCE_INPUT'
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    @transactional
    def lock(tx):
        coord = lease_ref.get(transaction=tx).to_dict()
        owner = owner_ref.get(transaction=tx).to_dict()
        claim = claim_ref.get(transaction=tx).to_dict()
        ledger = ledger_ref.get(transaction=tx).to_dict()
        control = control_ref.get(transaction=tx).to_dict()
        if not isinstance(coord, dict): return 'BLOCKED_LEASE_MISSING'
        lease = coord.get('lease')
        if not isinstance(lease, dict) or lease.get('token') != lease_token: return 'BLOCKED_LEASE_STALE'
        until = lease.get('until')
        # Naive lease timestamps do not establish the owner's expiry zone;
        # ambiguous lease evidence must never authorize a topup.
        if not isinstance(until, datetime) or until.tzinfo is None:
            return 'BLOCKED_LEASE_UNVERIFIED'
        until = until.astimezone(timezone.utc)
        if until <= now: return 'BLOCKED_LEASE_EXPIRED'
        if isinstance(coord.get('recoveryFenceReservation'), dict): return 'BLOCKED_FENCE_ALREADY_RESERVED'
        if not all(isinstance(row, dict) for row in (owner, claim, ledger, control)): return 'BLOCKED_MISSING_EVIDENCE'
        if (control.get('account') != account or control.get('enabled') is not True or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False): return 'BLOCKED_STOP'
        if (owner.get('account'), owner.get('symbol'), owner.get('cycleId'), owner.get('ownerSide')) != (account, symbol, cycle, 'SHORT'): return 'BLOCKED_OWNER'
        if owner.get('ownershipVerified') is not True or owner.get('cycleConfirmed') is not True or owner.get('state') not in ('PARTIAL', 'FINAL_PENDING'): return 'BLOCKED_OWNER'
        if (claim.get('account'), claim.get('symbol'), claim.get('cycle')) != (account, symbol, cycle): return 'BLOCKED_CLAIM'
        if claim.get('state') not in ('PARTIAL', 'PARTIAL_TERMINAL'): return 'BLOCKED_UNRESOLVED_RECOVERY'
        if (ledger.get('account'), ledger.get('symbol')) != (account, symbol): return 'BLOCKED_LEDGER'
        # Require the canonical ledger inventory to match this hedge cycle;
        # metadata alone cannot authorize any fencing decision.
        from short_recovery_firestore_mock import decode
        try:
            inventory = decode(ledger)
            remaining = sum((a.remaining for a in inventory.allocations if a.cycle_id == cycle), Decimal(0))
            if not remaining.is_finite() or remaining <= 0: return 'BLOCKED_LEDGER_INVENTORY'
        except (ValueError, TypeError, KeyError, InvalidOperation):
            return 'BLOCKED_LEDGER_INVENTORY'
        if claim.get('side') != 'SHORT' or claim.get('action') != 'CLOSE': return 'BLOCKED_CLAIM'
        try:
            expected = canonical_intent_id(account=account, symbol=symbol, cycle=cycle, side='SHORT', action='CLOSE', step=claim.get('step'))
            qty = Decimal(str(claim.get('executedQty')))
        except (TypeError, ValueError, InvalidOperation): return 'BLOCKED_CLAIM'
        if claim.get('intentId') != expected or not qty.is_finite() or qty <= 0: return 'BLOCKED_CLAIM'
        tx.set(lease_ref, {**coord, 'recoveryFenceReservation': {'account':account,'symbol':symbol,'cycle':cycle,'leaseToken':lease_token,'intentId':intent_id,'reservedAt':now,'state':'OFFLINE_ONLY'}})
        return 'RESERVED_OFFLINE_ONLY'
    try: return lock(db.transaction())
    except Exception: return 'BLOCKED_TRANSACTION_FAILURE'

def reserve_normal_hedge_mock_only(*,mock_only,db,transactional,coordination_ref,
                                   owner_ref,claim_ref,control_ref,account,symbol,
                                   lease_token,intent_id,now):
    """Atomic offline right for a normal hedge ONLY with no Recovery ownership.

    Shares the exact account coordination document and Recovery claim read set.
    A committed right stays reserved after timeout; never permits a live POST.
    """
    if mock_only is not True or not isinstance(now,datetime) or now.tzinfo is None:
        return 'BLOCKED_OFFLINE_SCOPE'
    if not all(isinstance(x,str) and x for x in (account,symbol,lease_token,intent_id)):
        return 'BLOCKED_FENCE_INPUT'
    @transactional
    def acquire(tx):
        coord=coordination_ref.get(transaction=tx).to_dict()
        owner=owner_ref.get(transaction=tx).to_dict()
        claim=claim_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        if not isinstance(coord,dict):return 'BLOCKED_COORDINATION_MISSING'
        if coord.get('recoveryFenceReservation') is not None:return 'BLOCKED_FENCE_ALREADY_RESERVED'
        lease=coord.get('lease')
        if not isinstance(lease,dict) or lease.get('token')!=lease_token:return 'BLOCKED_LEASE_STALE'
        until=lease.get('until')
        if not isinstance(until,datetime) or until.tzinfo is None:return 'BLOCKED_LEASE_UNVERIFIED'
        if until.astimezone(timezone.utc)<=now.astimezone(timezone.utc):return 'BLOCKED_LEASE_EXPIRED'
        if owner is not None or claim is not None:return 'BLOCKED_RECOVERY_OWNERSHIP_UNRESOLVED'
        if (not isinstance(control,dict) or control.get('account')!=account
                or control.get('enabled') is not True or control.get('emergencyStop') is not False
                or control.get('closeAllActive') is not False):return 'BLOCKED_STOP'
        tx.set(coordination_ref,{**coord,'recoveryFenceReservation':{
            'account':account,'symbol':symbol,'intentId':intent_id,
            'leaseToken':lease_token,'state':'NORMAL_HEDGE_MOCK_SUBMITTING',
            'reservedAt':now}})
        return 'RESERVED_NORMAL_HEDGE_MOCK_ONLY'
    try:return acquire(db.transaction())
    except Exception:return 'BLOCKED_TRANSACTION_FAILURE'

def reserve_rehedge_mock_only(*,mock_only,db,transactional,coordination_ref,
                              owner_ref,final_claim_ref,control_ref,account,symbol,
                              old_cycle,new_cycle,lease_token,intent_id,now,
                              final_readback_verified,new_claim_ref=None,allow_quantity_terminal_fence=False):
    """Separate offline rehedge right, requiring final verified close evidence.

    Never auto-releases any old fence and never issues exchange transport.
    A new cycle requires an explicit cleared coordination record.
    """
    if mock_only is not True or final_readback_verified is not True:
        return 'BLOCKED_REHEDGE_FINAL_READBACK'
    if not isinstance(now,datetime) or now.tzinfo is None or not all(
            isinstance(x,str) and x for x in (account,symbol,old_cycle,new_cycle,lease_token,intent_id)):
        return 'BLOCKED_REHEDGE_SCOPE'
    if old_cycle==new_cycle:return 'BLOCKED_REHEDGE_CYCLE_REUSE'
    @transactional
    def acquire(tx):
        coord=coordination_ref.get(transaction=tx).to_dict()
        owner=owner_ref.get(transaction=tx).to_dict()
        final_claim=final_claim_ref.get(transaction=tx).to_dict()
        control=control_ref.get(transaction=tx).to_dict()
        next_claim=new_claim_ref.get(transaction=tx).to_dict() if new_claim_ref is not None else None
        if new_claim_ref is not None and next_claim is not None:return 'BLOCKED_REHEDGE_NEW_CLAIM_EXISTS'
        if not isinstance(coord,dict):return 'BLOCKED_COORDINATION_MISSING'
        old_fence=coord.get('recoveryFenceReservation')
        if isinstance(old_fence,dict):
            if not (allow_quantity_terminal_fence is True and
                    (old_fence.get('account'),old_fence.get('symbol'),
                     old_fence.get('cycle'),old_fence.get('intentId'),
                     old_fence.get('state'))==
                    (account,symbol,old_cycle,final_claim.get('intentId') if isinstance(final_claim,dict) else None,
                     'RECOVERY_SUBMITTING_RECONCILE_ONLY') and
                    isinstance(final_claim,dict) and
                    final_claim.get('quantityTerminalOnly') is True and
                    final_claim.get('terminalVerified') is True and
                    final_claim.get('financialVerified') is False and
                    final_claim.get('financialSettlement')=='UNRECONCILED'):
                return 'BLOCKED_FENCE_ALREADY_RESERVED'
        elif old_fence is not None:
            return 'BLOCKED_FENCE_UNVERIFIED'

        lease=coord.get('lease')
        if not isinstance(lease,dict) or lease.get('token')!=lease_token:return 'BLOCKED_LEASE_STALE'
        until=lease.get('until')
        if not isinstance(until,datetime) or until.tzinfo is None:return 'BLOCKED_LEASE_UNVERIFIED'
        if until.astimezone(timezone.utc)<=now.astimezone(timezone.utc):return 'BLOCKED_LEASE_EXPIRED'
        if (not isinstance(control,dict) or control.get('account')!=account
            or control.get('enabled') is not True or control.get('emergencyStop') is not False
            or control.get('closeAllActive') is not False):return 'BLOCKED_STOP'
        if (not isinstance(owner,dict) or owner.get('account')!=account
            or owner.get('symbol')!=symbol or owner.get('cycleId')!=old_cycle
            or owner.get('ownerSide')!='SHORT' or owner.get('ownershipVerified') is not True
            or owner.get('cycleConfirmed') is not True):return 'BLOCKED_REHEDGE_OWNER'
        if (not isinstance(final_claim,dict) or
            (final_claim.get('account'),final_claim.get('symbol'),final_claim.get('cycle'),
             final_claim.get('side'),final_claim.get('action'),final_claim.get('state'))
            !=(account,symbol,old_cycle,'SHORT','CLOSE','CLOSED') or
            not final_claim.get('orderId') or not final_claim.get('intentId')):
            return 'BLOCKED_REHEDGE_FINAL_CLAIM'
        try:
            expected_close=canonical_intent_id(account=account,symbol=symbol,
                cycle=old_cycle,side='SHORT',action='CLOSE',step=final_claim.get('step'))
            expected_open=canonical_intent_id(account=account,symbol=symbol,
                cycle=new_cycle,side='SHORT',action='OPEN',step=0)
        except ValueError:return 'BLOCKED_REHEDGE_CANONICAL_ID'
        if final_claim['intentId']!=expected_close or intent_id!=expected_open:
            return 'BLOCKED_REHEDGE_CANONICAL_ID'
        if new_claim_ref is not None:
            tx.set(new_claim_ref,{'account':account,'symbol':symbol,'cycle':new_cycle,
                'previousCycle':old_cycle,'intentId':intent_id,'side':'SHORT',
                'action':'OPEN','step':0,'state':'RESERVED'})
        tx.set(coordination_ref,{**coord,'recoveryFenceReservation':{
            'account':account,'symbol':symbol,'cycle':new_cycle,'previousCycle':old_cycle,
            'intentId':intent_id,'leaseToken':lease_token,
            'state':'REHEDGE_MOCK_SUBMITTING','reservedAt':now}})
        return 'RESERVED_REHEDGE_MOCK_ONLY'
    try:return acquire(db.transaction())
    except Exception:return 'BLOCKED_TRANSACTION_FAILURE'


def reserve_verified_rehedge_mock_only(*,mock_only,db,transactional,coordination_ref,owner_ref,final_claim_ref,control_ref,account,symbol,old_cycle,new_cycle,lease_token,intent_id,now,client,long_qty,now_ms,new_claim_ref=None,allow_quantity_terminal_fence=False):
    """Do not accept a caller-supplied finality boolean; re-verify the canonical
    CLOSED claim and mock exchange financial/inventory evidence before reserving.
    The transaction rechecks the final claim but this is not live authorization.
    """
    if mock_only is not True or getattr(client,'offline_mock_only',False) is not True:
        return 'BLOCKED_REHEDGE_MOCK_REQUIRED'
    from short_recovery_rehedge_readback_offline import verify
    if not verify(db=db,transactional=transactional,claim_ref=final_claim_ref,
                  client=client,account=account,symbol=symbol,cycle=old_cycle,
                  long_qty=long_qty,now_ms=now_ms):
        return 'BLOCKED_REHEDGE_FINAL_READBACK'
    return reserve_rehedge_mock_only(mock_only=True,db=db,transactional=transactional,
        coordination_ref=coordination_ref,owner_ref=owner_ref,final_claim_ref=final_claim_ref,
        control_ref=control_ref,account=account,symbol=symbol,old_cycle=old_cycle,
        new_cycle=new_cycle,lease_token=lease_token,intent_id=intent_id,now=now,
        final_readback_verified=True,new_claim_ref=new_claim_ref,
        allow_quantity_terminal_fence=allow_quantity_terminal_fence)
