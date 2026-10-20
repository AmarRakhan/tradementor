"""Isolated strategy selection and position-adoption contract; OFFLINE ONLY.

The classic scanner/configuration is deliberately untouched. This module grants
no live transport authority; submitted orders must use existing canonical claims.
"""
from decimal import Decimal
from short_recovery_adoption import adoption_preview
from short_recovery_contract import Plan
from short_recovery_reduction import ReductionState, plan_reduction

CLASSIC = 'ASTER_CLASSIC'
RECOVERY = 'AUTO_HEDGE_SHORT_RECOVERY_2'


def select_strategy_offline(*, db, transactional, selector_ref, control_ref,
                            coordination_ref, account, selected):
    """Atomic, fail-closed strategy switch without executing orders."""
    if selected not in (CLASSIC, RECOVERY) or not account:
        return 'BLOCKED_STRATEGY'
    @transactional
    def switch(tx):
        selector = selector_ref.get(transaction=tx).to_dict()
        control = control_ref.get(transaction=tx).to_dict()
        coordination = coordination_ref.get(transaction=tx).to_dict()
        if not isinstance(control, dict) or control.get('account') != account or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False:
            return 'BLOCKED_CONTROL'
        if selector is not None and (not isinstance(selector, dict) or selector.get('account') != account):
            return 'BLOCKED_SELECTOR_SCOPE'
        if coordination is not None:
            if not isinstance(coordination, dict) or coordination.get('recoveryFenceReservation') is not None or coordination.get('lease') is not None:
                return 'BLOCKED_INFLIGHT_COORDINATION'
        if isinstance(selector, dict) and selector.get('pendingOrders') is True:
            return 'BLOCKED_INFLIGHT_ORDERS'
        if isinstance(selector, dict) and selector.get('activeStrategy') == selected:
            return 'ALREADY_SELECTED_OFFLINE'
        tx.set(selector_ref, {'account': account, 'activeStrategy': selected,
                              'adoptionStatus': 'PENDING_VERIFICATION' if selected == RECOVERY else 'NOT_APPLICABLE',
                              'offlineOnly': True})
        return 'SELECTED_OFFLINE_PENDING_ADOPTION' if selected == RECOVERY else 'SELECTED_CLASSIC_OFFLINE'
    try:
        return switch(db.transaction())
    except Exception:
        return 'BLOCKED_TRANSACTION'


def adopt_existing_hedge_offline(*, db, transactional, selector_ref, position_ref,
                                 control_ref, coordination_ref, account, hedge,
                                 steps, step_pct):
    """CAS-adopt a proven existing 1:1 hedge; never fabricate an entry anchor."""
    if hedge.account != account:
        return 'BLOCKED_ACCOUNT_SCOPE'
    try:
        preview = adoption_preview(hedge, user_enabled=True, steps=steps, step_pct=step_pct)
        if preview['status'] != 'ELIGIBLE_PREVIEW_ONLY':
            return preview['status']
        plan = Plan(preview['anchor_price'], preview['original_short_qty'],
                    Decimal(str(step_pct)), steps)
    except (TypeError, ValueError, ArithmeticError):
        return 'BLOCKED_ADOPTION_DATA'
    @transactional
    def adopt(tx):
        selector = selector_ref.get(transaction=tx).to_dict()
        position = position_ref.get(transaction=tx).to_dict()
        control = control_ref.get(transaction=tx).to_dict()
        coordination = coordination_ref.get(transaction=tx).to_dict()
        if not isinstance(selector, dict) or selector.get('account') != account or selector.get('activeStrategy') != RECOVERY or selector.get('offlineOnly') is not True:
            return 'BLOCKED_STRATEGY_NOT_SELECTED'
        if not isinstance(control, dict) or control.get('account') != account or control.get('enabled') is not True or control.get('emergencyStop') is not False or control.get('closeAllActive') is not False:
            return 'BLOCKED_CONTROL'
        if position is not None:
            return 'BLOCKED_ALREADY_OWNED'
        if coordination is not None and (not isinstance(coordination, dict) or coordination.get('recoveryFenceReservation') is not None or coordination.get('lease') is not None):
            return 'BLOCKED_INFLIGHT_COORDINATION'
        tx.set(position_ref, {'account': account, 'symbol': hedge.symbol,
                              'longPositionId': hedge.long_position_id,
                              'cycle': hedge.hedge_cycle_id,
                              'originalShortQty': str(plan.initial_short_qty),
                              'longQty': str(hedge.long_qty),
                              'anchor': str(plan.anchor), 'steps': steps,
                              'stepPct': str(plan.step_pct),
                              'confirmedClosed': '0', 'pending': False,
                              'state': 'ADOPTED_OFFLINE', 'offlineOnly': True})
        return 'ADOPTED_OFFLINE'
    try:
        return adopt(db.transaction())
    except Exception:
        return 'BLOCKED_TRANSACTION'


def preview_adopted_reduction(*, db, selector_ref, position_ref, account, mark):
    """Read-only planner; no order authorization and no funding assumptions."""
    try:
        selector = selector_ref.get(transaction=db.transaction()).to_dict()
        position = position_ref.get(transaction=db.transaction()).to_dict()
        if not isinstance(selector, dict) or selector.get('account') != account or selector.get('activeStrategy') != RECOVERY or selector.get('offlineOnly') is not True or not isinstance(position, dict) or position.get('account') != account or position.get('offlineOnly') is not True or position.get('state') != 'ADOPTED_OFFLINE':
            return {'status': 'BLOCKED_STRATEGY_OR_ADOPTION'}
        plan = Plan(Decimal(position['anchor']), Decimal(position['originalShortQty']),
                    Decimal(position['stepPct']), position['steps'])
        return plan_reduction(ReductionState(plan, Decimal(position['confirmedClosed']), Decimal(str(mark)), pending=position.get('pending') is True))
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return {'status': 'BLOCKED_INVALID_POSITION'}
