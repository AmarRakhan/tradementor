"""Offline atomic recording of confirmed SHORT CLOSE execution quantity.

This supplements existing canonical claims, not a router, order submitter, or
financial settlement. Funding remains unknown. The shared fence stays locked,
so recording a fill never authorizes a second reduction.
"""
from decimal import Decimal, InvalidOperation
from short_recovery_standalone_offline import RECOVERY
from short_recovery_standalone_execution_evidence_offline import (
    inspect_terminal_short_close_offline,
)


def record_confirmed_short_close_offline(*, db, transactional, selector_ref,
        position_ref, claim_ref, coordination_ref, control_ref, client,
        account, symbol, cycle, step, expected_quantity):
    """Repeated exchange readback + atomic same-claim quantity record."""
    claim = claim_ref.get(transaction=db.transaction()).to_dict()
    evidence = inspect_terminal_short_close_offline(
        client=client, account=account, symbol=symbol, cycle=cycle,
        step=step, claim=claim, expected_quantity=expected_quantity)
    if evidence.get('status') != 'ORDER_EXECUTION_VERIFIED_UNSETTLED':
        return evidence.get('status', 'BLOCKED_READBACK')
    try:
        qty = Decimal(evidence['executedQty'])
        records = tuple(evidence['executionFinancials'])
        if not records or qty <= 0 or not qty.is_finite():
            return 'BLOCKED_EXECUTION_EVIDENCE'
    except (TypeError, ValueError, InvalidOperation, KeyError):
        return 'BLOCKED_EXECUTION_EVIDENCE'

    @transactional
    def persist(tx):
        selector = selector_ref.get(transaction=tx).to_dict()
        position = position_ref.get(transaction=tx).to_dict()
        current = claim_ref.get(transaction=tx).to_dict()
        coordination = coordination_ref.get(transaction=tx).to_dict()
        control = control_ref.get(transaction=tx).to_dict()
        if (not isinstance(selector, dict) or
            (selector.get('account'), selector.get('activeStrategy'),
             selector.get('offlineOnly')) != (account, RECOVERY, True)):
            return 'BLOCKED_STRATEGY_NOT_ACTIVE'
        if (not isinstance(control, dict) or control.get('account') != account
                or control.get('enabled') is not True
                or control.get('emergencyStop') is not False
                or control.get('closeAllActive') is not False):
            return 'BLOCKED_STOP'
        if (not isinstance(position, dict) or
            (position.get('account'),position.get('symbol'),position.get('cycle'),
             position.get('offlineOnly')) != (account,symbol,cycle,True) or
            position.get('state') not in ('ADOPTED_OFFLINE','RECOVERY_ACTIVE_OFFLINE')):
            return 'BLOCKED_POSITION_SCOPE'
        if not isinstance(current, dict) or current != claim:
            return 'BLOCKED_CONCURRENT_CLAIM_CHANGE'
        fence = coordination.get('recoveryFenceReservation') if isinstance(coordination,dict) else None
        if (not isinstance(fence, dict) or
            (fence.get('account'),fence.get('symbol'),fence.get('cycle'),
             fence.get('intentId')) !=
            (account,symbol,cycle,evidence['intentId']) or
            fence.get('state') not in ('RECOVERY_SUBMITTING_RECONCILE_ONLY',
                                      'RECOVERY_CLAIM_RESERVED') or
            isinstance(coordination.get('lease'),dict)):
            return 'BLOCKED_COORDINATION_FENCE'
        try:
            previous = Decimal(str(position['confirmedClosed']))
            total = Decimal(str(position['originalShortQty']))
            steps = position['steps']
            if (isinstance(steps,bool) or not isinstance(steps,int) or
                steps < 1 or previous < 0 or total <= 0 or
                previous + qty > total or
                qty > total / Decimal(steps) or
                not all(v.is_finite() for v in (previous,total))):
                return 'BLOCKED_QUANTITY_LIMIT'
        except (KeyError,TypeError,InvalidOperation,ValueError):
            return 'BLOCKED_POSITION_QUANTITY'
        stored = current.get('offlineTerminalExecutions')
        if stored is not None:
            if (tuple(tuple(x) for x in stored) == records and
                current.get('offlineTerminalQty') == str(qty) and
                current.get('offlineFundingStatus') == 'UNRECONCILED'):
                return 'ALREADY_RECORDED_UNSETTLED'
            return 'BLOCKED_EXECUTION_REPLAY_DRIFT'
        if current.get('orderId') != evidence['orderId']:
            return 'BLOCKED_ORDER_IDENTITY'
        tx.set(claim_ref, {**current,
            'offlineTerminalExecutions': [list(x) for x in records],
            'offlineTerminalQty': str(qty),
            'offlineOrderTerminalVerified': True,
            'offlineFundingStatus': 'UNRECONCILED',
            'offlineFinancialSettlement': 'PENDING',
            'offlineNextClaimAuthorized': False})
        tx.set(position_ref, {**position, 'confirmedClosed': str(previous + qty),
            'lastTerminalIntentId': evidence['intentId'],
            'pending': True})
        return 'QUANTITY_RECORDED_UNSETTLED_NO_HANDOFF'
    try:
        return persist(db.transaction())
    except Exception:
        return 'BLOCKED_TRANSACTION'
