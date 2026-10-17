# SHORT Recovery 2.0 — canonical end-to-end pair-close gap (offline audit, 2026-10-17)

**Status: NO-GO. This document does not authorize an order.**

Verified in source: `short_recovery_order_claim_shadow.reserve()` owns one claim with `(account,symbol,cycle,intentId)` and requires `ownerSide=SHORT`. `short_recovery_order_resolution_shadow.resolve()` writes a SHORT allocation ledger and one claim. The pair-level `verify_pair_exit_settlement()` and `pair_exit_recovery_gate()` in `short_recovery_executor_adapter.py` accept separate LONG/SHORT order dictionaries and claim states but do not read two persisted side-scoped claims, do not reconcile their fills through the canonical ledger and never call Aster's executor. They cannot yet prove the two-leg transition.

## Minimum integrated completion contract
1. **One account/cycle-scoped pair identity and independent LONG and SHORT claims.** Persist each client-order-ID, Aster order-ID, quantity, side, terminal state, and verified exchange fill IDs under the same pair cycle. Preserve Recovery's existing SHORT allocation ownership and leave legacy Auto Hedge unchanged when Recovery is off.
2. **Read and reconcile both legs independently before any next submit.** Use existing Aster `query_order` and paginated `user_trades` via the existing gateway. `UNKNOWN`, partial, cancellation, and timeout retain claims. A late readback must not rebind order IDs. Never infer no-order from an expired lease. Check for outstanding exchange orders and actual position quantities.
3. **Atomic persistence of reconciled side inventories and economics.** After verified executions, update the canonical pair ledger with deduplicated exchange execution IDs and explicit PnL, commission and funding provenance. Treat an unclosed side or mismatched position quantity as unresolved; do not mark a pair closed or send a second close implicitly.
4. **Funding provenance.** `income_history()` is timestamp/limit paginated and supplies no stable transaction-ID continuation in this wrapper; `funding_for_cycle()` requires external exclusive ownership proof per `tranId`. No full pair net-profit TP when history coverage or cycle ownership is unproved. Never replace unknown funding with zero.
5. **Only then wire into the existing guarded executor.** Implement a pair-level transaction/reservation scope, preserve account stop/close-all guards, revalidate at Aster `before_order_submit`, and reconcile uncertain POSTs before further orders. Test offline concurrency/restart/partial/one-sided fill/UNKNOWN/funding missing, then run local emulator. No autonomous residual order recovery until those invariants are met.

Current mocks passing is not evidence that this contract is implemented. No live pilot approval.
