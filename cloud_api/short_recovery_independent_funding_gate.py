"""Offline-only independent funding prerequisite for canonical pair settlement.

The Aster income endpoint lacks a stable cursor and a verified per-execution
hedge-cycle allocation. This gate never upgrades a user-asserted proof.
"""
from short_recovery_funding_shadow import read_bounded_symbol_funding


def inspect_mock_coverage(*, client, account, symbol, cycle, start_ms, end_ms):
    """Fail closed on missing exchange completeness and ownership provenance."""
    if (getattr(client, 'offline_mock_only', False) is not True or
            not isinstance(cycle, str) or not cycle):
        return 'BLOCKED_INDEPENDENT_FUNDING_CLIENT_OR_CYCLE'
    try:
        snapshot = read_bounded_symbol_funding(client, symbol=symbol, account=account,
                                                start_ms=start_ms, end_ms=end_ms)
    except (ValueError, TypeError, KeyError, AttributeError):
        return 'BLOCKED_INCOME_READBACK_INCOMPLETE'
    if (snapshot.get('account') != account or snapshot.get('symbol') != symbol or
            snapshot.get('startMs') != start_ms or snapshot.get('endMs') != end_ms or
            snapshot.get('complete') is not True or
            snapshot.get('independentlyVerified') is not True):
        return 'BLOCKED_INDEPENDENT_FUNDING_COMPLETENESS'
    # Even an independently complete symbol-wide window cannot prove how
    # individual funding events belong to this hedge cycle or each side.
    from short_recovery_funding_provenance_decision import decide
    return decide(account=account, symbol=symbol, cycle=cycle, income_rows=snapshot.get('rows'))
