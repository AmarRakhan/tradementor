from pathlib import Path

MAIN = Path("cloud_api/main.py")
text = MAIN.read_text(encoding="utf-8")

old_import = "from aster_dynamic_hedge_execution import run_dynamic_hedge_overlay, dynamic_strategy_order_guard\n"
new_import = (
    "from aster_dynamic_hedge_execution import dynamic_strategy_order_guard\n"
    "from aster_dynamic_hedge_sequence import run_dynamic_hedge_sequence\n"
)
if new_import not in text:
    if old_import not in text:
        raise SystemExit("Dynamic Hedge execution import marker ontbreekt")
    text = text.replace(old_import, new_import, 1)

old_comment = (
    "# Strategy-2 scheduler integration. Dynamic Hedge gets first right of action and\n"
    "# at most one hedge order per leased tick. Only when the hedge is already inside\n"
    "# its safe dynamic band may Multi BB continue on the dominant trading side.\n"
)
new_comment = (
    "# Strategy-2 scheduler integration. Dynamic Hedge gets first right of action and\n"
    "# may execute multiple individually confirmed actions in the same leased tick.\n"
    "# Each next action is based on fresh Aster position/margin truth after a 2..5s\n"
    "# cadence; capital/risk sizing is the limiter, not a one-order-per-tick rule.\n"
)
if old_comment in text:
    text = text.replace(old_comment, new_comment, 1)

if "dynamic=run_dynamic_hedge_sequence(" not in text:
    marker = "dynamic=run_dynamic_hedge_overlay("
    if marker not in text:
        raise SystemExit("Dynamic Hedge scheduler call marker ontbreekt")
    text = text.replace(marker, "dynamic=run_dynamic_hedge_sequence(", 1)

MAIN.write_text(text, encoding="utf-8")
print("Fast sequential Dynamic Hedge runner installed: no one-order-per-tick throttle")
