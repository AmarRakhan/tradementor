"""TradeMentor Cloud API entrypoint with secure production extensions registered."""
import main
import withdraw_extension  # noqa: F401  - importing registers routes on main.app
import aster_spot_balance_extension  # noqa: F401 - read-only Spot balance route
import profit_sweep_settings_extension  # noqa: F401 - per-user Profit Pot settings
import profit_sweep_live_extension  # noqa: F401 - fail-closed confirmed-close Futures -> Spot sweep
from snapshot_profit_close_extension import router as snapshot_profit_close_router
from aster_portfolio_emergency_hedge import install as install_aster_portfolio_emergency_hedge
from aster_portfolio_emergency_margin_extension import install as install_aster_portfolio_emergency_margin_safety
from aster_portfolio_emergency_guard import install as install_aster_portfolio_emergency_guard

main.app.include_router(snapshot_profit_close_router)
install_aster_portfolio_emergency_hedge(
    main.app,
    db=main.db,
    load_secret=main.load_aster_secret,
    auth_app=main.auth_app,
)
install_aster_portfolio_emergency_margin_safety()
install_aster_portfolio_emergency_guard(main)
app = main.app
