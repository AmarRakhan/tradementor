"""TradeMentor Cloud API entrypoint with secure production extensions registered."""
import main
import withdraw_extension  # noqa: F401  - importing registers routes on main.app
from snapshot_profit_close_extension import router as snapshot_profit_close_router
from aster_portfolio_emergency_hedge import install as install_aster_portfolio_emergency_hedge

main.app.include_router(snapshot_profit_close_router)
install_aster_portfolio_emergency_hedge(
    main.app,
    db=main.db,
    load_secret=main.load_aster_secret,
    auth_app=main.auth_app,
)
app = main.app
