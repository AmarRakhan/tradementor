# SHORT Recovery Plan 2.0 — rollback contract findings (bouwstop 21)

Source: protected baseline `amar-crypto-bot-2026-cloud` at `0eb6a58cdaa40b2f327686f831056c6ba7cc9621`.

## Confirmed legacy behavior
- `aster_position_loss_auto_hedge._build_action` computes `delta = protected_qty - effective_hedge_qty`; positive delta becomes OPEN, not HOLD. Thus an intentional 75%-SHORT becomes a top-up back to 100% if the old reconciler runs.
- `aster_position_loss_auto_hedge_extension._prepare_lifecycle` keeps ACTIVE pairs in the reconciliation owner mapping.
- Auto Hedge persists per-account settings in `asterPositionLossAutoHedge/{uid}` and per-symbol pairs under `pairs/{symbol}`. This is symbol-level, not proof of distinct position-per-zone ownership.
- `aster_profit_close.py` includes exposure helpers, but this is not proof that closed hedge-cycle realized PnL and fees are included in LONG TP.

## Rollback invariant (not yet satisfied)
**A rollback to build 601 with an active partially reduced SHORT cannot preserve intended partial exposure automatically.** Old exact-1:1 reconciliation can re-open the missing SHORT. This can consume margin and undo strategy intent. Prior to any eventual production activation, prove one of:
1. Force all new Recovery Plan cycles to a safely reconciled 1:1 state before rollback, with confirmed exchange fills, explicit authorization and account-level verification; or
2. A genuinely backward-compatible protection guard retained independently of the reverting application code (not presently proven).
A mere featureflag OFF or old code ignoring optional Firestore fields is insufficient to preserve partial hedge behavior.

## Scope safeguards
- This branch contains only pure arithmetic and tests: NO order execution, API routes, Firestore mutations, Cloud Build, or deployment.
- `decision` is advisory: it does not submit or authorize orders, and `REHEDGE_READY` alone is insufficient without an independently confirmed TP check and exchange reconciliation.
- `cycle_net_pnl` assumes funding provided with a signed PnL convention. Required accounting source, event IDs, and idempotent attribution remain unresolved.
- The existing pair document is keyed by symbol: multi-zone multiple LONGs in one symbol require explicit ownership analysis before implementing trade-level cycles.

## Next implementation gates
1. Prove exchange-truth ownership per LONG / SHORT and canonical profit event ledger.
2. Model partial-close fill states and live-setting changes without duplicate orders.
3. Define reversible lifecycle migrations and failure behavior.
4. Test whole rollback playbook without real orders, and obtain a separate GO for deployment.
