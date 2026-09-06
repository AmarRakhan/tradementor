"""TradeMentor Cloud API entrypoint with the secure withdrawal extension registered."""
import main
import withdraw_extension  # noqa: F401  - importing registers routes on main.app

app = main.app
