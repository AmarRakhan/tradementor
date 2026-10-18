"""Fail-closed independent funding provenance decision; offline, no executor."""
NO_GO = 'NO_GO_INDEPENDENT_FUNDING_PROVENANCE_UNAVAILABLE'

def decide(*, account, symbol, cycle, income_rows=None, financial_proof=None):
    """Aster symbol income has no proven execution/side/cycle ownership or complete cursor.

    Caller-provided flags and enriched mock rows cannot grant authority.
    """
    return NO_GO
