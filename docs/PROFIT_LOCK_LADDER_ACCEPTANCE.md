# Profit Lock Ladder — acceptance checklist

- opt-in; default OFF
- existing Bot Settings and trading behavior unchanged when OFF
- LONG-only primary execution when ON without overwriting stored legacy LONG/SHORT choices
- manual coin selection and automatic seat filling supported
- net-cycle-profit ladder (LONG + Profit Lock SHORT + realized cycle PnL - fees when available)
- one-way ratchet: Profit Lock SHORT is not automatically reduced during a cycle
- hard `SHORT <= LONG` invariant
- final 100% level first fills and validates full hedge, then closes only that symbol cycle and restarts cleanly
- weighted account Portfolio Snapshot hedge coverage
- per-symbol Profit Lock detail status
- normal pre-existing SHORTs are isolated and block Profit Lock Ladder rather than being silently adopted/closed
- approved visual reference `file_00000000e8dc82108202dd2e1397c131`
