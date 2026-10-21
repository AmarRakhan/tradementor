# CLOSE PROFITS 2.1 SAFE FIX — Claude handoff (round 2, after independent ChatGPT review)

Repo `AmarRakhan/tradementor` · PR #783 (draft) · Branch `review/close-profits-2-1-safe-20261021`
**Code commit to review: `320c4c7a460aff1a77c2a07dca84ea8c2e115d50`** · round 1 code commit: `bddff04c3c994d7bb0fe12966f2d301a68fab511` · PR #783 head: `f8cd2af5f76c6b240bd49c87deedbbe8622ef4ea`.
A later commit on the same branch only adds this file and the patches (a file cannot contain its own SHA).
Not merged, not deployed, no Cloud Build, no live orders, build 601 untouched, SHORT Recovery 2.0 untouched, Auto Hedge/Recovery code untouched (one additive helper in the lock module).

## 0. What round 2 changed (answer to the two review findings)
| Review finding | Fix | Proof level |
|---|---|---|
| 1. Auto Hedge can change after the check | Bulk close takes the **same per-account lease Auto Hedge live execution takes** (`_acquire_aster_account_coordination`) **before** the protection check and holds it through order + verification; released in `finally`. Second check right before the order. Post-order detection `protectionChangedDuringClose` shown to the user. | Mitigated, **not fully eliminated** (see §8.1) |
| 2. Missing `ownedLegs` treated as empty | Canonical contract investigated; **proven-none vs unreliable** are now different. Unreliable → HTTP 409 / preview 502, no order. | Offline PASS |
| 3. Integration tests | Real FastAPI + Firestore emulator **NOT RUN** (dependencies missing in sandbox, see §7). Real close-route **source** executed against mocks + a lease model instead. | NOT RUN / substitute |
| 4. Old backend accepts the flag silently | **Confirmed with real pydantic 2.x**: old model accepts and drops `bulk_profit_close`. New code: preview returns `bulkGuardVersion: 1`; new frontend refuses to run without it and stops when a close response lacks `protectionChangedDuringClose`. Rollout/rollback order in §8.4. | Offline PASS |

## 1. Exact cause of the original problem
1. **Build 601** counted Auto Hedge-managed profitable legs that the server excludes ("Close 15 profits" ≠ closable).
2. **PR #783** bulk = sequential calls to the individual close route, which for an Auto Hedge pair moves it to `MANUAL_RELEASE_PENDING` → `RECOVERY` with `rehedgeEnabled=false` — no Auto Hedge filter in frontend, preview or route.
3. Planner bug: `if side == "LONG" and opposite and not linked` let a lone LONG through.
4. Threshold inconsistency (`>= 0.50` legacy vs `> 0.50` new SHORT path).

## 2. New behaviour
- Bulk = **SHORT only**, strictly **> $0.50** (UI + planner), not Auto Hedge-managed, not Focus Airbag. Count on the button = real closable count. 25/50/75/100%. One confirmation modal (count, fraction, Auto Hedge/Airbag note).
- LONG never bulk-closed (no verified hedge-link source); planner rejects a lone LONG.
- Preview endpoint (read-only) removes protected candidates server-side, returns `protectedExcludedCount` and `bulkGuardVersion: 1`; unreliable protection data → 502.
- Execution = existing route `POST /api/exchanges/aster/positions/{symbol}/close` with `bulk_profit_close: true` (no second route/engine). With the flag the route: (1) takes the account lease (busy → 409, nothing placed), (2) re-reads Auto Hedge (strict, fail-closed) + Focus Airbag data live, (3) refuses the manual Auto Hedge release branch, (4) re-checks right before the order, (5) after the order re-checks and reports `protectionChangedDuringClose`.
- Frontend stop/skip rules: "valt onder Auto Hedge"/"Focus Airbag-hedge" → counted as protected skip, loop continues; busy account, unreliable Airbag data, unreadable hedge lock, API error, UNKNOWN, broad contract error, missing guard confirmation → **stop** with visible message; minimum-order skip unchanged; in-flight ref blocks double press; fresh idempotency key per symbol.
- Individual Close (no flag): unchanged — no lease, no guard (tested). Close Long/Short/All unchanged.

## 3. Focus Airbag contract and fail-closed rule
Canonical writers (`aster_strategy2_focus_multi/_live/_v2`): `asterStrategy2/{uid}.ownedLegs` = list of OwnedLeg mappings, each with `symbol`, `side` (LONG|SHORT) and a non-empty string `role` (default `HARVEST`); airbag hedge leg = role `FOCUS_SLOT_AIRBAG:<slotId>`. `focusLiveSlots[].airbag` (dict) marks a slot with an airbag.
| State | Outcome |
|---|---|
| Strategy-2 document does not exist | proven none → allowed |
| document exists, no focus keys (`focusLiveSlots/State, focusCycleState, focusV2State`), no `ownedLegs` | proven none → allowed |
| `ownedLegs` list, all rows well-formed, no airbag role on this leg, no airbag slot for the pair | proven none → allowed |
| airbag role on this leg, or a slot with `airbag` for this pair (both legs protected, conservative) | blocked: protected |
| `ownedLegs` not a list / row not a dict / row without symbol, side or role; focus keys but no `ownedLegs`; `focusLiveSlots` malformed; slot with airbag missing pair/side; document not a dict | **BulkProtectionUnreliable → 409, no order** |
| Firestore read error | exception → fail closed (409/502), no order |
Assumption to review: the "no focus keys → proven none" rule relies on all Focus engines writing `ownedLegs` together with their focus keys (verified in the writers listed above), and on Multi-BB state (`multiBbPositions`) not carrying airbag roles.

## 4. Changed files (vs PR #783 head)
`cloud_api/main.py`, `cloud_api/manual_profit_close_guard.py` (new, pure), `cloud_api/aster_position_loss_auto_hedge_lock.py` (additive `auto_hedge_symbol_managed_strict`), `cloud_api/manual_profit_close_planner.py`, `web/components/aster-recent-trades.tsx`, `cloud_api/test_close_profits_2_1_guard.py` (new), `web/tests/aster-close-profits-2-1-safety.test.mjs` (new), `web/tests/aster-close-profits-short-handler.test.mjs` (one mock line: success payload now carries the guard confirmation).
Patches: `CLOSE_PROFITS_2_1_vs_PR783.patch` (all 2.1), `CLOSE_PROFITS_2_1_ROUND2_vs_bddff04.patch` (only this round), `CLOSE_PROFITS_2_1_vs_BUILD601.patch`.

## 5. Difference versus production build 601
601: counts LONG+SHORT incl. Auto Hedge legs, legacy `profitable-close-preview` + `close-profitable`. 2.1: SHORT-only, > $0.50, Auto Hedge/Airbag excluded in UI, preview and execution (lease + live re-check), percentage choice, one confirmation, per-symbol idempotent calls to the individual route.

## 6. Proven Auto Hedge protection (what is actually proven)
**Proven offline (real route source from `main.py`, mocks + lease model):**
- stale preview, Auto Hedge-managed at execution → 409, 0 orders, lease released.
- Auto Hedge flips between 1st check and the order → caught by the late check, 0 orders.
- Auto Hedge flips during the order → order done, response `protectionChangedDuringClose=true`, intent flagged, frontend warning.
- While the bulk close holds the lease, the Auto Hedge tick model gets `PENDING` (same exclusive lease); after release it can run. Account busy → 409, no order, bulk never steals a held lease.
- Lease released on success, block, unreliable data and order failure (no leak); duplicate idempotency key → 409 before taking the lease.
- Source contract: Auto Hedge live execution really acquires the same lease (`AUTO_HEDGE`/`POSITION_LOSS_EXACT_1_TO_1`, `ACCOUNT_COORDINATION_BUSY`, release in finally); lease before guard, guard before `close_size`/`begin_manual_action`/`execute_aster_leg`.
**Not proven:** the same behaviour with the real Auto Hedge worker, real Firestore transactions and real FastAPI (NOT RUN). The lease is a model in the tests; the Auto Hedge side was verified by source reading only.

## 7. Test results
Env: Python 3.13, Node 22.22, pydantic 2.13.5. Missing: fastapi, firebase_admin, google-cloud-firestore, pytest, hypothesis, websockets; no Firebase emulator / firebase-tools; PyPI and the npm registry unreachable. `httpx` is imported by `aster_gateway` (not used by the tested paths): runs marked *stub* used a 5-line stub on PYTHONPATH.
| Item | Result |
|---|---|
| `test_close_profits_2_1_guard` (backend, 46 tests) | **PASS 46/46 with httpx stub; PASS 44 + SKIP 2 without it** (the 2 real-`ContractRules` tests: 25/50/75/100% quantities, exchange minQty/minNotional) |
| `aster-close-profits-2-1-safety.test.mjs` (27) | PASS 27/27 |
| `aster-close-profits-short-handler.test.mjs` (9, PR's) | PASS 9/9 (one mock line updated) |
| Scenarios: normal SHORT; Auto Hedge SHORT blocked; Auto Hedge LONG with loss untouched; mixed portfolio; Focus Airbag blocked; missing/unreliable protection blocked; unreadable hedge lock blocked; concurrent activation (before order / during order); repeated request; Math.abs on negative qty; 25/50/75/100 + exchange minimums; minimum-order skip; API error; UNKNOWN stops; old backend refused; individual Close unchanged | PASS (offline; route-level via real source + mocks) |
| Real FastAPI app init + Firestore emulator integration (all 8 mandated scenarios) | **NOT RUN** — dependencies/emulator unavailable |
| Real Auto Hedge worker concurrency | **NOT RUN** |
| Live Aster orders | NOT RUN (forbidden) |
| Regression, whole `cloud_api` suite, PR head vs this commit | identical per file; PR head 1990 pass/21 fail/73 import errors → now 2036 pass/21 fail/73 import errors (+46 new). The 21 failures/73 import errors are environmental and identical on the PR head, incl. `test_aster_position_loss_auto_hedge_lock`, `test_aster_close_guard`, `test_aster_hedge_recovery` (need pytest/fastapi) = NOT RUN. Auto Hedge: `test_aster_position_loss_auto_hedge` 19/19, lifecycle 7/7, owner gate 5/5 PASS. 100/107 `test_short_recovery_*` files run, equal to baseline. |
| Regression, web suite | 149/151 files pass (PR head 148/150 + new file); `extreme-spike-settings-route-execution` and `rendered-html` fail identically on the PR head |

## 8. Open risks
1. **Race not fully eliminated.** The lease serializes Auto Hedge's *order execution* with our check+order. But Auto Hedge's `_run_uid` calls `_prepare_lifecycle` (which can write a new pair status, e.g. HEDGING) **before** it tries the lease (code order: `_prepare_lifecycle` ≈ line 566, lease ≈ line 597). A status write in the few-ms window between our last check and the order is therefore still possible; it is detected after the fact (`protectionChangedDuringClose`) but not prevented. Consequence analysis: Auto Hedge cannot place orders inside the window (lease), the bulk path can never run the manual release (→ no RECOVERY / re-hedge OFF from this path), and Auto Hedge reconciles to 1:1 on its next tick — but a protected LONG can be briefly under-hedged by the closed fraction. Fully removing it needs Auto Hedge to take the lease before `_prepare_lifecycle` (change in Auto Hedge code; deliberately not done).
2. Lease TTL is 45 s; a close slower than that loses exclusivity (the post-order check still reports).
3. Everything that is not the Auto Hedge worker and does not take the lease is not serialized (the individual Close button by design; the user PUT `/rehedge` only touches already-managed pairs).
4. **Rollout/rollback (code-enforced where possible).** Roll out: (a) deploy backend with 100% traffic (no traffic split; flag defaults false, nothing else changes), (b) verify `GET /v1/me/aster/positions/manual-profit-close-plan` returns `bulkGuardVersion: 1`, (c) deploy frontend. Roll back: frontend first, then backend. New frontend + old backend = refused (no `bulkGuardVersion`); during a traffic split the preview could hit the new and a close the old revision: the frontend stops after that first response (no confirmation field) but that one order would have run without the guard → hence no traffic split.
5. Real integration (FastAPI + Firestore emulator + real Auto Hedge worker) not run.
6. Focus Airbag rule "no focus keys ⇒ proven none" is an inference from the writers (see §3).
7. Individual Close can still dismantle a hedge deliberately (unchanged by requirement). Threshold: bulk `> 0.5`, Close Long/Short/All `>= 0.5`. LONG bulk off. CSV download per preview (PR #783) unchanged.
8. Security outside this change: repo is public and tracks `gha-creds-*.json` (WIF configs, no private key) — make private, remove, restrict the WIF provider.

## 9. GO / NO-GO
- **Further development / independent review: GO.**
- **Integration into main: NO-GO** until the mandated FastAPI + Firestore-emulator tests run green in an environment that has the dependencies.
- **Production: NO-GO** — also needs a decision on risk 1 (Auto Hedge lease before `_prepare_lifecycle`), the rollout order in 8.4, and a supervised staging check with `ASTER_LIVE_EXECUTION_ENABLED=false` first.

## 10. Independent review (for ChatGPT)
1. `git fetch origin review/close-profits-2-1-safe-20261021`; review `CLOSE_PROFITS_2_1_ROUND2_vs_bddff04.patch` (only this round) and the full `CLOSE_PROFITS_2_1_vs_PR783.patch`.
2. Check in `close_one_aster_position`: lease → live protection check → … → late check → `begin_manual_action` → order → post check; `account_token` released in `finally`; individual path untouched.
3. Verify the Auto Hedge side yourself: `aster_position_loss_auto_hedge_extension.py` `_run_uid` — order of `_prepare_lifecycle` vs lease (risk 8.1), and that `reconcile_auto_hedge` runs under the lease.
4. Verify `manual_profit_close_guard.focus_airbag_protected` against the Strategy-2 writers (§3) for false "proven none".
5. Run: `cd cloud_api && python3 -m unittest test_close_profits_2_1_guard`; `cd web && node --test tests/aster-close-profits-2-1-safety.test.mjs tests/aster-close-profits-short-handler.test.mjs` (Node ≥ 22.13).
6. Run the mandated FastAPI + emulator scenarios where fastapi/firebase_admin/firestore exist (not possible in my sandbox).

🤖 Generated with [Claude Code](https://claude.com/claude-code) · https://claude.ai/code/session_01QXY7Vj7kan5d3RCT7LopcA
