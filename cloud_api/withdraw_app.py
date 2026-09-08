"""TradeMentor Cloud API entrypoint with secure production extensions registered."""
import main
import withdraw_extension  # noqa: F401  - importing registers routes on main.app
from snapshot_profit_close_extension import router as snapshot_profit_close_router

main.app.include_router(snapshot_profit_close_router)
app = main.app
