"""Bouwstop 60: fail-closed evidence audit; offline only, no client calls or writes."""
from decimal import Decimal, InvalidOperation


def ownership_audit(*, rows, symbol, side, cycle_id, start_ms, end_ms, exclusive_event_owners):
    """Audit event-level exclusivity: never infer a cycle from symbol/side/time alone."""
    def block(reason):
        return {'status': reason, 'proven': False, 'funding': None, 'ordersSent': 0}
    if not symbol or side not in ('LONG', 'SHORT') or not cycle_id or not isinstance(exclusive_event_owners, dict) or not isinstance(start_ms, int) or not isinstance(end_ms, int) or start_ms >= end_ms:
        return block('BLOCKED_SCOPE')
    if not isinstance(rows, (tuple, list)):
        return block('BLOCKED_FORMAT')
    seen = set()
    funding = Decimal(0)
    for row in rows:
        if not isinstance(row, dict):
            return block('BLOCKED_FORMAT')
        if row.get('incomeType') != 'FUNDING_FEE':
            continue
        try:
            ident = str(row['tranId'])
            stamp = int(row['time'])
            value = Decimal(str(row['income']))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return block('BLOCKED_EVENT')
        if not ident or ident in seen or not value.is_finite() or row.get('symbol') != symbol or row.get('positionSide') != side or not start_ms <= stamp < end_ms:
            return block('BLOCKED_EVENT')
        seen.add(ident)
        if exclusive_event_owners.get(ident) != (symbol, side, cycle_id):
            return block('BLOCKED_OWNERSHIP_PROOF')
        funding += value
    # Caller cannot establish exhaustive income history from this audit alone.
    return {'status': 'SHADOW_ATTRIBUTION_PREVIEW', 'proven': bool(seen), 'funding': funding if seen else None, 'ledgerSafe': False, 'ordersSent': 0}


def timestamp_boundary_audit(page, *, page_size):
    """A full page is intrinsically ambiguous with timestamp-only pagination."""
    if not isinstance(page, list) or page_size < 1 or any(not isinstance(row, dict) for row in page):
        return 'BLOCKED_PAGE_FORMAT'
    if len(page) >= page_size:
        return 'BLOCKED_TIMESTAMP_CURSOR_AMBIGUOUS'
    return 'SHADOW_SHORT_PAGE_ONLY'
