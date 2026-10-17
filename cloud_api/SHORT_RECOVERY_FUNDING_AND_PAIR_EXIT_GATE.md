# SHORT Recovery 2.0 — proven evidence boundary (offline)

Reviewed on 2026-10-17 against `aster_gateway.py`, `short_recovery_funding_shadow.py`, and `short_recovery_order_resolution_shadow.py`.

## Funding
- `AsterV3Client.income_history()` requests `/fapi/v3/income` using `symbol`, optional `incomeType`, timestamp range and `limit`. This wrapper does **not** expose a stable income transaction ID cursor.
- A full timestamp-bounded income page cannot prove completeness where multiple income events share one millisecond. `income_pages()` correctly refuses a full page rather than guessing a continuation.
- A funding row's symbol/time (and even an optional side) does not prove which price-zone allocation and hedge cycle owns the transaction. `funding_for_cycle()` requires independently evidenced `tranId` -> (symbol, side, cycle) ownership for *every* funding event.
- Consequently the existing exchange adapter cannot currently certify full net profit for overlapping hedge cycles based solely on Aster income and userTrades responses. Missing evidence remains unknown, never a synthetic zero. No settlement or live GO is justified by this document.

## Partial pair close
- The canonical `resolve()` keeps an already filled but then terminally cancelled order in `PARTIAL_TERMINAL`, preserving the claim and inventory for reconciliation, rather than releasing another order.
- A `CANCEL_TERMINAL` applied after any fill now additionally requires explicitly verified terminal readback and a matching Aster order ID. This verifies the supplied *mock* evidence contract, not authenticity against the exchange in production.
- No automatic residual LONG/SHORT order is authorized. Complete both-side exchange reconciliation, risk checks and independent funding attribution before considering a pilot.

## Execution integration gate review (2026-10-17)
`aster_position_loss_auto_hedge_extension.py` invokes Recovery only under `not execute` and `ASTER_SHORT_RECOVERY_SHADOW_ENABLED=true`, after the existing reconciliation call. Thus the new atomic pair-settlement has no live executor caller and cannot govern live orders. Making it active would require (a) a canonical account/cycle-level order guard and persisted side claims shared by the existing Auto Hedge reconciler, (b) an authoritative desired-hedge transition avoiding legacy 1:1 top-up on intentional partial SHORT, and (c) pre-submit readback/stop checks and terminal settlement before any fresh order. Do not enable it without those invariants and a separately authorized live pilot.

Aster income_history's available parameters are symbol/type/start/end/limit, not an income ID cursor. Price-zone/cycle ownership is not present in that contract; two hedge cycles on the same symbol and side cannot be distinguished by these records alone. The current `funding_for_cycle()` accepts independently supplied transaction ownership, but exchange retrieval does not establish it. Inability to prove income completeness or attribution must fail closed; cannot claim net TP or live readiness.
