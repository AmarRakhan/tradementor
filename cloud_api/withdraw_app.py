"""TradeMentor Cloud API entrypoint with secure production extensions registered."""
import main
import withdraw_extension  # noqa: F401  - importing registers routes on main.app
import aster_spot_balance_extension  # noqa: F401 - read-only Spot balance route
import profit_sweep_settings_extension  # noqa: F401 - per-user Profit Pot settings
import profit_sweep_live_extension  # noqa: F401 - fail-closed confirmed-close Futures -> Spot sweep
from snapshot_profit_close_extension import router as snapshot_profit_close_router

# P0 2026-09-16: Portfolio Noodhedge is globally disabled.
# Do NOT register its API, background worker, margin hook or order guard.
# This guarantees that no new emergency-hedge orders can be scheduled/submitted
# after rollout and that stale EXECUTING/LOCKED state cannot block manual closes.
# Existing exchange positions are deliberately left untouched.

main.app.include_router(snapshot_profit_close_router)
app = main.app
