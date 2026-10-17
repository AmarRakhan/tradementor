# SHORT Recovery Plan 2.0 — integrated offline live-gate audit

Date: 2026-10-17 (Europe/Amsterdam); baseline 05c000eb; feature/short-recovery-contract-20261016.

## Verified offline tests
- `cd cloud_api && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -p 'test_short_recovery*.py'`: 339 passed, 0 failed.
- `cd cloud_api && PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q test_aster_cost_evidence.py test_aster_gateway.py test_aster_dynamic_hedge_execution.py test_aster_dynamic_hedge_execution_hardening.py`: 52 passed, 0 failed.
- No authenticated Aster read, real Firestore transaction, exchange order or production smoke test performed.

## Confirmed blockers and exact evidence
1. **Executor wiring**: `cloud_api/short_recovery_executor_adapter.py` says `Mock-only adapter` and always sets `ordersSent: 0`. No evidence that SHORT Recovery decisions reach a production order executor. Must prove one centrally gated, authorized and idempotent lifecycle in a non-production integration environment.
2. **Durable ownership and atomicity**: `cloud_api/short_recovery_transaction_adapter.py` explicitly says `Not connected to production`. Mock Firestore CAS and restart/concurrency tests do not validate real Firestore paths, retries or ownership after process restart.
3. **Financial finality**: `cloud_api/short_recovery_readback_completeness_shadow.py` does not authorize settlement without full readback, executedQty and funding proof. Test the real response schema, terminal order status, partial and canceled executions, and stale/late executions before allowing any ledger write.
4. **Funding attribution**: `cloud_api/aster_strategy2_runtime.py` selects funding by symbol, positionSide and created_at_ms, not by a separately proven Recovery cycle event owner; `short_recovery_build60_evidence_shadow.py` requires transaction-exclusive ownership proof. No established event-level evidence for live Recovery is present.
5. **Income completeness**: `cloud_api/aster_gateway.py` income_history accepts time windows but has no income `fromId` cursor. `cloud_api/aster_cost_evidence.py` advances a full page using max timestamp + 1, potentially excluding equal-timestamp events. Recovery shadow code blocks full timestamp-only pages; this is not a verified complete-history solution.
6. **Emergency stop and mode isolation**: account-wide emergency code exists in `cloud_api/main.py`, but no end-to-end proof was found that it cancels/disables a Recovery order between claim, preflight, submit, settlement and restart. It must also preserve older Auto Hedge users, position parity and the designated test account isolation.

## Required path to limited pilot (strict gates)
A. Integrate read-only production-schema replay against redacted captured Aster responses, with provably complete history or fail closed and transaction-exclusive funding ownership (or independently proven account/side/time exclusivity for the entire interval).
B. Build an isolated, production-equivalent Firestore emulator or authorized staging setup to exercise idempotent claims, exact account/cycle ownership, restart/reconcile, partial fills, duplicate/delayed callbacks, and no double exposure.
C. Route Recovery intent through the established centralized guarded executor, with explicit feature flag default OFF, active stop checks before submit/retry, symbol/account restrictions, quantity bounds, hedge 1:1, and NO orders in these tests.
D. Execute shadow against real read-only account snapshots, including zero-order invariants and restart scenarios; independently verify mismatch/stop behavior.
E. Only after A-D pass: request explicit separate approval for a tightly limited one-account, one-cycle live pilot with minimum exchange-compliant size and rollback/stop criteria. Do not silently enable any account.

**GO** for offline development only. **NO-GO** for live execution or deployment.
