"""Read-only proof helpers for Recovery funding; never places orders or writes ledgers."""
from decimal import Decimal, InvalidOperation


def income_pages(client, *, symbol, start_ms, end_ms, page_size=500, max_pages=20):
    """Fail closed on full pages: timestamp pagination cannot split equal-time events."""
    if not symbol or not isinstance(start_ms, int) or not isinstance(end_ms, int) or start_ms >= end_ms or not 1 <= page_size <= 1000 or max_pages < 1:
        raise ValueError('BLOCKED_WINDOW')
    cursor = start_ms
    rows = []
    seen = set()
    for _ in range(max_pages):
        page = client.income_history(symbol=symbol, start_time=cursor, end_time=end_ms, limit=page_size)
        if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
            raise ValueError('BLOCKED_INCOME_FORMAT')
        if len(page) == page_size:
            # A time-only cursor cannot establish that no further transactions
            # share the timestamp of this page's last event.
            raise ValueError('BLOCKED_SAME_TIMESTAMP_PAGINATION')
        previous_time = None
        for row in page:
            try:
                time = int(row['time'])
                identity = str(row['tranId']) if row.get('tranId') is not None else ''
            except (KeyError, TypeError, ValueError):
                raise ValueError('BLOCKED_INCOME_IDENTITY')
            if not identity or not cursor <= time <= end_ms or identity in seen or row.get('symbol') != symbol:
                raise ValueError('BLOCKED_INCOME_IDENTITY')
            if previous_time is not None and time < previous_time:
                raise ValueError('BLOCKED_INCOME_ORDER')
            previous_time = time
            seen.add(identity)
            rows.append(row)
        return tuple(rows)
    raise ValueError('BLOCKED_INCOME_PAGE_LIMIT')


def funding_for_cycle(rows, *, symbol, side, cycle_id, start_ms, end_ms, ownership_proof):
    """Returns funding only with explicit exclusive-cycle ownership proof.

    Symbol and side alone do not identify a Recovery hedge cycle. Each event
    must be individually tied to that cycle by independent persisted evidence.
    """
    if not cycle_id or side not in {'LONG', 'SHORT'} or start_ms >= end_ms or not isinstance(ownership_proof, dict):
        raise ValueError('BLOCKED_OWNERSHIP')
    total = Decimal('0')
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('BLOCKED_INCOME_FORMAT')
        if row.get('incomeType') != 'FUNDING_FEE':
            continue
        try:
            identity = str(row['tranId']) if row.get('tranId') is not None else ''
            timestamp = int(row['time'])
            value = Decimal(str(row['income']))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise ValueError('BLOCKED_FUNDING_EVIDENCE')
        if not identity or identity in seen or not value.is_finite() or row.get('symbol') != symbol or not start_ms <= timestamp < end_ms:
            raise ValueError('BLOCKED_FUNDING_EVIDENCE')
        seen.add(identity)
        # Without positionSide, or proof of exclusive ownership of the actual
        # funding transaction, neither netting nor proportional allocation is safe.
        if row.get('positionSide') != side or ownership_proof.get(identity) != (symbol, side, cycle_id):
            raise ValueError('BLOCKED_FUNDING_ATTRIBUTION')
        total += value
    # An empty result cannot establish that funding was zero: a missing or
    # incomplete income window is observationally identical. Only a separate
    # completeness/ownership attestation could authorize zero funding.
    if not seen:
        raise ValueError('BLOCKED_ZERO_FUNDING_NOT_PROVEN')
    return total
