# Close Profits 2.0 — minimal scope (definitive)

Branch `review/close-profits-2-0-minimal-20261021`, based on PR #783 head `f8cd2af5f76c6b240bd49c87deedbbe8622ef4ea`.
The 2.1 work (Auto Hedge worker lease, guards, backend changes) stays isolated on `review/close-profits-2-1-safe-20261021` and is **not** part of this branch.

## Scope (as instructed)
Green button = automation of the manual individual Close: all SHORTs with > $0.50 profit (hedged SHORTs included, as the individual button allows them), one percentage (25/50/75/100), one confirmation, then per SHORT the existing `POST /api/exchanges/aster/positions/{symbol}/close` with `{confirm, side:"SHORT", expected_quantity:<full live quantity>, percentage, idempotency_key}`. Backend computes the partial size. Too-small pre-submit error → skip and continue. Any other error / UNKNOWN outcome → stop (no double close). Focus Airbag hedge legs stay excluded (same as the individual button).

## What was verified in PR #783 (no change needed)
- Backend: **zero changes** on this branch vs PR #783 (individual close route, Auto Hedge status handling, Recovery, planner untouched). Preview planner already keeps a profitable SHORT whose paired LONG is unverified (`test_unverified_link_protects_long_not_short`).
- Frontend sends no extra flag; no Auto Hedge/Recovery logic in the handler.

## The only change (frontend, +10 lines in `web/components/aster-recent-trades.tsx`)
The central confirmation now shows the existing consequence when selected SHORTs are Auto Hedge-managed: "het paar gaat daarna in Recovery, de verkleinde SHORT wordt niet automatisch teruggevuld en re-hedge blijft UIT", and tags those rows "Auto Hedge". Informational only; no route, status or lifecycle change.

## Tests (offline)
| Item | Result |
|---|---|
| new `web/tests/aster-close-profits-scope.test.mjs` (5) + PR `short-handler` (9) + `aster-close-profitable` (5) | PASS 19/19 |
| backend planner/preview/snapshot tests | PASS 12/12 |
| web suite | 149/151 files; the 2 failures (`extreme-spike-settings-route-execution`, `rendered-html`) are pre-existing on the PR head |
| Real backend route with FastAPI/Firestore emulator, live Aster | **NOT RUN** (no environment; no real orders) |

## Consequences to know (unchanged existing behaviour)
Each Auto Hedge-managed SHORT closed this way moves its pair to RECOVERY with re-hedge OFF, exactly as the manual click does. Not a bulk-specific effect, not changed here.

## Open
Concurrency between several sequential closes and an Auto Hedge worker tick is the same as clicking quickly by hand; the 2.1 lease work addresses that separately and is deliberately excluded. Not merged, not deployed, build 601 untouched. GO for review; merge/production NO-GO until a real-environment test.
