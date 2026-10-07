# Aster Single Source of Truth · Architecture Contract v1

Status: Build 571 migration
Scope: read-only account data, presentation data and state ownership
Trading behavior: unchanged

## Non-negotiable rule

For every meaningful account value there is exactly one canonical owner and one canonical source. Every other representation is read-only derived from that source. Browser state may store UI preferences, but may never create financial, trading, risk, position, strategy or historical truth.

Missing canonical data must fail visible as unavailable/stale. It must not be reconstructed from DOM text, localStorage, sessionStorage, stale component state or a different endpoint.

## Runtime flow

Aster exchange/account APIs
→ server exchange normalization
→ canonical persisted account/runtime state
→ canonical server contract
→ API response
→ formatting/rendering only in the browser

Portfolio history:
Aster exchange-confirmed equity
→ server OHLC persistence
→ one server daily-range helper
→ both accountTruth and Portfolio Koers

Strategy:
Strategy-2 runtime
→ persisted Strategy-2 state
→ aster_strategy2_public
→ accountTruth.strategy
→ UI

No browser write participates in this chain.

## Data ownership matrix

| Field / state family | Canonical owner | Canonical source | Persistence | Browser API contract | Consumers | Legacy duplicate | Build 571 status |
|---|---|---|---|---|---|---|---|
| Equity | `cloud_api.aster_status` | Aster account_information + position_risk | `asterAutomation/{uid}.accountSnapshot` | `/api/exchanges/aster -> accountTruth.account.equity` | Header, Snapshot, risk UI | local Aster snapshot, realtime browser reconstruction, DOM text | REPLACED |
| Wallet balance | `cloud_api.aster_status` | Aster account_information | accountSnapshot | accountTruth.account.walletBalance | account cards | local Aster snapshot | REPLACED |
| Available balance | `cloud_api.aster_status` | Aster account_information | accountSnapshot | accountTruth.account.availableBalance | Snapshot, risk | local Aster snapshot / DOM | REPLACED |
| Active trade capital | `cloud_api.aster_status` | normalized server snapshot | accountSnapshot | accountTruth.account.activeTradeCapital | Snapshot | DOM scrape | REPLACED |
| Open PnL | `cloud_api.aster_status` | Aster account/position truth | accountSnapshot | accountTruth.account.unrealizedPnl | account UI | realtime browser formula | REPLACED |
| Maintenance / liquidation | `cloud_api.aster_status` | Aster account + server risk normalization | accountSnapshot | accountTruth.account.* | Snapshot, risk UI | DOM scrape / component fallback | REPLACED for snapshot |
| Open positions | `cloud_api.aster_status` | Aster position_risk | accountSnapshot.positions | accountTruth.positions | Positions, Snapshot, Advisor | browser snapshot cache | REPLACED |
| LONG/SHORT counts | accountTruth builder | canonical position rows | none extra | accountTruth.positions.longCount/shortCount | Snapshot | DOM slot parsing | REPLACED |
| DCA count shown in Snapshot | accountTruth builder | server-owned position dcaCount | Strategy-2 + account snapshot | accountTruth.strategy.summary.dcaCount | Snapshot | DOM active-trades summary parsing | REPLACED |
| Strategy settings | `aster_strategy2_public` | Strategy-2 settings document | `asterStrategy2/{uid}` | accountTruth.strategy.settings | Configurator, zone UI | retained configurator copies | CANONICAL READ CONTRACT; legacy UI cleanup staged |
| DCA runtime state | Strategy-2 runtime | persisted runtime state | asterStrategy2 | accountTruth.strategy.runtimeTruth / strategy2 | Position details, scanner | component-derived state | CANONICAL SERVER |
| TP runtime state | Strategy-2 runtime | persisted ownership/runtime evidence | asterStrategy2 | strategy2 position contracts | Position details, markers | legacy presentation helpers | CANONICAL SERVER |
| Hedge / recovery state | dedicated server runtime owner | persisted hedge state | hedge collections / Strategy-2 | server APIs only | Hedge UI | none may be browser-owned | KEEP SERVER-OWNED |
| Zone state | Strategy-2 / zone runtime | persisted server runtime + server chart zones | asterStrategy2 + server OHLC | accountTruth.strategy + portfolio-chart.zones | Chart, zone details | localStorage zone cache, browser zone derivation | REPLACED in Portfolio Koers |
| Day High / Low | `_aster_account_daily_range` | persisted 5m account-equity OHLC + current server snapshot | asterPortfolioChart5m | accountTruth.performance + portfolio-chart.dayHigh/dayLow | Snapshot/Advisor/Portfolio Koers | browser-local candle history | REPLACED |
| Rendement vandaag | portfolio growth runtime | persisted dailyGrowth | portfolioGrowth/aster | accountTruth.performance.todayGrowthPercentage | Snapshot | DOM scrape | REPLACED |
| Gemiddeld per dag | portfolio growth runtime | persisted dailyGrowth aggregates | portfolioGrowth/aster | accountTruth.performance.averageDailyGrowthPercentage | Snapshot | DOM scrape | REPLACED |
| Gesloten resultaat vandaag | close-history server owner | persisted server closed trades, fail-closed when 100-row boundary can truncate | asterClosedTrades | accountTruth.performance.realizedPnlToday | Snapshot | DOM scrape | REPLACED, reliability flag required |
| Trades gesloten vandaag | close-history server owner | persisted server closed trades | asterClosedTrades | accountTruth.performance.tradesClosedToday | Snapshot | DOM scrape | REPLACED, reliability flag required |
| Portfolio Koers candles | portfolio-chart server | persisted exchange-confirmed account equity | timeframe collections | portfolio-chart.candles | Portfolio Koers | localStorage portfolioEquity | REPLACED |
| Portfolio Koers realtime equity | aster_status / portfolio-chart server | server snapshot | server state | currentEquity | Portfolio Koers | browser parse of rendered equity + synthetic OHLC | REMOVED |
| Realtime market mark | market stream | server SSE market event | none | realtime stream | position mark decoration | browser recomputation of PnL/equity/notional | FINANCIAL RECOMPUTATION REMOVED |
| Browser UI preferences | individual UI component | browser | localStorage allowed | n/a | UI only | n/a | ALLOWED |

## Browser storage classification

Allowed:
- selected UI destination/tab
- visual-only expand/collapse state
- other non-financial presentation preferences

Forbidden:
- account snapshots
- equity history
- PnL
- balances
- positions
- trade history
- DCA/TP/hedge/recovery state
- price zones
- soldier/seat runtime state
- any fallback capable of changing a displayed financial or trading fact

Retired keys:
- `tradementor.asterSnapshot.v2:*`
- `tradementor.portfolioEquity.v2.*`
- `tradementor.portfolioZones.v1.*`
- `tradementor.zoneSoldierActivity.v1.*`

Sign-out contains one-way cleanup for these retired keys only. Nothing reads them.

## Single-writer rules

1. Exchange account snapshot: only server account/runtime code writes canonical account snapshot.
2. Strategy-2 state: only Strategy-2 server runtime/settings routes write it.
3. Portfolio equity OHLC: only server persistence helpers write timeframe candles.
4. Daily growth: only portfolio growth server logic writes dailyGrowth.
5. Browser: zero business-truth writers.
6. Realtime browser market events may decorate mark price only. They may not write or derive equity, balance, notional, realized PnL, unrealized PnL, DCA, TP, hedge or zone truth.

## Failure behavior

If canonical data is unavailable:
- show `—`, unavailable or stale;
- keep the last rendered React state only as visual continuity during the current mounted session when explicitly safe;
- do not persist it;
- do not merge it with a partial payload;
- do not downgrade missing fields to zero;
- do not derive replacement financial values from market prices or DOM text.

## Duplicate remediation log

| Duplicate | Decision | Reason | Removal condition | Status |
|---|---|---|---|---|
| `aster-snapshot-cache.mjs` | REMOVE | browser account truth | canonical status live | removed in Build 571 |
| `portfolio-equity-history.ts` browser history | REMOVE | device-specific account history | server OHLC live | removed in Build 571 |
| Portfolio Koers local zone cache | REMOVE | second zone truth | server zones live | removed |
| Portfolio Koers browser-derived zones | REMOVE | second derivation | server zones live | removed |
| Portfolio Koers DOM equity → synthetic candle | REMOVE | client financial reconstruction | server currentEquity live | removed |
| Snapshot DOM metric scraping | REMOVE for business values | cross-surface inconsistency | accountTruth live | removed; DOM retained only for button UI state |
| useExchangeData account+history merge | REMOVE | mixed freshness / partial fallback | status is canonical account snapshot | removed |
| Realtime mark → PnL/equity formula | REMOVE | browser financial truth | server refresh remains authoritative | removed |
| Legacy configurator sources | TEMPORARILY COMPATIBLE | not currently routed live | delete after existing release-contract tests prove no live dependency | pending separate cleanup |
| Old backend strategy compatibility projections | TEMPORARILY COMPATIBLE | some current presentation consumers still depend on shape | migrate consumers to accountTruth/runtimeTruth | staged |

## CI release gates

A release must fail if:
- Portfolio Koers reads or writes browser business-truth keys;
- useExchangeData restores/persists Aster account snapshots in browser storage;
- Snapshot derives portfolio values by scraping other rendered components;
- realtime market code derives equity or PnL;
- accountTruth loses `readOnly=true`, `ordersSent=0`, provenance or schema version;
- account status and Portfolio Koers stop sharing the canonical day-range helper.

## Account-isolation contract

- every server read is authenticated and keyed by Firebase UID;
- no account business data is stored under shared browser keys;
- changing UID initializes an empty browser account state and fetches the new canonical server state;
- no previous user's account data is used as fallback;
- the same UID on two devices receives the same server-owned values for the same captured snapshot.

## Cross-surface contract

For the same canonical capture:
- Portfolio Koers currentEquity must equal accountTruth.account.equity within the expected server snapshot timing window;
- Snapshot equity/available/PnL/risk values render from accountTruth only;
- dayHigh/dayLow are produced by the same server helper for accountTruth and Portfolio Koers;
- position counts come from canonical server position rows;
- missing/stale canonical values are displayed as unavailable, never reconstructed.

## Trading safety

Build 571 does not change:
- scanner decisions;
- entry decisions;
- DCA decisions;
- TP decisions;
- hedge/recovery decisions;
- order sizing;
- leverage;
- exchange order submission;
- user trading settings.

The migration is read/presentation architecture only.
