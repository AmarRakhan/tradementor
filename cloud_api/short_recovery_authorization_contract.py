"""Offline boundary: legacy mock financial proof is NEVER execution authority."""

def classify(*, mode, account, symbol, cycle, evidence):
    if mode == 'LEGACY_MOCK_TEST':
        return 'LEGACY_MOCK_ONLY_NOT_AUTHORIZED'
    # There is not yet an exchange-signed, independently complete funding and
    # side/execution/cycle ownership attestation in the Aster V3 readback API.
    # Caller supplied dictionaries, flags, and income-window records cannot
    # grant a production or future executor entitlement.
    return 'BLOCKED_INDEPENDENT_EXECUTION_AUTHORIZATION'
