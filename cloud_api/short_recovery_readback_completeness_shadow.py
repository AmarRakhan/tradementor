"""Offline-only Recovery readback completeness gate. Never authorizes an order.

The Aster income API has no stable cursor for events sharing a timestamp, so
funding cannot be safely allocated to a single order from a symbol-only read.
"""
from decimal import Decimal, InvalidOperation

_TERMINAL = {'FILLED', 'CANCELED', 'EXPIRED', 'REJECTED'}


def inspect_completeness(client, *, symbol, client_order_id, page_size=500, max_pages=20):
    def blocked(reason):
        return {'status': reason, 'complete': False, 'terminalVerified': False,
                'ledgerSafe': False, 'ordersSent': 0}

    if not symbol or not client_order_id or not 1 <= page_size <= 1000 or max_pages < 1:
        return blocked('BLOCKED_INPUT')
    try:
        order = client.query_order(symbol, client_order_id)
        if not isinstance(order, dict) or order.get('symbol') != symbol or order.get('clientOrderId') != client_order_id or not order.get('orderId'):
            return blocked('BLOCKED_ORDER_IDENTITY')
        if order.get('status') not in _TERMINAL:
            return blocked('BLOCKED_ORDER_NOT_FINAL')
        observed = []
        ids = set()
        cursor = None
        for _ in range(max_pages):
            args = {'limit': page_size}
            if cursor is not None:
                args['from_id'] = cursor
            page = client.user_trades(symbol, **args)
            if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                return blocked('BLOCKED_FILL_FORMAT')
            page_ids = []
            for row in page:
                try:
                    execution_id = int(row['id'])
                    quantity = Decimal(str(row['qty']))
                    pnl = Decimal(str(row['realizedPnl']))
                    fee = Decimal(str(row['commission']))
                except (KeyError, ValueError, TypeError, InvalidOperation, OverflowError):
                    return blocked('BLOCKED_FILL_EVIDENCE')
                if execution_id < 0 or not quantity.is_finite() or quantity <= 0 or not pnl.is_finite() or not fee.is_finite() or fee < 0:
                    return blocked('BLOCKED_FILL_EVIDENCE')
                if cursor is not None and execution_id < cursor:
                    return blocked('BLOCKED_FILL_CURSOR')
                page_ids.append(execution_id)
                if execution_id in ids:
                    return blocked('BLOCKED_DUPLICATE_FILL')
                ids.add(execution_id)
                if str(row.get('orderId')) == str(order['orderId']) and row.get('symbol') == symbol:
                    observed.append({'executionId': str(execution_id), 'quantity': quantity, 'realizedPnl': pnl, 'fee': fee})
            if len(page) < page_size:
                break
            if not page_ids:
                return blocked('BLOCKED_FILL_CURSOR')
            next_cursor = max(page_ids) + 1
            if cursor is not None and next_cursor <= cursor:
                return blocked('BLOCKED_FILL_CURSOR')
            cursor = next_cursor
        else:
            return blocked('BLOCKED_FILL_PAGINATION')
        try:
            executed = Decimal(str(order['executedQty']))
        except (KeyError, InvalidOperation, ValueError, TypeError):
            return blocked('BLOCKED_EXECUTED_QUANTITY')
        if not executed.is_finite() or executed < 0 or sum((x['quantity'] for x in observed), Decimal(0)) != executed:
            return blocked('BLOCKED_EXECUTION_INCOMPLETE')
        # Income events may be symbol-wide and funding has no orderId.  Even a
        # short page cannot prove the attribution to this owned hedge cycle.
        try:
            income = client.income_history(symbol=symbol, limit=page_size)
        except Exception:
            return blocked('BLOCKED_INCOME_UNAVAILABLE')
        if not isinstance(income, list) or any(not isinstance(row, dict) for row in income):
            return blocked('BLOCKED_INCOME_FORMAT')
        if len(income) >= page_size:
            return blocked('BLOCKED_INCOME_PAGINATION')
        if any(row.get('incomeType') == 'FUNDING_FEE' for row in income):
            return blocked('BLOCKED_FUNDING_ATTRIBUTION')
        # Missing income rows do not establish funding absence for the full
        # ownership interval; therefore no ledger write is permitted.
        return {'status': 'READBACK_SHADOW_UNPROVEN_FUNDING', 'complete': False,
                'terminalVerified': True, 'ledgerSafe': False, 'ordersSent': 0,
                'observedFills': observed}
    except Exception:
        return blocked('BLOCKED_READBACK_UNAVAILABLE')
