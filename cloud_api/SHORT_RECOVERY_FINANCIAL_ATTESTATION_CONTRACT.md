# SHORT Recovery 2.0 — Financial Attestation Contract (offline design)

Status: **EXTERNAL DEPENDENCY / NO-GO**. No live orders; no authority granted by this document.
Branch baseline: `b1e39add`. Scope: a single canonical Recovery SHORT-CLOSE order and a separate active hedge cycle.

## Independent evidence requirements

1. **Identity**: account, symbol, original hedge cycle ID, canonical client order ID, exchange order ID and exact step (1–4) are immutable and cross-matched. Each step refers to fixed initial-cycle anchors −5%, −10%, −15%, −20%, not compounded prices.
2. **Order terminality**: two stable independent `query_order` reads return `FILLED`; executed quantity equals exactly the sum of distinct, paginated `user_trades` fills for that order, accounting for all pages. Partial, NEW, canceled-with-fills, UNKNOWN and SUBMITTING are *not* financially terminal.
3. **Execution economics**: every exchange fill has stable execution ID, quantity, realized PnL and actual commission. Two reads must agree. Existing ledger bookings must agree without rebooking an execution ID.
4. **Funding completeness**: an independent source must attest *complete account-wide* funding events covering the full hedge ownership/exposure interval, including stable pagination for tied timestamps, account identity, source version/watermark and a closed completeness window. An empty result alone never proves zero funding. The current Aster `/fapi/v3/income` bounded, time-only pagination does not meet this.
5. **Funding attribution**: the design must not allocate funding to a single SHORT order without independent transaction-to-position/cycle evidence. A conservative account-wide **loss floor** may instead charge *all negative funding* within an independently attested complete account coverage window, ignore positive funding and prevent reuse of these events in subsequent cycles. This can support only a net-profit lower-bound decision, **not** a claim of per-order funding accounting.
6. **No double consumption**: immutable set of `tranId` and distinct execution IDs must be stored with cycle/account and financial window ownership in canonical Firestore claims. Overlapping settlement windows must be refused or handled by an independently proven disjoint partition, inside a single transaction.
7. **Atomic authorization**: the same Firestore transaction must read current control (enabled, no emergency stop or Close All), previous terminal order claim, financial attestation ownership and coordination fence; then CAS-reserve the next canonical SHORT-CLOSE claim. Previous claim remains immutable. No second router, fallback, or automatic retry from SUBMITTING/UNKNOWN.
8. **Restart and concurrency**: stale leases, mismatched ownership, duplicate fills, drifted snapshots, partial readback, late fills and either concurrent ordering must fail closed. Rehedge has a separate new-cycle SHORT-OPEN claim only after final exchange inventory/readback and financial gates.
9. **Non-financial order terminal** can be recorded while the hedge cycle remains active and 75/50/25% SHORT inventory remains; it never grants next-step submit rights.

## Source feasibility and external dependency

Aster `query_order` and `user_trades` can establish order and execution identity/economics. Aster `income_history` exposes symbol/type/time-bounded rows without a documented transaction-complete stable cursor and without a verifiable order/cycle ownership relation. Two identical reads demonstrate stability, **not completeness**. Caller-injected `complete`, `independentlyVerified`, `financialVerified` or invented zero funding cannot close this gap.

**Required external input before implementation may authorize step 2–4**: a verifiable complete account income ledger export/API with watermark, stable pagination and scope guarantees, or independently auditable reconciliation of account cashflow/equity changes that bounds *all* funding charges for the full exposure window, with non-overlapping cycle attribution. Verify using offline fixtures and actual documented schemas before enabling anything. No such source is established in this branch.

## Acceptance / GO criteria

- All four 25% CLOSE orders at fixed anchors execute once, each independently confirmed, financially reconciled, and handed off atomically; original hedge cycle remains active until intended end.
- Both concurrent schedules, crash/restart, stale lease, emergency stop, Close All, partial/late fills, UNKNOWN/SUBMITTING, pagination ambiguity, income replay and incomplete/changed readbacks proven against real Firestore emulator.
- No fake financial evidence, second order router, duplicate income/fill consumption or live order path.
- Entire Recovery/Aster test suite and emulator tests PASS; otherwise **NO-GO**, no commit/push.

## Current observed evidence

Latest preceding real emulator baseline: **912 PASS / 1 FAIL**, 17 subtests PASS; failing `FourStepRunUidCycle.test_all_four_run_uid_reductions_confirmed_before_next_step`. Rehedge new-cycle mock end-to-end PASS. This document does not resolve the funding proof gap and does not change runtime authorization.

## External source audit — 2026-10-19 CEST (bouwronde 50)

Reviewed official public evidence:
- Aster Futures V3 Account & Trading: https://asterdex.github.io/aster-api-website/futures-v3/account%26trades/
  - `GET /fapi/v3/userTrades` supports `orderId` and `fromId` for fill evidence; `GET /fapi/v3/income` accepts symbol/type/start/end/limit but documents no lossless cursor/watermark for same-timestamp funding records.
  - `GET /fapi/v3/balance` is a balance snapshot, not proof that all intermediate income events were exported.
- Aster V1 Futures account docs: https://asterdex.github.io/aster-api-website/futures/account%26trades/
  - Legacy income history is also bounded by timestamps and limit; not an independent complete ledger export.
- Aster Spot transaction history: https://asterdex.github.io/aster-api-website/spot/spot-account-and-trading-api/
  - Covers spot-side transactions and transfers, not a guaranteed complete Futures FUNDING_FEE stream.
- Aster Support Center: https://docs.asterdex.com/trading/spot/support-center
  - Mentions reporting issues via Discord ticket; does not provide documented audit-grade Futures account statement format or completeness semantics.

**No qualifying official download/export or authoritative completeness attestation was established by this audit.** Absence of documented evidence is not proof that no private/manual export exists.

Aster must provide and document:
1. A complete account-identified, closed-period Futures ledger/statement of all FUNDING_FEE events across relevant assets/positions with immutable transaction IDs, exact timestamps, source watermark and reconciliation to account opening/closing balances.
2. Lossless pagination or signed complete download, including more than 1000 records and identical-timestamp ties; independently verifiable reconciliation totals/counts.
3. A way to reconcile all transfers, realized PnL, fees, rebates, funding and other balance movements without double-counting, and to allocate any account-level conservative loss floor to disjoint non-overlapping ownership periods.
4. Reproducible offline verification vectors demonstrating missing row, duplicate, same-time overflow, snapshot drift, partial fill, restart, concurrent claim handoff and stale lease failure.

**Gate remains NO-GO**: no authoritative source currently meets these requirements. No runtime permission, assumed zero funding, caller-attested proof, live orders or commit/push from this audit. Last proven full emulator baseline 912 PASS / 1 FAIL with 17 subtests PASS; NOT RUN this audit.

## Official Futures V3 schema recheck — 2026-10-19

Verified source: https://asterdex.github.io/aster-api-website/futures-v3/account%26trades/ (`GET /fapi/v3/income`, `GET /fapi/v3/userTrades`). Futures income documents filters `symbol`, `incomeType`, `startTime`, `endTime`, `limit` (maximum 1000), but no cursor/complete export/closed-period watermark. The specification says `tranId` is unique **within the same `incomeType` for one user**: deduplication must therefore use at least `(account, incomeType, tranId)`, and must not mistake the identifier for an across-types globally unique event ID. `tradeId`, when present, is not a verified cycle-funding allocation. `userTrades` supports order-filtered execution evidence separately and cannot prove funding-history completeness. No publicly documented qualifying complete Futures account statement or support-issued attest was established; provider confirmation/export with complete event count, lossless pagination or signed snapshot, balance movement reconciliation and non-overlapping funding ownership remains required. **NO-GO unchanged.**

## Newly confirmed official export availability — 2026-10-19

Official Aster product release notes: https://docs.asterdex.com/trading (Product releases, weeks starting 7 July 2025 and 28 April 2025) explicitly state that Aster Perpetual **transaction history is exportable** and that **downloaded funding history files** received formatting improvements. This supersedes any previous suggestion that existence of Perpetual download functionality was unconfirmed. **Export availability is confirmed; export completeness is NOT confirmed.** The notes do not document field schema, full historical retention, pagination boundary, same-timestamp guarantees, immutable source watermark, account-level total/control count, or the reconciliation formula to opening/closing balances. No offline import can authorize financial settlement until a sample export and official coverage guarantee are obtained and inspected. Obtain representative redacted Futures transaction-history and funding-history downloads, including account scope, assets, start/end and statement generation time. Test duplicate (account,incomeType,tranId), missing rows, overlapping periods, funding drift and balance reconciliation before coding permission for order settlement. Support request: ask Aster to confirm whether each export is exhaustive over the selected closed time period, whether all FUNDING_FEE and other balance movements are included, which maximum dates/row limits apply, and how omissions can be detected independently. Existing NO-GO remains.

## Export UI, format and coverage verification — 2026-10-19 11:42 CEST

Official Aster Product releases (https://docs.asterdex.com/trading) confirm that Aster Perpetual transaction history became exportable in the week starting 2025-07-07, and downloaded funding history formatting was improved in the week starting 2025-04-21. These statements confirm **export existence only**. Public documentation inspected does **not** establish: exact button/menu location, CSV/XLSX/JSON file format and field schema, oldest available date/retention window, selectable maximum date range, row/export limit, whether the download is complete beyond 1,000 rows or with identical timestamps, immutable export ID/watermark, or any accounting reconciliation to balance history.

Before authorizing an offline importer, require a redacted *real* Perpetual transaction history export and funding history download for an identified bounded interval, together with opening/closing Futures balance and all transfer/fee/PnL entries; independently compare event counts and source identifiers. Ask Aster Support in writing for (a) guaranteed completeness of all funding events in exported period and account, including same-timestamp ties; (b) maximum historical date and row limits/truncation behavior; (c) supported format/schema and source IDs; (d) how account balance changes reconcile to exported records; (e) whether the export contains all assets and funding transaction types. If any remain unproven, **NO-GO**. Do not infer account-specific paid funding from public funding-rate datasets or CCXT wrappers around the same income endpoint. No runtime changes or new tests warranted until evidence arrives.
