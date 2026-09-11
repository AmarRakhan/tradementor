# Profit Lock Ladder — release contract

Reference UI: `file_00000000e8dc82108202dd2e1397c131`.

This mode is opt-in and defaults to OFF. When OFF, existing Multi DCA behavior remains authoritative. When ON, primary trading is LONG-only at runtime and SHORT is reserved for automatic profit locking. The user's stored legacy LONG/SHORT distribution and manual side choices are preserved so disabling the mode restores them.

Core invariants:

- configured LONG DCA keeps running;
- normal SHORT-primary entry is suppressed at runtime;
- Profit Lock SHORT never auto-reduces during the cycle;
- `shortNotional <= longNotional` is mandatory;
- ladder advancement requires a newly reached net cycle-profit level;
- weighted account hedge is `sum(profitLockShortNotional) / sum(longNotional)`;
- the final 100% level first fills and confirms the missing SHORT to effectively full hedge; only then does the following reconciliation close that symbol's Profit Lock SHORT + LONG, confirm flat, and release the seat for a new LONG cycle;
- existing normal SHORT positions are never adopted or silently closed by Profit Lock Ladder;
- Dynamic Hedge yields the SHORT side while Profit Lock Ladder is enabled;
- existing Bot Settings and Portfolio Snapshot remain present; the new UI is additive.
