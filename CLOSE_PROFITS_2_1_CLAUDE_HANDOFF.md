# CLOSE PROFITS 2.1 SAFE FIX — Claude handoff

Repo: `AmarRakhan/tradementor` · PR #783 (draft) · Branch: `review/close-profits-2-1-safe-20261021`
**Code commit (what to review): `bddff04c3c994d7bb0fe12966f2d301a68fab511`** (parent `f8cd2af5f76c6b240bd49c87deedbbe8622ef4ea` = PR #783 head).
A later commit on the same branch only adds this file and the two patch files (a file cannot contain its own commit SHA).
Not merged, not deployed, no Cloud Build, no live orders, production build 601 untouched, SHORT Recovery 2.0 untouched.

## 1. Exact cause of the original problem
1. **Build 601** green button counted every profitable LONG+SHORT from the legacy preview (`profitCandidates`, `>= 0.5`), including Auto Hedge-managed legs. The server (`_exclude_auto_hedge_managed_profit_candidates`) removes those, so the number on the button was not the number that can be closed ("Close 15 profits" ≠ closable).
2. **PR #783** replaced this by sequential calls to the individual close route. That route is built for a *manual* close: closing any leg of an Auto Hedge pair (even 25%) moves the pair to `MANUAL_RELEASE_PENDING` → `RECOVERY` with `rehedgeEnabled=false`. PR #783 had no Auto Hedge filter in the frontend, none in the preview, and none in the route for bulk use. A bulk press could therefore dismantle hedges and silently switch re-hedge off.
3. Planner bug in PR #783: `if side == "LONG" and opposite and not linked` — a LONG without an opposite row skipped the hedge check and could be selected.
4. Threshold inconsistency: legacy selector `>= 0.50`, new SHORT path `> 0.50`.

## 2. New behaviour
- Bulk button = **SHORT only**, strictly **> $0.50** (same bound in frontend and planner), **not** Auto Hedge-managed (`positionLossAutoHedge`), **not** Focus Airbag hedge. Button count = real closable count. Percentages 25/50/75/100 unchanged.
- LONG is never part of the bulk (no verified hedge-link source exists; `hedge_links={}`); planner now also rejects a lone LONG (`long_requires_verified_hedge_link`).
- Preview endpoint removes protected candidates server-side and returns `protectedExcludedCount`; the confirmation modal says Auto Hedge/Airbag are not closed; preview message shows how many were protected.
- **Server-side re-check right before every close**: the frontend sends `bulk_profit_close: true` on the *existing* individual route `POST /api/exchanges/aster/positions/{symbol}/close` (no second route/engine). When set, the route (after the live position/quantity/mark checks, before any state change or order) re-reads Auto Hedge state (**strict, fail-closed**), the Focus Airbag role and the side. Refusal = HTTP 409, intent `blocked_bulk_protected`, no order. Unreadable/missing hedge state → `AutoHedgeCloseBlocked` → 409 / run stops.
- Frontend: refusal "valt onder Auto Hedge"/"Focus Airbag-hedge" is counted as "beschermd niet aangeraakt" and the loop continues; any other error (API error, UNKNOWN, hedge state unreadable, broad contract error) **stops** the run with a visible message; the minimum-order skip is unchanged; the in-flight ref blocks double presses; each symbol gets a fresh idempotency key.
- Individual Close button/route behaviour without the flag is unchanged (tested). Close Long/Short/All unchanged (generic `>= 0.5` kept).

## 3. Changed files (vs PR #783 head)
| File | Change |
|---|---|
| `cloud_api/main.py` | request flag `bulk_profit_close`; guard in `close_one_aster_position`; preview filters protected; imports |
| `cloud_api/manual_profit_close_guard.py` (new, 28 lines, pure) | `bulk_profit_close_block_reason` |
| `cloud_api/aster_position_loss_auto_hedge_lock.py` | additive `auto_hedge_symbol_managed_strict` (existing functions untouched) |
| `cloud_api/manual_profit_close_planner.py` | lone-LONG fix |
| `web/components/aster-recent-trades.tsx` | candidate filter, bulk flag, protected handling, texts |
| `cloud_api/test_close_profits_2_1_guard.py` (new) | 28 tests |
| `web/tests/aster-close-profits-2-1-safety.test.mjs` (new) | 23 tests |

Patches: `CLOSE_PROFITS_2_1_vs_PR783.patch` (exact 2.1 changes), `CLOSE_PROFITS_2_1_vs_BUILD601.patch` (whole PR + 2.1 vs `e035431`).

## 4. Commit / branch
Branch `review/close-profits-2-1-safe-20261021`, code commit `bddff04c3c994d7bb0fe12966f2d301a68fab511`.

## 5. Difference versus production build 601
Build 601: counts LONG+SHORT incl. Auto Hedge legs, uses legacy `profitable-close-preview` + `close-profitable`. 2.1: SHORT-only, > $0.50, Auto Hedge/Airbag excluded in UI, preview and (re-checked) at execution, percentage choice, single confirmation, per-symbol idempotent calls to the individual route. See `CLOSE_PROFITS_2_1_vs_BUILD601.patch` (14 files, +1166/−39, includes PR #783's own files).

## 6. Proven Auto Hedge protection (offline)
- `test_auto_hedge_managed_blocked_before_any_order_with_stale_snapshot`: the **real route source** (ast-extracted from main.py, dependencies mocked) with a stale preview (symbol managed only at execution time) → 409, **0 orders**, intent `blocked_bulk_protected`.
- Focus Airbag leg → blocked, 0 orders. Unreadable hedge reader → blocked, 0 orders. No reader configured / garbage reader / exception → strict lock raises (the legacy helper returns "not managed" in these cases — proven in `test_missing_reader_fails_closed`).
- Every status (HEDGED, HEDGING, RECOVERY, REHEDGE_ARMED, DISABLED, unknown) → managed; `''`/`CLOSED` → free.
- Source-order contract: guard runs before `close_size`, `_begin_position_loss_auto_hedge_manual_release`, `begin_manual_action`, `execute_aster_leg`; preview has no order calls.
- Without the flag the guard is not consulted (individual Close unchanged).
**Not proven**: behaviour against real Firestore / real FastAPI (see §8).

## 7. Test results
Commands: `cd cloud_api && python3 -m unittest <module>`, `cd web && node --test tests/<file>`. No pytest/PyPI in the sandbox; for `httpx` (imported by `aster_gateway`, not used by the tested paths) a 5-line stub on PYTHONPATH was used for the suite runs below — flagged here.

| Scenario | Result |
|---|---|
| Normal profitable SHORT selected (UI + planner) | PASS |
| Normal profitable LONG "per chosen control" | PASS (by design **not** a bulk candidate; Close Long/Short/All unchanged — source test) |
| Auto Hedge SHORT with profit excluded (UI, preview, route) | PASS |
| Auto Hedge LONG with loss untouched | PASS |
| Mixed portfolio | PASS (UI filter + planner) |
| Auto Hedge status changes preview→execution | PASS (route test) |
| Missing/unreliable hedge status fails closed | PASS (strict lock + route) |
| Negative SHORT quantity / Math.abs | PASS (planner + preview handler) |
| 25/50/75/100% quantities | PASS (planner, handler); invalid % rejected PASS |
| Contract validation broad error stops | PASS (PR test, still green) |
| Minimum order not achievable skipped with reason | PASS (planner reason + handler skip) |
| API error visible, no false success | PASS |
| UNKNOWN stops, no blind re-order | PASS |
| Repeated press, no double order | PASS (UI in-flight guard; route duplicate idempotency key → 409, 0 orders) |
| Threshold `> 0.50` consistent | PASS (0.50 excluded, 0.51 included, UI + planner) |
| Firestore emulator / real FastAPI route integration | NOT RUN (main.py not importable offline: firebase_admin/fastapi etc. unavailable; no emulator) |
| Live Aster orders | NOT RUN (forbidden) |

Suites: new backend **28/28 PASS**; new web **23/23 PASS**; PR's handler tests **16/16 PASS**; planner 9/9, snapshot 3/3, preview-contract 2/2, profit_close 13/13 + 8/8, manual_close_contract 4/4, auto_hedge 19/19, lifecycle_contract 7/7, owner_gate 5/5, close_all 2/2 (all PASS).
Regression comparison PR-head vs 2.1: whole `cloud_api` suite **identical per file** (before 1990 pass / 21 fail / 73 import errors; after 2018 pass (+28 new) / 21 fail / 73 import errors). The 21 failures and 73 import errors exist unchanged on the PR head (missing pytest, fastapi, websockets, hypothesis, google libs; mexc/gateway tests) = **NOT RUN / pre-existing**, incl. `test_aster_position_loss_auto_hedge_lock`, `test_aster_close_guard`, `test_aster_hedge_recovery`. 100 of 107 `test_short_recovery_*` files ran green-equal to baseline. Web: 149/151 files pass; `extreme-spike-settings-route-execution` and `rendered-html` fail identically on the PR head.

## 8. Open risks
1. **Deploy order**: backend first. An old backend silently ignores `bulk_profit_close` (pydantic default) → new frontend against old backend has only the UI filter.
2. Check-then-act race: Auto Hedge could change a pair between the guard and the order (small window; the bulk path does not take the account coordination lock). The existing `require_auto_hedge_close_allowed` still runs afterwards.
3. Focus Airbag detection on the server relies on `asterStrategy2` `ownedLegs` roles; a missing doc counts as "no airbag legs" (read errors fail closed, absence does not).
4. Real FastAPI + Firestore integration not run (see §7). Route test executes the real function source but with mocks.
5. The individual Close button still lets a user dismantle a hedge deliberately (unchanged by requirement).
6. Threshold: Close Long/Short/All keep `>= 0.5`; the bulk button uses `> 0.5`; a position at exactly $0.50 counts for the former only.
7. LONG profit-taking via bulk is intentionally off until a verified hedge-link source exists; hedged SHORTs get a later controlled flow.
8. PR #783 still downloads a CSV on every preview (unchanged).
9. **Security (outside this change)**: the repo is public and tracks `gha-creds-*.json` (Workload Identity Federation configs, no private key). Make the repo private, remove them from the tree/history and restrict the WIF provider to that repo/branch.

## 9. GO / NO-GO
- **Integration into the review branch / independent ChatGPT review: GO.**
- **Production: NO-GO** until risks 1–4 are closed: real integration test (emulator or staging with ASTER_LIVE_EXECUTION_ENABLED=false), backend-before-frontend deploy plan, and a supervised staging check on a controlled account.

## 10. Independent review (for ChatGPT)
1. `git fetch origin review/close-profits-2-1-safe-20261021`; review `git diff f8cd2af bddff04c3c994d7bb0fe12966f2d301a68fab511` (= `CLOSE_PROFITS_2_1_vs_PR783.patch`).
2. Check the guard position in `close_one_aster_position`: after live position/quantity/mark checks, before `close_size`/`_begin_position_loss_auto_hedge_manual_release`/`execute_aster_leg`; verify the guard is skipped when `bulk_profit_close` is false.
3. Verify `auto_hedge_symbol_managed_strict` fails closed for no reader / exception / non-dict; compare with legacy `current_lock`.
4. Verify the `shortProfitCandidates` filter and the 409 message regex in `closeProfits` match the backend strings in `manual_profit_close_guard.py`.
5. Run: `cd cloud_api && python3 -m unittest test_close_profits_2_1_guard` and `cd web && node --test tests/aster-close-profits-2-1-safety.test.mjs tests/aster-close-profits-short-handler.test.mjs` (Node ≥ 22.13 for `stripTypeScriptTypes`).
6. Try to break it: Auto Hedge status flip after preview, reader outage, LONG with unverified hedge, 0.50 exactly, double click.

🤖 Generated with [Claude Code](https://claude.com/claude-code) · https://claude.ai/code/session_01QXY7Vj7kan5d3RCT7LopcA
