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

## Latest release checkpoint (commit 60af1b1)
All 6 workflows completed SUCCESS: emulator 38423995982, backend 38423995491,
runtime 38423995542, web 38423995305, bot settings reference 38423995361,
Android 38423995461. The emulator gate runs real Firestore create operations
against a disposable loopback emulator, but is **not** a production IAM test.
Responsive visual artifact captures the isolated Extreme Spike component
including expanded dropdown, not the entire authenticated settings host.
GET-after-PUT verification is implemented and covered with source contract
tests, but an authenticated end-to-end test against a disposable application
backend has not been proven. No current production rollout or live user
configuration change is authorized solely by green CI.

**Remaining sign-off:** exercise authenticated settings GET -> PUT -> GET on
staging with disposable user, including OFF/BOLLINGER/EXTREME_SPIKE, refresh,
legacy editor, and failure rollback; then validate integrated settings host
for overlay/z-index and clipping. Record PASS evidence before merge/deploy.

## Staging end-to-end acceptance procedure — required before GO
**Isolated environment only:** use a disposable staging account and exchange
sandbox/mock executor with trading disabled. No production user tokens, accounts,
Firestore documents, exchange API keys or orders.

1. GET authenticated `/api/exchanges/aster`; record the original staging
   `strategy2.settings` snapshot and the canonical version.
2. PUT to `/api/exchanges/aster/strategy2/settings` all existing settings,
   changing only `entryFilterMode=EXTREME_SPIKE`,
   `bollingerEntryFilter15mEnabled=false`, sigma `5-6`,
   LONG `1m`, SHORT `15m`. Require 2xx and an independent GET readback
   with exact matching values.
3. Invoke the **actual existing scanner tick** with controlled closed candles
   in sandbox/mock exchange. Assert LONG reads 1m candles and SHORT reads 15m;
   observed gate result must match the configured sigma band, not an old
   Bollinger gate. Assert ZERO exchange POSTs and ZERO margin/leverage mutations.
4. Save `OFF`, reload and assert no additional entry filter; save
   `BOLLINGER`, reload and assert Spike evaluation is absent.
5. With Spike active, submit a legacy-editor payload without `entryFilterMode`
   and assert persisted Spike mode is unchanged. Inject a failed GET and
   assert 409 with zero setting mutations.
6. Verify full authenticated settings host on narrow phone and Fold widths:
   dropdown options remain clickable and unoccluded, success/error status
   visible, and no horizontal overflow.
7. Restore original staging snapshot. Confirm no production account touched.
   Attach request/response redacted logs, scanner admission trace, and screenshots.
**Release authority:** require a human review of logs/screenshots and explicit
GO before merging/deploying; previous passing CI alone is insufficient.

## Explicit end-to-end execution target (2026-10-13)
The real scanner entrypoint is `cloud_api.aster_multi_bb_core.run_multi_bb_step`
(line ~760 at feature head), **not** `require_extreme_spike_entry` in
isolation. The final staging/sandbox test must call `run_multi_bb_step`
using an isolated account document with settings read back through the
authenticated settings API. Inject a controlled exchange client and assert:
* Complete qualifying candles yield the correct admission route for configured
  LONG 1m / SHORT 15m; nonqualifying and OFF/BOLLINGER choices use their
  respective canonical paths.
* No real order POST, margin or leverage mutation is possible from the test;
  all trading methods are hard-failed mocks, and no real exchange credentials
  are available.
* The account's existing DCA, take-profit and position state remain unchanged.
* Both save error rollback and switching settings during a scanner tick reject
  stale admissions.
Do **not** interpret standalone candle adapter, config-roundtrip or route
unit-test success as this final proof. Production GO remains blocked until the
real scanner entrypoint plus authenticated API has been exercised together.

## Scanner dry-run boundary confirmed
`run_multi_bb_step(..., dry_run=True)` traverses the real scanner candidate
admission path and returns simulated `ENTRY` actions, but intentionally
bypasses `execute_approved_leg_once`, final fresh-settings validation, and
atomic Spike reservation. Therefore a scanner dry-run is a **valuable separate
test**, NOT a substitute for pre-submit/Firestore controls or authenticated
settings-to-scanner staging E2E. Existing tests cover those layers separately;
do not report them as one integrated execution.

## Integrated isolated smoke — confirmed 2026-10-13
Commit `c3970783aacdf9ceb8b189af2b9e89f758c74db0`:
- Extreme Spike isolated safety tests run **38449696379 succeeded**.
- Real Strategy2 PUT route is executed against an injected mock backend; its
  output feeds `run_multi_bb_step` in dry_run with controlled candles.
- Backend, Firestore emulator, runtime and web CI also succeeded.
- This is not an authenticated deployment/staging test. Final pre-submit order
  admission is bypassed by dry_run, but covered by separate order-gate tests.
- Remaining: isolated authenticated staging account and full settings host
  visual confirmation, plus explicit review/GO. Do not merge or deploy on
  green CI alone.
