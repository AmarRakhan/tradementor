# Smart Rescue DCA validation — 2026-09-14

## Scope

- Read-only historical replay against Aster public `1m` candles.
- Symbols: BTCUSDT and HYPEUSDT.
- 30 days per symbol, 43,200 candles each (86,400 total).
- Candle model: minute-close-only; intrabar high/low ordering is deliberately not invented.
- Leverage in replay: 50x. Start margin per cycle: $0.15.
- Fees/funding/liquidation engine are not fabricated in this replay. Live execution keeps using the existing Aster exchange rules, tier/leverage resolution, fills and portfolio risk engine.
- Portfolio Take Profit is intentionally outside this replay and is validated by deterministic integration tests because Smart Rescue does not own TP.

## Historical regimes selected automatically

### BTCUSDT

| Regime | UTC window | Return | Max drawdown | Range |
|---|---|---:|---:|---:|
| rising | 2026-08-19T12:18:00Z → 2026-08-20T00:17:00Z | 8.12% | 2.43% | 8.45% |
| choppy | 2026-09-11T18:18:00Z → 2026-09-12T06:17:00Z | 0.00% | 0.64% | 0.67% |
| normal_correction | 2026-08-25T02:18:00Z → 2026-08-25T14:17:00Z | -2.35% | 3.60% | 3.74% |
| strong_decline | 2026-08-28T08:18:00Z → 2026-08-28T20:17:00Z | -2.94% | 3.39% | 3.50% |
| crashlike_drawdown | 2026-08-21T02:18:00Z → 2026-08-21T14:17:00Z | 2.80% | 3.82% | 6.74% |

### HYPEUSDT

| Regime | UTC window | Return | Max drawdown | Range |
|---|---|---:|---:|---:|
| rising | 2026-08-19T10:19:00Z → 2026-08-19T22:18:00Z | 22.79% | 4.54% | 24.60% |
| choppy | 2026-08-29T23:19:00Z → 2026-08-30T11:18:00Z | 0.00% | 1.16% | 1.70% |
| normal_correction | 2026-09-02T05:19:00Z → 2026-09-02T17:18:00Z | -2.49% | 4.01% | 4.18% |
| strong_decline | 2026-09-10T04:19:00Z → 2026-09-10T16:18:00Z | -6.34% | 6.45% | 6.89% |
| crashlike_drawdown | 2026-08-21T17:19:00Z → 2026-08-22T05:18:00Z | 4.78% | 11.68% | 13.22% |

## Aggregate Smart Rescue replay results

Each configuration starts once in each of the five selected regimes per symbol. “Position drawdown on margin” is deliberately **not** a portfolio-liquidation estimate; at 50x it can exceed 100% while cross-margin survival still depends on total account equity and all other positions.

### BTCUSDT

| Config | Starts | Rescue orders | Skipped | Max DCA | Max margin | Max notional | Worst BE recovery | Largest drawdown on allocated margin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 5pct-5dca-1.35x | 5 | 7 | 0 | 3 | $0.99 | $49.75 | 1.42% | 133.3% |
| 10pct-10dca-1.35x | 5 | 8 | 2 | 4 | $1.49 | $74.66 | 1.17% | 147.5% |
| 20pct-25dca-1.20x | 5 | 11 | 6 | 6 | $2.10 | $105.08 | 1.45% | 132.5% |
| custom-12pct-16dca-1.25x | 5 | 10 | 5 | 5 | $1.97 | $98.40 | 1.26% | 128.1% |

### HYPEUSDT

| Config | Starts | Rescue orders | Skipped | Max DCA | Max margin | Max notional | Worst BE recovery | Largest drawdown on allocated margin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 5pct-5dca-1.35x | 5 | 12 | 0 | 4 | $1.49 | $74.66 | 2.16% | 208.7% |
| 10pct-10dca-1.35x | 5 | 14 | 3 | 5 | $2.17 | $108.29 | 1.94% | 198.3% |
| 20pct-25dca-1.20x | 5 | 17 | 9 | 6 | $2.26 | $113.17 | 2.36% | 218.2% |
| custom-12pct-16dca-1.25x | 5 | 17 | 7 | 6 | $2.58 | $129.14 | 2.24% | 212.3% |

## Deterministic simulation coverage

- Calm decline with separate rebounds: multiple rescue levels can fill one-by-one.
- Free fall: deeper crossed level replaces shallower armed levels; no buy-buy-buy cascade.
- Deep bottom + rebound: weighted entry improves and required underlying-price recovery shrinks.
- Rising market: no rescue is armed or bought.
- Full 20% / 25-step ladder: finite margin, notional and break-even calculations.
- Insufficient margin: advisory configuration remains saveable; live order waits/fails without corrupting rescue state.
- Portfolio TP during rescue: existing Portfolio TP gate wins before Smart Rescue execution.
- Partial/confirmed fill accounting: actual exchange executed quantity is used.
- Restart while an order remains open: duplicate rescue submission is blocked.
- Restart after exchange fill but before state persistence: position increase is reconciled into the armed rescue level; replaying the same snapshot is idempotent.
- Global Smart Rescue toggle OFF after a cycle started: existing cycle finishes under its stored Smart Rescue snapshot; only new cycles switch back to normal DCA.
- Smart Rescue ON does not retrofit already-open positions.

## Observations

- The progressive ladder behaves as intended: deeper volatility causes more skipped shallow levels and fewer clustered buys than a fixed-distance catch-up ladder.
- On HYPE, the selected crashlike 12-hour window contained an 11.68% peak-to-trough drawdown. Smart Rescue remained deterministic and did not generate duplicate orders in the replay.
- High leverage remains high risk. The replay shows drawdown on the position’s allocated margin can exceed 100%; Smart Rescue is a DCA/rescue mechanism, not a hedge or liquidation guarantee.
- Break-even shown in the UI is the **underlying price recovery** from the simulated/current price to weighted break-even, not leveraged ROI.

## Evidence files

- `docs/smart-rescue-backtest-20260914.json` — BTCUSDT 30-day replay.
- `docs/smart-rescue-backtest-hype-20260914.json` — HYPEUSDT 30-day replay.
- `tools/smart_rescue_backtest.py` — reproducible read-only replay script.
- `cloud_api/test_aster_smart_rescue.py` — unit/integration/restart/idempotency tests.
- `cloud_api/test_aster_smart_rescue_simulation.py` — deterministic scenario simulations.
