# CLOSE PROFITS 2.1 SAFE FIX — Claude handoff (round 3)

Repo `AmarRakhan/tradementor` · PR #783 (draft) · Branch `review/close-profits-2-1-safe-20261021`
**Code commit to review: `bbe12cf9cd5149cc571e6ac3ba01878190e8cfde`** · round 2 code: `320c4c7a460aff1a77c2a07dca84ea8c2e115d50` · round 1 code: `bddff04c3c994d7bb0fe12966f2d301a68fab511` · PR #783 head: `f8cd2af5f76c6b240bd49c87deedbbe8622ef4ea`.
A later commit on the branch only adds this file and the patches. Not merged, not deployed, no Cloud Build, no live orders, build 601 and SHORT Recovery 2.0 untouched. **Auto Hedge code IS modified this round (lease placement + fences only; no strategy, threshold, Recovery-ownership or claim logic changed).**

## 0. Round 3 — what changed and what is (not) proven
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
`cloud_api/main.py`, `cloud_api/aster_position_loss_auto_hedge_extension.py` (**lease before lifecycle, renew, per-order fence**), `cloud_api/aster_position_loss_auto_hedge_lock.py` (additive strict check), `cloud_api/manual_profit_close_guard.py` (new), `cloud_api/manual_profit_close_planner.py`, `web/components/aster-recent-trades.tsx`, `cloud_api/test_close_profits_2_1_guard.py` (new), `web/tests/aster-close-profits-2-1-safety.test.mjs` (new), `web/tests/aster-close-profits-short-handler.test.mjs` (one mock line).
Patches: `CLOSE_PROFITS_2_1_ROUND3_vs_320c4c7.patch` (this round), `CLOSE_PROFITS_2_1_ROUND2_vs_bddff04.patch`, `CLOSE_PROFITS_2_1_vs_PR783.patch` (all), `CLOSE_PROFITS_2_1_vs_BUILD601.patch`.

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
| `test_close_profits_2_1_guard` (68 tests) | **PASS 68/68 with httpx stub; PASS 66 + SKIP 2 without it** (2 real-`ContractRules` tests) |
| web `aster-close-profits-2-1-safety` (28) + PR `short-handler` (9) | PASS 37/37 |
| Whole `cloud_api` suite, PR head vs now | identical per file except the new file: 1990 → 2058 pass (+68), 21 fail / 73 import errors on both (env: pytest/fastapi/...; incl. `test_aster_position_loss_auto_hedge_lock`, `test_aster_close_guard`, `test_aster_hedge_recovery` = NOT RUN). Auto Hedge: `test_aster_position_loss_auto_hedge` 19/19, lifecycle 7/7, owner gate 5/5 PASS after the Auto Hedge change. |
| Web suite | 149/151 files pass; `extreme-spike-settings-route-execution`, `rendered-html` fail identically on the PR head |
| **Firestore emulator + real FastAPI app init: concurrent Auto Hedge/bulk, mutation before send, lease expiry during verification, worker crash/restart, duplicates, missing Airbag state, Recovery/re-hedge untouched, Close Long/Short/All + individual** | **NOT RUN** (offline substitutes above cover the logic of each scenario, not the infrastructure) |
| Live Aster orders | NOT RUN (forbidden) |

## 8. Open risks
1. **Real-infrastructure proof missing** (emulator, FastAPI, real worker). Mocks and in-memory models are not a safety proof.
2. **Behaviour change in Auto Hedge:** when the lease is busy, `_prepare_lifecycle` no longer runs (e.g. PROTECTED_LEG_CLOSED → RECOVERY/CLOSED transitions wait one worker tick); the lease is held longer per run (reads + lifecycle), so other lease users (bulk close, strategy management) see "busy" more often; a run that exceeds 45 s between renewals (renew happens before reconcile and before each order) would still lose exclusivity — the fence then blocks its own order, it does not extend silently.
3. **Not covered by the lease:** the individual Close button (by design), the user `PUT .../rehedge` (touches only already-managed pairs), Auto Hedge reads outside `_run_uid`. `aster_legacy_hedge_scale_extension` and the manual-release helpers do take the lease.
4. **Newly noted: other hedge systems are not part of the bulk guard.** The guard checks Auto Hedge 2.0 pairs and Focus Airbag. Dynamic Hedge (`asterDynamicHedge`, mutually exclusive with Auto Hedge enabling), the portfolio emergency hedge and Short Recovery 2.0 ownership are not checked by the bulk filter; the route still calls `begin_manual_action` for Dynamic Hedge as for any manual close. Needs an owner decision before production.
5. Focus Airbag rule relies on the writer scan (§3); 7 known writers lack `ownedLegs` and are handled fail-closed.
6. Rollout: backend (100% traffic, no split) → verify `bulkGuardVersion: 1` → frontend; roll back frontend first. New frontend + old backend is refused.
7. Individual Close can still dismantle a hedge deliberately (unchanged). Bulk threshold `> 0.5` vs legacy `>= 0.5`. LONG bulk off.
8. Security outside this change: repo public with tracked `gha-creds-*.json` (WIF configs, no private key).

## 9. GO / NO-GO
- **Further development / independent review: GO.**
- **Merge to main: NO-GO** until the emulator + FastAPI integration run green in an environment that has the dependencies (e.g. CI image of the project).
- **Production: NO-GO** — no claim of full safety: only mocks/in-memory models were available.

## 10. Independent review (for ChatGPT)
1. `git fetch origin review/close-profits-2-1-safe-20261021`; read `CLOSE_PROFITS_2_1_ROUND3_vs_320c4c7.patch`.
2. Verify in `aster_position_loss_auto_hedge_extension.py` that no pair-state write or order remains outside the lease: `_run_uid`, `_prepare_lifecycle`, `_sync_pair_views`, `reconcile_auto_hedge`; and that Recovery ownership/claim/Classic-vs-Recovery gating is byte-identical (diff only touches `_client` and the lease block).
3. Verify `_renew_aster_account_coordination` (transaction, no resurrection) and the two fences.
4. Check risk 8.4 (Dynamic Hedge / emergency hedge) and decide.
5. Run: `cd cloud_api && python3 -m unittest test_close_profits_2_1_guard`; `cd web && node --test tests/aster-close-profits-2-1-safety.test.mjs tests/aster-close-profits-short-handler.test.mjs`.
6. Run the mandated emulator scenarios where fastapi/firebase_admin/firestore + emulator exist.

🤖 Generated with [Claude Code](https://claude.com/claude-code) · https://claude.ai/code/session_01QXY7Vj7kan5d3RCT7LopcA
