"""Offline independent CLOSE-order readback gate for standalone SHORT Recovery.

This function does not write claims, book profit, allocate funding, or submit.
It provides independently repeated execution facts to the existing reconciler.
Financial settlement and the next canonical order authorization remain separate.
"""
from decimal import Decimal, InvalidOperation
from short_recovery_aster_readback_mock_adapter import inspect
from short_recovery_order_claim_shadow import canonical_intent_id


def inspect_terminal_short_close_offline(*, client, account, symbol, cycle,
                                        step, claim, expected_quantity):
    """Return immutable order-only evidence or a fail-closed status."""
    if getattr(client, 'offline_mock_only', False) is not True:
        return {'status': 'BLOCKED_OFFLINE_CLIENT'}
    try:
        intent_id = canonical_intent_id(account=account, symbol=symbol,
            cycle=cycle, side='SHORT', action='CLOSE', step=step)
        qty = Decimal(str(expected_quantity))
        if not qty.is_finite() or qty <= 0:
            return {'status': 'BLOCKED_EXPECTED_QUANTITY'}
    except (TypeError, ValueError, InvalidOperation):
        return {'status': 'BLOCKED_INTENT_SCOPE'}
    if (not isinstance(claim, dict) or
        (claim.get('account'), claim.get('symbol'), claim.get('cycle'),
         claim.get('intentId'), claim.get('side'), claim.get('action'),
         claim.get('step')) !=
        (account, symbol, cycle, intent_id, 'SHORT', 'CLOSE', step) or
        claim.get('state') not in ('ACKED', 'PARTIAL', 'SUBMITTING', 'UNKNOWN') or
        not claim.get('orderId')):
        return {'status': 'BLOCKED_CLAIM_SCOPE'}
    first = inspect(client, symbol=symbol, client_order_id=intent_id)
    if first.get('status') != 'READBACK_PREVIEW':
        return {'status': first.get('status', 'BLOCKED_READBACK')}
    if first.get('orderStatus') != 'FILLED':
        return {'status': 'BLOCKED_NOT_FULLY_FILLED'}
    second = inspect(client, symbol=symbol, client_order_id=intent_id)
    if second != first:
        return {'status': 'BLOCKED_READBACK_DRIFT'}
    fills = first.get('fills')
    if not fills:
        return {'status': 'BLOCKED_NO_FILLS'}
    try:
        executions = [f['executionId'] for f in fills]
        amount = sum((f['quantity'] for f in fills), Decimal('0'))
        if (len(executions) != len(set(executions)) or amount != qty or
            any(f['orderId'] != str(claim['orderId']) for f in fills)):
            return {'status': 'BLOCKED_EXECUTION_SCOPE_OR_QUANTITY'}
        execution_financials = tuple(sorted(
            (f['executionId'], str(f['quantity']), str(f['realizedPnl']),
             str(f['fee'])) for f in fills))
    except (KeyError, TypeError, InvalidOperation):
        return {'status': 'BLOCKED_INCOMPLETE_FILLS'}
    return {'status': 'ORDER_EXECUTION_VERIFIED_UNSETTLED',
            'account': account, 'symbol': symbol, 'cycle': cycle,
            'step': step, 'intentId': intent_id, 'orderId': str(claim['orderId']),
            'executedQty': str(amount), 'executionFinancials': execution_financials,
            'fundingStatus': 'UNRECONCILED',
            'nextClaimAuthorized': False, 'profitVerified': False}
