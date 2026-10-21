# CLOSE PROFITS 2.1 SAFE FIX — Claude handoff (round 4)

Repo `AmarRakhan/tradementor` · PR #783 (draft) · Branch `review/close-profits-2-1-safe-20261021`
**Round-4 code commit to review: `696a3f12293a4c795384a529199231da74e0672c`** · round 3 code `bbe12cf9cd5149cc571e6ac3ba01878190e8cfde` · round 2 `320c4c7a460aff1a77c2a07dca84ea8c2e115d50` · round 1 `bddff04c3c994d7bb0fe12966f2d301a68fab511` · PR #783 head `f8cd2af5f76c6b240bd49c87deedbbe8622ef4ea`.
A later commit only adds this file and the patches. Not merged, not deployed, no Cloud Build/workflow started, no live orders, build 601 untouched. **Round 4 changes no Auto Hedge, Recovery, Dynamic/Emergency Hedge or strategy code and no setting: only the bulk-close guard, its read helpers in `main.py`, one frontend marker, tests, and a test runner.**

## R4. Round 4 — what changed
| Assignment | Result | Status |
|---|---|---|
| 1. Canonical ownership of all systems | Matrix below; guard checks every system server-side, in preview, at first check and in the late re-check right before the order; unreadable/malformed ownership data raises → 409 (`blocked_bulk_unreliable`) / preview 502, no order | Code + offline tests PASS; emulator NOT RUN |
| 2. Protect Short Recovery 2.0 | A SHORT is never bulk-closed when the pair doc carries a Recovery cycle (`state` PARTIAL/FINAL_PENDING, or `ownerSide` + `cycleConfirmed`) or when `shortRecoveryPlan.enabled` and a same-symbol LONG exists. **No canonical Recovery router grants a Close-Profits permission today (Recovery is offline/shadow), so the answer is always "not permitted".** Status flips between preview and execution are caught by the late re-check. | PASS offline |
| 3. Round-3 re-inspection | See §R3 below | Verified |
| 4. Real integration | No suitable offline environment (see §7). Delivered `cloud_api/test_close_profits_2_1_firestore_emulator.py` (real lease transactions + real ownership reads, skips without emulator) and `tools/run_close_profits_2_1_integration.sh` | **NOT RUN** |
| 5. Regressions | §7 | PASS / pre-existing FAIL identical |

### Ownership matrix (who owns a position, canonical store, what the guard reads)
| System | Canonical document / field | Takes account lease | Bulk guard decision |
|---|---|---|---|
| Auto Hedge 2.0 | `asterPositionLossAutoHedge/{uid}/pairs/{SYMBOL}.status` ∈ `AUTO_HEDGE_MANAGED_STATUSES` (strict reader, fail-closed) | yes (round 3, before lifecycle) | block + manual release refused |
| Short Recovery 2.0 – cycle | same pair doc: `state` PARTIAL/FINAL_PENDING, `ownerSide`+`cycleConfirmed` | (via Auto Hedge worker) | block |
| Short Recovery 2.0 – plan | `asterPositionLossAutoHedge/{uid}.shortRecoveryPlan` via canonical `resolve_existing_active_strategy`; non-bool `enabled` → unreliable | – | block SHORT that has a same-symbol LONG while enabled (per-leg ownership is not persisted yet, so not provable → excluded); lone SHORT unaffected |
| Focus Airbag | `asterStrategy2/{uid}.ownedLegs[].role = FOCUS_SLOT_AIRBAG:<slot>` (+ fail-closed focus keys, §3) | yes (Strategy-2 management) | block |
| Dynamic Hedge | `users/{uid}/asterDynamicHedge/control`: `enabled` bool, `ownershipState` | no | account-wide block while enabled or `MANUAL_ACTION_LOCK`; non-bool → unreliable |
| Emergency (portfolio) Hedge | `aster_portfolio_emergency_hedges/{uid}.status` OFF/ARMED/EXECUTING/LOCKED | **no** (own `leaseOwner/leaseUntil`) | block on EXECUTING/LOCKED; unknown status → unreliable |
| Strategy 2 in-flight | `asterStrategy2/{uid}.pendingReopens[]`, `orderQueueState.currentIntent` (the `aster_symbol_ownership` claims) | yes | block that symbol |
| Sniper | `asterSniper/{uid}.activeTrades[]`, `pendingIntent` | yes | block that symbol |
| Individual Close / Close Long/Short/All | – | Close-all yes; individual no | unchanged |

Conservative by design: it can only remove candidates from the bulk list, never add or change an order. A user who runs Dynamic Hedge sees an empty/short bulk list (individual Close still works).

## R3. Round-3 re-inspection (what the code does today)
- Real lease transactions (`@firestore.transactional` get-then-set; acquire fails while `until > now`; renew only for matching token and unexpired; release only for matching token) — logic proven offline on a serialisable in-memory model; **real Firestore transactions NOT RUN**.
- `_run_uid`: lease → client → reads → `_prepare_lifecycle` → renew → reconcile → release (tests on real source). Expired token never authorises an order (renew-or-block in `before_order_submit` for bulk and for each Auto Hedge order). Unknown outcome: one POST, no second POST, 502.
- Other users of the same lease (grep): `aster_legacy_hedge_scale_extension`, Auto Hedge, Strategy-2 management/scheduler, Sniper, Emergency Close-All, bulk close. **Not under the lease:** individual Close (unchanged by design), Emergency Hedge executor (own lease), Dynamic Hedge, user `PUT …/rehedge`. The new Dynamic/Emergency guard therefore reads their documents instead of relying on the lease.
- Legacy route `POST /v1/me/aster/positions/close-profitable` and the Next routes `…/close-profitable`, `…/snapshot-close-profitable` plus `aster-portfolio-snapshot-enhancer.tsx` still exist and are **outside this change** (pre-existing; non-strict Auto Hedge check, no Dynamic/Emergency/Recovery check). See risk 9.

## 0. Round 3 (kept for history) — what changed and what is (not) proven
| Review request | Change | Status |
|---|---|---|
| 1. Close the Auto Hedge race | In `_run_uid` the account lease is now taken **before** `_client`/position reads/`_prepare_lifecycle` (it used to be taken after). All pair-state writes in `_prepare_lifecycle`, `_transition_missing_protected` and `_sync_pair_views` are `if execute`-gated and therefore now run under the same exclusive lease the bulk close holds across check + order. Lease busy → Auto Hedge defers (PENDING) without any read/write/order. | Code + offline tests PASS; real worker/Firestore NOT RUN |
| 2. 45 s TTL | New fencing primitives in `main.py`: `_renew_aster_account_coordination` (extends only while token matches and not expired; **never resurrects** an expired lease) and `_aster_account_coordination_held`. **Bulk close:** `before_order_submit` renews-or-blocks right before every submit (fresh 45 s covers the 15 s POST + one read-only recovery query); lost/taken-over lease → order not sent. After the order a held-check sets `leaseLostDuringClose` (reported, never a second order). **Auto Hedge:** renew before `reconcile_auto_hedge` (else `ACCOUNT_LEASE_LOST`, no orders) and the same renew-or-block fence on every Auto Hedge order. Unknown order status stays fail-closed: one POST, no automatic second order (existing gateway behaviour + route 502). | Code + offline tests PASS |
| 3. Focus Airbag contract | AST scan of **all** writers (see §3). | Verified; scan is a regression test |
| 4. Real integration tests | **NOT RUN** — see §7. Substitutes: real lease functions + real threads + fake clock; real `_run_uid`/route source with mocks. | NOT RUN (emulator) |

## 1. Original cause (unchanged)
Build 601 counted Auto Hedge-managed legs the server excludes; PR #783 bulk used the manual close route (pair → RECOVERY, re-hedge OFF) without any Auto Hedge filter; planner let a lone LONG through; threshold `>=` vs `>` inconsistent.

## 2. Behaviour (cumulative)
Bulk = SHORT only, strictly > $0.50, not Auto Hedge-managed, not Focus Airbag; real closable count; one confirmation. Execution via the existing close route with `bulk_profit_close: true`: (1) account lease, (2) live protection check (Auto Hedge strict fail-closed + Airbag fail-closed), (3) manual Auto Hedge release refused, (4) late re-check, (5) per-order fence, (6) post checks (`protectionChangedDuringClose`, `leaseLostDuringClose`). Frontend: preview must advertise `bulkGuardVersion: 1`; busy/unreliable/unknown/API error stop the run; protected refusal = skip; individual Close and Close Long/Short/All unchanged.

## 3. Focus Airbag canonical contract (verified by scanning every writer)
- `FOCUS_SLOT_AIRBAG:<slot>` is created only in `aster_strategy2_focus_multi.py` (`_airbag_role`); `main.py` only filters/reads/labels it. It is persisted only as `role` of an `ownedLegs` row.
- 25 literal Firestore writes set focus keys (`focusLiveSlots/State, focusCycleState, focusV2State`) **together with** `ownedLegs`. **7 writes set focus keys without `ownedLegs`** (`aster_strategy2_focus_live.py` 243/272/447/462/498/505, `aster_strategy2_focus_v2.py` 662; merge updates). For a document that has focus keys but no `ownedLegs` the guard therefore **blocks** (unreliable) — it never reads that as "no protection".
- "Proven none" (allowed) only when: no Strategy-2 document; or a document with no focus key and no `ownedLegs` (airbag roles cannot exist without `ownedLegs`); or a well-formed `ownedLegs` list without an airbag role/slot for this pair. Any malformed row/list/slot, or a read error → no order.
- The airbag hedge leg cannot appear between check and order because Strategy-2/airbag management (`REALTIME_MANAGEMENT`, `SCHEDULER`) takes the same account lease (asserted in tests).
- Test `FocusAirbagContractScanTests` fails if a new writer of focus state appears that is not on the reviewed list.

## 4. Changed files (vs PR #783 head)
`cloud_api/main.py`, `cloud_api/aster_position_loss_auto_hedge_extension.py` (**lease before lifecycle, renew, per-order fence**), `cloud_api/aster_position_loss_auto_hedge_lock.py` (additive strict check), `cloud_api/manual_profit_close_guard.py` (new; round 4: ownership checks), `cloud_api/test_close_profits_2_1_firestore_emulator.py` + `tools/run_close_profits_2_1_integration.sh` (round 4, NOT RUN), `cloud_api/manual_profit_close_planner.py`, `web/components/aster-recent-trades.tsx`, `cloud_api/test_close_profits_2_1_guard.py` (new), `web/tests/aster-close-profits-2-1-safety.test.mjs` (new), `web/tests/aster-close-profits-short-handler.test.mjs` (one mock line).
Patches: `CLOSE_PROFITS_2_1_ROUND4_vs_662cb70.patch` (this round), `CLOSE_PROFITS_2_1_ROUND3_vs_320c4c7.patch`, `CLOSE_PROFITS_2_1_ROUND2_vs_bddff04.patch`, `CLOSE_PROFITS_2_1_vs_PR783.patch` (all), `CLOSE_PROFITS_2_1_vs_BUILD601.patch`.

## 5. Versus build 601
601: legacy preview + `close-profitable`, LONG+SHORT, Auto Hedge legs counted. 2.1: see §2. Auto Hedge worker differs from 601 in lease placement/fences only (§0).

## 6. What is proven (offline)
- **Real** `_acquire/_release/_renew/_held` source from `main.py` on an in-memory Firestore model (serializable mutex, nested-merge semantics) with a fake clock: 16 concurrent acquirers → exactly one winner; busy at 44 s, expired at 46 s; expired holder cannot renew, cannot resurrect, is fenced after takeover, stale release is a no-op; renew extends beyond TTL; crash without release recovers after TTL; renew vs takeover race never both succeed (20 rounds).
- **Real** `_run_uid` source: order = acquire → `_client` → `_prepare_lifecycle` → renew → `reconcile_auto_hedge` → release; busy → no client/read/write/order; crash in lifecycle → lease released; renew fails → no reconcile; every Auto Hedge order fenced; shadow mode unchanged (no lease, no fence).
- **Real** close-route source: expired lease before the order → no order (502), taken over → no order, expiry during verification → one order + `leaseLostDuringClose`, unknown order status → one submit, no retry, lease released; plus all round-1/2 scenarios (stale preview, Auto Hedge/Airbag blocked, unreliable data, busy account, late flip, individual Close unchanged, idempotency, 25/50/75/100% with real `ContractRules` when httpx is present).
- **Mutation checks:** the new tests fail on the old Auto Hedge source (5/6 fail) and on the route with the fence removed (3 fail).
**Not proven:** behaviour with real Firestore transactions/emulator, real FastAPI, real Auto Hedge worker threads, real exchange.

## 7. Test results and environment
Sandbox (cloud container, no production access): Python 3.13, Node 22.22, pydantic 2.13.5, starlette, anyio. **Search for a pre-provisioned test environment:** no fastapi, firebase_admin, google-cloud-firestore, pytest, firebase-tools anywhere on disk; `gcloud emulators firestore` exists but its component is not installed and `gcloud components install` is refused by the egress proxy (403 on dl.google.com); PyPI/npm/maven unreachable. Not circumvented. `httpx` is imported by `aster_gateway`: runs marked *stub* used a 5-line stub.
| Item | Result |
|---|---|
| `test_close_profits_2_1_guard` (85 tests; +17 round 4) | **PASS 85/85 with httpx stub; 83 + 2 SKIP without it** (2 real-`ContractRules` tests) |
| `test_close_profits_2_1_firestore_emulator` (6 tests) | **SKIP 6/6 here (no emulator)** → NOT RUN |
| Mutation checks round 4 | removing each of the 5 new reason functions makes tests fail (5/5 killed) |
| web `aster-close-profits-2-1-safety` (30) + PR `short-handler` (9) | PASS 39/39 |
| Whole `cloud_api` suite, PR head vs now | identical per file except the new file: 1990 → 2075 pass (+85), 21 fail / 73 import errors on both (env: pytest/fastapi/...; incl. `test_aster_position_loss_auto_hedge_lock`, `test_aster_close_guard`, `test_aster_hedge_recovery` = NOT RUN). Auto Hedge: `test_aster_position_loss_auto_hedge` 19/19, lifecycle 7/7, owner gate 5/5 PASS after the Auto Hedge change. |
| Web suite | 149/151 files pass; `extreme-spike-settings-route-execution`, `rendered-html` fail identically on the PR head |
| **Firestore emulator + real FastAPI app init: concurrent Auto Hedge/bulk, mutation before send, lease expiry during verification, worker crash/restart, duplicates, missing Airbag state, Recovery/re-hedge untouched, Close Long/Short/All + individual** | **NOT RUN** (offline substitutes above cover the logic of each scenario, not the infrastructure) |
| Live Aster orders | NOT RUN (forbidden) |

## 8. Open risks
1. **Real-infrastructure proof missing** (emulator, FastAPI, real worker). Mocks and in-memory models are not a safety proof.
2. **Behaviour change in Auto Hedge:** when the lease is busy, `_prepare_lifecycle` no longer runs (e.g. PROTECTED_LEG_CLOSED → RECOVERY/CLOSED transitions wait one worker tick); the lease is held longer per run (reads + lifecycle), so other lease users (bulk close, strategy management) see "busy" more often; a run that exceeds 45 s between renewals (renew happens before reconcile and before each order) would still lose exclusivity — the fence then blocks its own order, it does not extend silently.
3. **Not covered by the lease:** the individual Close button (by design), the user `PUT .../rehedge` (touches only already-managed pairs), Auto Hedge reads outside `_run_uid`. `aster_legacy_hedge_scale_extension` and the manual-release helpers do take the lease.
4. **Ownership guard is conservative and not proven against real data:** Recovery per-leg ownership is not persisted yet, so "plan enabled + same-symbol LONG" excludes SHORTs that might not be Recovery-owned (fewer bulk closes, never a wrong one). Emergency Hedge and Dynamic Hedge are read, not locked: a change in the microseconds between the late re-check and the order is not excluded (same residual as before for non-lease systems).
5. Focus Airbag rule relies on the writer scan (§3); 7 known writers lack `ownedLegs` and are handled fail-closed.
6. Rollout: backend (100% traffic, no split) → verify `bulkGuardVersion: 1` → frontend; roll back frontend first. New frontend + old backend is refused.
7. Individual Close can still dismantle a hedge deliberately (unchanged). Bulk threshold `> 0.5` vs legacy `>= 0.5`. LONG bulk off.
9. **Legacy `close-profitable` backend route / Next routes / `aster-portfolio-snapshot-enhancer.tsx` are not covered by this guard.** If any live UI still calls them they can still sell Dynamic/Emergency/Recovery-owned legs. Owner decision: route them through the same guard or remove before production.
10. Security outside this change: repo public with tracked `gha-creds-*.json` (WIF configs, no private key).

## 9. GO / NO-GO
- **Further development / independent review: GO.**
- **Merge to main: NO-GO** until the emulator + FastAPI integration run green in an environment that has the dependencies (e.g. CI image of the project).
- **Review of round 4: GO.**
- **Production: NO-GO** — no claim of full safety: only mocks/in-memory models were available.

## 10. Independent review (for ChatGPT)
1. `git fetch origin review/close-profits-2-1-safe-20261021`; read `CLOSE_PROFITS_2_1_ROUND4_vs_662cb70.patch`.
2. Verify in `aster_position_loss_auto_hedge_extension.py` that no pair-state write or order remains outside the lease: `_run_uid`, `_prepare_lifecycle`, `_sync_pair_views`, `reconcile_auto_hedge`; and that Recovery ownership/claim/Classic-vs-Recovery gating is byte-identical (diff only touches `_client` and the lease block).
3. Verify `_renew_aster_account_coordination` (transaction, no resurrection) and the two fences.
4. Check the ownership matrix above against the code of each system (document names, status values) and risk 9.
5. Run: `cd cloud_api && python3 -m unittest test_close_profits_2_1_guard`; `cd web && node --test tests/aster-close-profits-2-1-safety.test.mjs tests/aster-close-profits-short-handler.test.mjs`.
6. Run `tools/run_close_profits_2_1_integration.sh` where network, Java 21 and the dependencies exist (CI image or dev machine; uses only the emulator + mocks; CI workflows were NOT started by me).

🤖 Generated with [Claude Code](https://claude.com/claude-code) · https://claude.ai/code/session_01QXY7Vj7kan5d3RCT7LopcA
