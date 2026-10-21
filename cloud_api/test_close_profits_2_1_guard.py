"""Close Profits 2.1 offline tests: guard, strict Auto Hedge lock, planner, route behaviour.

No network, no Firestore, no live orders. The close route is executed from its real
source (ast-extracted from main.py) against mocks, because main.py itself cannot be
imported offline (firebase_admin etc.).
"""
from __future__ import annotations

import ast
import builtins
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import aster_position_loss_auto_hedge_lock as lock
from manual_profit_close_guard import bulk_profit_close_block_reason
from manual_profit_close_planner import build_profit_close_plan

HERE = Path(__file__).parent
MAIN_SRC = (HERE / "main.py").read_text()

FILTERS = {s: {"stepSize": "0.001", "minQty": "0.001", "minNotional": "5", "maxQty": "100000"}
           for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")}


def row(symbol, side, qty, pnl, mark="100"):
    qty = float(qty)
    amt = -qty if side == "SHORT" else qty
    return {"symbol": symbol, "positionSide": side, "positionAmt": str(amt),
            "unRealizedProfit": str(pnl), "markPrice": mark}


def never_managed(**_):
    return False


class GuardTests(unittest.TestCase):
    def test_normal_short_allowed(self):
        self.assertIsNone(bulk_profit_close_block_reason("u", "BTCUSDT", "SHORT", [], managed_check=never_managed))

    def test_normal_long_not_allowed_in_bulk(self):
        self.assertIn("SHORT", bulk_profit_close_block_reason("u", "BTCUSDT", "LONG", [], managed_check=never_managed))

    def test_auto_hedge_short_blocked(self):
        reason = bulk_profit_close_block_reason("u", "BTCUSDT", "SHORT", [], managed_check=lambda **_: True)
        self.assertIn("Auto Hedge", reason)

    def test_focus_airbag_blocked(self):
        legs = [{"symbol": "ETHUSDT", "side": "SHORT", "role": "FOCUS_SLOT_AIRBAG:slot1"}]
        self.assertIn("Focus Airbag", bulk_profit_close_block_reason("u", "ETHUSDT", "SHORT", legs, managed_check=never_managed))
        self.assertIsNone(bulk_profit_close_block_reason("u", "SOLUSDT", "SHORT", legs, managed_check=never_managed))

    def test_status_change_between_preview_and_execution_blocks(self):
        state = {"managed": False}
        check = lambda **_: state["managed"]
        self.assertIsNone(bulk_profit_close_block_reason("u", "BTCUSDT", "SHORT", [], managed_check=check))
        state["managed"] = True  # Auto Hedge took the pair after the preview
        self.assertIsNotNone(bulk_profit_close_block_reason("u", "BTCUSDT", "SHORT", [], managed_check=check))

    def test_reader_failure_propagates(self):
        def boom(**_):
            raise lock.AutoHedgeCloseBlocked({"message": "unreadable"})
        with self.assertRaises(lock.AutoHedgeCloseBlocked):
            bulk_profit_close_block_reason("u", "BTCUSDT", "SHORT", [], managed_check=boom)


class StrictLockTests(unittest.TestCase):
    def tearDown(self):
        lock.configure_auto_hedge_lock_reader(None)

    def test_missing_reader_fails_closed(self):
        lock.configure_auto_hedge_lock_reader(None)
        with self.assertRaises(lock.AutoHedgeCloseBlocked):
            lock.auto_hedge_symbol_managed_strict(account_uid="u", symbol="BTCUSDT")
        # legacy helper keeps its old (open) behaviour: proves the strict one is needed
        self.assertFalse(lock.auto_hedge_symbol_managed(account_uid="u", symbol="BTCUSDT"))

    def test_reader_exception_and_garbage_fail_closed(self):
        def boom(uid, sym):
            raise RuntimeError("firestore down")
        lock.configure_auto_hedge_lock_reader(boom)
        with self.assertRaises(lock.AutoHedgeCloseBlocked):
            lock.auto_hedge_symbol_managed_strict(account_uid="u", symbol="BTCUSDT")
        lock.configure_auto_hedge_lock_reader(lambda uid, sym: None)
        with self.assertRaises(lock.AutoHedgeCloseBlocked):
            lock.auto_hedge_symbol_managed_strict(account_uid="u", symbol="BTCUSDT")

    def test_statuses(self):
        for status, expected in [("", False), ("CLOSED", False), ("HEDGED", True), ("HEDGING", True),
                                 ("RECOVERY", True), ("REHEDGE_ARMED", True), ("DISABLED", True),
                                 ("SOMETHING_NEW", True)]:
            lock.configure_auto_hedge_lock_reader(lambda uid, sym, s=status: {"status": s})
            self.assertIs(lock.auto_hedge_symbol_managed_strict(account_uid="u", symbol="BTCUSDT"), expected, status)
        lock.configure_auto_hedge_lock_reader(lambda uid, sym: {})
        self.assertFalse(lock.auto_hedge_symbol_managed_strict(account_uid="u", symbol="BTCUSDT"))


class PlannerTests(unittest.TestCase):
    def plan(self, rows, pct=25):
        return build_profit_close_plan(rows, pct, FILTERS, hedge_links={})

    def test_lone_long_is_never_selected(self):
        p = self.plan([row("BTCUSDT", "LONG", 1, 5)])
        self.assertEqual(p["selected"], [])
        self.assertEqual(p["skipped"][0]["reason"], "long_requires_verified_hedge_link")

    def test_long_with_unverified_hedge_skipped(self):
        p = self.plan([row("BTCUSDT", "LONG", 1, 5), row("BTCUSDT", "SHORT", 1, -2)])
        self.assertTrue(any(s["side"] == "LONG" and s["reason"] == "hedge_relationship_unverified" for s in p["skipped"]))
        self.assertFalse(any(x["side"] == "LONG" for x in p["selected"]))

    def test_threshold_is_strictly_above_050(self):
        p = self.plan([row("BTCUSDT", "SHORT", 1, "0.50"), row("ETHUSDT", "SHORT", 1, "0.51")])
        self.assertEqual([x["symbol"] for x in p["selected"]], ["ETHUSDT"])
        self.assertTrue(any(s["symbol"] == "BTCUSDT" and s["reason"] == "profit_not_above_0_50" for s in p["skipped"]))

    def test_negative_short_quantity_uses_absolute(self):
        p = self.plan([row("BTCUSDT", "SHORT", 8, 3)], 50)
        self.assertEqual(Decimal(p["selected"][0]["quantity"]), Decimal(4))

    def test_percentages(self):
        for pct, expected in [(25, "2.000"), (50, "4"), (75, "6.000"), (100, "8.000")]:
            p = self.plan([row("BTCUSDT", "SHORT", 8, 3)], pct)
            self.assertEqual(Decimal(p["selected"][0]["quantity"]), Decimal(expected))

    def test_invalid_percentage_rejected(self):
        with self.assertRaises(ValueError):
            self.plan([row("BTCUSDT", "SHORT", 8, 3)], 33)

    def test_minimum_order_skipped_with_reason(self):
        p = self.plan([row("BTCUSDT", "SHORT", 0.002, 3, mark="1")], 25)  # 0.0005 < minQty
        self.assertEqual(p["selected"], [])
        self.assertEqual(p["skipped"][0]["reason"], "below_exchange_minimum")

    def test_loss_never_selected_and_mixed_portfolio(self):
        rows = [row("BTCUSDT", "SHORT", 1, 4), row("BTCUSDT", "LONG", 1, -9),       # loss long untouched
                row("ETHUSDT", "SHORT", 2, -1), row("SOLUSDT", "SHORT", 5, 2),
                row("XRPUSDT", "LONG", 3, 7)]                                         # lone profitable long
        p = self.plan(rows, 100)
        self.assertEqual(sorted((x["symbol"], x["side"]) for x in p["selected"]),
                         [("BTCUSDT", "SHORT"), ("SOLUSDT", "SHORT")])


def load_close_route():
    tree = ast.parse(MAIN_SRC)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "close_one_aster_position")
    fn.decorator_list = []
    module = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(module)
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    return compile(module, "main.py::close_one_aster_position", "exec"), names


class RouteBehaviourTests(unittest.TestCase):
    """Runs the REAL close route source with every dependency mocked."""

    def build(self, *, managed=False, reader_raises=False, owned_legs=None, bulk=True, qty=8.0):
        code, names = load_close_route()
        ns = {n: mock.MagicMock(name=n) for n in names if not hasattr(builtins, n)}
        calls = SimpleNamespace(orders=[], intents=[])

        class FakeHTTP(Exception):
            def __init__(self, status, detail):
                self.status_code, self.detail = status, detail

        class Blocked(RuntimeError):
            pass

        class Intent:
            def create(self, data): calls.intents.append(("create", data))
            def set(self, data, merge=False): calls.intents.append(("set", data))

        live = [{"symbol": "BTCUSDT", "positionSide": "SHORT", "positionAmt": "-8", "markPrice": "100", "leverage": "5"}]
        client = mock.MagicMock()
        client.position_risk.return_value = live
        ns.update({
            "HTTPException": FakeHTTP, "AutoHedgeCloseBlocked": Blocked,
            "os": SimpleNamespace(getenv=lambda *a, **k: "true"),
            "hashlib": __import__("hashlib"), "datetime": __import__("datetime").datetime,
            "timezone": __import__("datetime").timezone,
            "google_exceptions": SimpleNamespace(AlreadyExists=type("AlreadyExists", (Exception,), {})),
            "user_reference": lambda user: SimpleNamespace(collection=lambda n: SimpleNamespace(document=lambda d: Intent())),
            "AsterV3Client": lambda **kw: client, "load_aster_secret": lambda u: SimpleNamespace(signer_address="a"),
            "local_eip712_signer": lambda s: None, "_block_order_during_close_all": lambda uid: None,
            "ALLOWED_CLOSE_PERCENTAGES": {25, 50, 75, 100},
            "safe_float": lambda v, d=0.0: float(v) if v not in (None, "") else d,
            "close_size": lambda q, p: q * p / 100, "Decimal": __import__("decimal").Decimal,
            "ContractRules": SimpleNamespace(from_exchange_info=lambda info: SimpleNamespace(
                market_quantity=lambda q, m: q)),
            "AsterValidationError": ValueError,
            "_position_loss_auto_hedge_pair": lambda uid, sym: {},
            "_MANUAL_AUTO_HEDGE_RELEASE_STATUSES": set(),
            "require_auto_hedge_close_allowed": lambda **kw: None,
            "begin_manual_action": lambda *a, **k: object(), "complete_manual_action": lambda *a, **k: None,
            "fail_manual_action": lambda *a, **k: None, "_fail_position_loss_auto_hedge_manual_release": lambda *a, **k: None,
            "_complete_position_loss_auto_hedge_manual_release": lambda *a, **k: None,
            "PairExecutionPlan": lambda *a, **k: object(), "PositionSide": lambda s: s,
            "_release_aster_account_coordination": lambda *a, **k: None,
            "time": SimpleNamespace(sleep=lambda s: None),
        })
        client.public_exchange_info.return_value = {"symbols": [{"symbol": "BTCUSDT"}]}

        def execute(*a, **k):
            calls.orders.append(k)
            live[0]["positionAmt"] = str(-(8 - 8 * 0.25))
            return {"status": "FILLED"}
        ns["execute_aster_leg"] = execute

        def bulk_reason(uid, symbol, side):
            if reader_raises:
                raise Blocked("Auto Hedge-lock kon niet betrouwbaar worden gelezen")
            return bulk_profit_close_block_reason(
                uid, symbol, side, owned_legs or [], managed_check=lambda **_: managed)
        ns["_bulk_profit_close_block_reason_live"] = bulk_reason
        exec(code, ns)
        request = SimpleNamespace(confirm=True, side="SHORT", expected_quantity=qty, percentage=25,
                                  idempotency_key="k" * 20, bulk_profit_close=bulk)
        return ns["close_one_aster_position"], request, calls, FakeHTTP, Blocked

    def call(self, **kw):
        fn, request, calls, FakeHTTP, Blocked = self.build(**kw)
        try:
            return fn("btcusdt", request, {"uid": "u1"}), calls, None
        except (FakeHTTP, Blocked) as exc:
            return None, calls, exc

    def test_normal_bulk_short_is_closed(self):
        result, calls, exc = self.call()
        self.assertIsNone(exc)
        self.assertEqual(len(calls.orders), 1)
        self.assertEqual(result["percentage"], 25)

    def test_auto_hedge_managed_blocked_before_any_order_with_stale_snapshot(self):
        result, calls, exc = self.call(managed=True)
        self.assertEqual(getattr(exc, "status_code", None), 409)
        self.assertIn("Auto Hedge", exc.detail)
        self.assertEqual(calls.orders, [])
        self.assertTrue(any(c[1].get("status") == "blocked_bulk_protected" for c in calls.intents if c[0] == "set"))

    def test_focus_airbag_blocked(self):
        _, calls, exc = self.call(owned_legs=[{"symbol": "BTCUSDT", "side": "SHORT", "role": "FOCUS_SLOT_AIRBAG:s"}])
        self.assertEqual(calls.orders, [])
        self.assertIn("Focus Airbag", exc.detail)

    def test_unreliable_hedge_state_fails_closed(self):
        _, calls, exc = self.call(reader_raises=True)
        self.assertIsNotNone(exc)
        self.assertEqual(calls.orders, [])

    def test_individual_close_unchanged_when_flag_not_set(self):
        # Without the bulk flag the new guard is not consulted at all, even when
        # the symbol is Auto Hedge managed: existing individual Close semantics.
        result, calls, exc = self.call(managed=True, bulk=False)
        self.assertIsNone(exc)
        self.assertEqual(len(calls.orders), 1)

    def test_stale_quantity_rejected(self):
        _, calls, exc = self.call(qty=5.0)
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(calls.orders, [])

    def test_duplicate_idempotency_key_places_no_second_order(self):
        fn, request, calls, FakeHTTP, Blocked = self.build()
        ns_exc = fn.__globals__["google_exceptions"].AlreadyExists
        fn.__globals__["user_reference"] = lambda user: SimpleNamespace(collection=lambda n: SimpleNamespace(
            document=lambda d: SimpleNamespace(create=mock.Mock(side_effect=ns_exc()), set=lambda *a, **k: None)))
        with self.assertRaises(FakeHTTP) as ctx:
            fn("btcusdt", request, {"uid": "u1"})
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(calls.orders, [])


class SourceContractTests(unittest.TestCase):
    def test_guard_runs_before_any_state_change_in_route(self):
        route = MAIN_SRC[MAIN_SRC.index("def close_one_aster_position("):]
        route = route[:route.index('@app.post("/v1/me/aster/simulate")')]
        guard = route.index("if request.bulk_profit_close:")
        for later in ("close_size(live_quantity", "_begin_position_loss_auto_hedge_manual_release(",
                      "begin_manual_action(", "execute_aster_leg("):
            self.assertLess(guard, route.index(later), later)
        self.assertLess(route.index("expected_quantity"), guard)  # after live-quantity check

    def test_request_model_flag_defaults_false(self):
        self.assertIn("bulk_profit_close: bool = False", MAIN_SRC)

    def test_preview_uses_strict_check_and_no_new_close_route(self):
        preview = MAIN_SRC[MAIN_SRC.index("def preview_manual_profit_close_plan("):]
        preview = preview[:preview.index('@app.post("/v1/me/aster/positions/close-profitable")')]
        self.assertIn("auto_hedge_symbol_managed_strict", preview)
        self.assertEqual(MAIN_SRC.count('"/v1/me/aster/positions/{symbol}/close"'), 1)
        self.assertNotIn("bulk-close", MAIN_SRC.lower().replace("bulk_close", ""))

    def test_no_order_submission_in_preview(self):
        preview = MAIN_SRC[MAIN_SRC.index("def preview_manual_profit_close_plan("):]
        preview = preview[:preview.index('@app.post("/v1/me/aster/positions/close-profitable")')]
        for forbidden in ("execute_aster_leg", "submit_order", "live=True"):
            self.assertNotIn(forbidden, preview)


if __name__ == "__main__":
    unittest.main()
