"""Standalone Recovery decision orchestration: PURE OFFLINE, NEVER submits orders.

All returned actions are previews, not canonical claims or authority to send.
Funding is deliberately not read, inferred, or counted as profit.
"""
from decimal import Decimal, InvalidOperation
from short_recovery_contract import Plan
from short_recovery_reduction import ReductionState, plan_reduction
from short_recovery_standalone_offline import RECOVERY
from short_recovery_minimum_order_preview_offline import preview_minimum_aware_reduction


def _decimal(value):
    v=Decimal(str(value))
    if not v.is_finite(): raise ValueError('nonfinite')
    return v


def preview_cycle(*, active_strategy, account, position, exchange, mark,
                  auto_hedge_loss_usd, open_long_pnl, stop=False,
                  close_all=False, pending=False, final_order_verified=False,
                  exchange_filters=None):
    """One action preview; independent of Classic strategy and financial income.

    Caller must establish authentic exchange inventory before a future submit.
    A mocked boolean here NEVER authorizes transport or claim transfer.
    """
    if active_strategy != RECOVERY:
        return {'status':'BLOCKED_STRATEGY_NOT_ACTIVE'}
    if stop or close_all:
        return {'status':'BLOCKED_STOP'}
    if pending:
        return {'status':'WAIT_PENDING'}
    if not isinstance(position,dict) or not isinstance(exchange,dict):
        return {'status':'BLOCKED_READBACK'}
    if position.get('account') != account or exchange.get('account') != account or position.get('symbol') != exchange.get('symbol'):
        return {'status':'BLOCKED_ACCOUNT_OR_SYMBOL'}
    if exchange.get('verified') is not True or exchange.get('hedgeMode') is not True or exchange.get('openOrders') != []:
        return {'status':'BLOCKED_INVENTORY_UNVERIFIED'}
    if position.get('offlineOnly') is not True:
        return {'status':'BLOCKED_OFFLINE_ONLY'}
    try:
        long=_decimal(exchange['LONG']); short=_decimal(exchange['SHORT'])
        pnl=_decimal(open_long_pnl); loss=_decimal(auto_hedge_loss_usd)
        if long<=0 or short<0 or loss<=0: return {'status':'BLOCKED_QUANTITY_OR_TRIGGER'}
        state=position.get('state')
        if state=='LONG_UNHEDGED_OFFLINE':
            if short!=0:return {'status':'BLOCKED_UNEXPECTED_SHORT'}
            if pnl > -loss: return {'status':'WAIT_HEDGE_TRIGGER'}
            return {'status':'PREVIEW_INITIAL_HEDGE','side':'SHORT','action':'OPEN','quantity':long,
                    'requiresCanonicalOrderClaim':True,'requiresImmediateInventoryReadback':True}
        if state not in ('ADOPTED_OFFLINE','RECOVERY_ACTIVE_OFFLINE','FINAL_SHORT_FILLED_OFFLINE'):
            return {'status':'BLOCKED_STATE'}
        plan=Plan(_decimal(position['anchor']),_decimal(position['originalShortQty']),
                  _decimal(position['stepPct']),position['steps'])
        closed=_decimal(position['confirmedClosed'])
        if closed<0 or closed>plan.initial_short_qty:
            return {'status':'BLOCKED_CONFIRMED_QUANTITY'}
        expected=plan.initial_short_qty-closed
        if short!=expected:
            return {'status':'BLOCKED_INVENTORY_MISMATCH'}
        if closed==plan.initial_short_qty:
            if short!=0:return {'status':'BLOCKED_INVENTORY_MISMATCH'}
            if final_order_verified is not True:return {'status':'BLOCKED_FINAL_ORDER_UNVERIFIED'}
            return {'status':'PREVIEW_IMMEDIATE_REHEDGE','side':'SHORT','action':'OPEN',
                    'quantity':long,'newCycleRequired':True,'requiresCanonicalOrderClaim':True,
                    'requiresImmediateInventoryReadback':True}
        reduction_state=ReductionState(plan,closed,_decimal(mark))
        if exchange_filters is not None:
            if not isinstance(exchange_filters,dict):
                return {'status':'BLOCKED_EXCHANGE_FILTER'}
            required=('minimum_qty','quantity_step','minimum_notional','executable_price')
            if any(k not in exchange_filters for k in required):
                return {'status':'BLOCKED_EXCHANGE_FILTER'}
            reduced=preview_minimum_aware_reduction(
                state=reduction_state,exchange_short_qty=short,
                **{k:exchange_filters[k] for k in required})
            if reduced['status']!='PREVIEW_MINIMUM_VALID_REDUCE_ONLY':
                return reduced
        else:
            reduced=plan_reduction(reduction_state)
        if reduced['status'] not in ('PREVIEW_REDUCE_ONLY','PREVIEW_MINIMUM_VALID_REDUCE_ONLY'):return reduced
        due=reduced['due_qty']
        if due<=0 or due>short:return {'status':'BLOCKED_OVER_CLOSE'}
        return {'status':'PREVIEW_SHORT_REDUCE','side':'SHORT','action':'CLOSE',
                'quantity':due,'reachedSteps':reduced['reached_steps'],
                'requiresCanonicalOrderClaim':True,'requiresImmediateInventoryReadback':True}
    except (KeyError,TypeError,ValueError,InvalidOperation,ArithmeticError):
        return {'status':'BLOCKED_INVALID_FINANCIAL_OR_POSITION_INPUT'}
