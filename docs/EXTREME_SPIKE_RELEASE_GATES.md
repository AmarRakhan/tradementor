# Extreme Spike 1.0 — concurrent order safety release gate

Status: NOT PROVEN, NO-GO for production.

## Confirmed code behavior
- Same spike candle/side/timeframe yields a deterministic event key.
- Candidate and pre-order evaluation must match the same completed candle.
- Normal order submit uses `mbb-open-...` client order IDs.
- `aster_gateway.submit_order_once` recovers an uncertain POST with one GET, and never blindly retries that uncertain POST.

## Critical residual race
Two concurrent account ticks may both:
1. Observe the same spike.
2. See no current position.
3. Pass the same config/capacity gates.
4. Submit the same client order ID.

A deterministic ID does NOT prove that both cannot produce a second order. A subsequent tick after a completed TP may also re-use a prior event if Aster permits client-order-ID recycling or if old order history is unavailable.

## Mandatory fail-closed solution
- Identify the existing account-level scanner lock/lease, transaction boundaries, and order-intent persistence.
- Claim the (account, symbol, side, timeframe, spike candle) event atomically before **any** exchange side effect (including leverage/margin changes), within existing canonical order execution. No second independent scanning pipeline.
- Claim states should support PENDING/SUBMITTED/FILLED/UNKNOWN with a safe TTL/reconciliation contract. Do not automatically unlock UNKNOWN for a retry.
- Existing historical signals must not be re-consumed after TP; enable a new event only for a newly completed qualifying spike candle.
- Add controlled two-worker barrier/concurrency test, restart and error-injection tests. Verify one POST at most, no new OPEN after TP for the same event, and a newly qualified event permits an OPEN.
- Validate that legacy OFF/BOLLINGER paths never use this new claim and retain current behavior.

## Remaining UI release gates
- Only one authoritative mode OFF/BOLLINGER/EXTREME_SPIKE; avoid two competing controls and PUT races.
- 1:1 screenshots for reference IDs file_00000000b64c820a8071cb6453a32f6d and file_000000001f408243967fc81117b60b75.
- Per-user saved GET/PUT state and active runtime mode readback, including failure rollback.
- Cross-account safety tests with existing positions, DCA, TP and portfolio TP unchanged.

Never merge to production without these tests and explicit production verification.

## Critical verified ordering — must resolve before production
Current `aster_execution.execute_leg_once` configures margin mode and
leverage for OPEN *before* calling `before_submit`.
Current Spike claim occurs inside the canonical decision_provider reached in
`before_submit`. Thus an unsuccessful/double Spike claim prevents the order
POST, but may still follow a margin/leverage side effect. This is **NOT**
sufficient to claim the four accounts are untouched on rejection.
Required before GO: move the necessary gate/reservation ahead of any
risk-increasing side effect for Spike OPEN, without changing the legacy
OFF/BOLLINGER behavior, OR demonstrate an equivalent pre-existing account-level
exclusive lock plus test proof. Preserve the revalidation immediately before
actual submit. Add concurrency/failure-injection tests for leverage/margin
calls and order POST counts; any claim failure must cause zero exchange mutations.

## Verified development-branch checks (2026-10-13)
- Cloud Backend CI 38419996531: SUCCESS.
- Runtime Contract V1 38419996653: SUCCESS.
- Web Cloud CI 38419996730: SUCCESS.
- Spike OPEN now uses pre_mutation_admission before entering low-level executor;
  final decision_provider revalidates before order POST. Earlier ordering
  warning above describes the **pre-fix** state; retain it as an audit trail.
- Unit tests for concurrent same-account claims, cross-account identity,
  uncertain order retry suppression, and pre-mutation denial exist and passed CI.
- No real Firestore emulator/project integration was run, so atomic claim
  authorization and document-path isolation against the deployed IAM rules are
  unverified. Run in a disposable **non-production** Firebase test project only.
- Existing visual QA artifact is for legacy Botconfigurator, NOT a pixel check of
  Extreme Spike component. Screenshot the actual new card in 390px and Fold
  layouts including an open dropdown, compare against approved design.
- Legacy save protection is tested by source-contract tests. End-to-end actual
  GET -> PUT -> GET readback remains unverified. Tests must exercise unavailable
  GET => 409 (no mutation), explicit mode changes, and restored settings.
- **Release remains NO-GO** pending those three real integration checks.
