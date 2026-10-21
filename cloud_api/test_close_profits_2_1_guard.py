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
from manual_profit_close_guard import BulkProtectionUnreliable, bulk_profit_close_block_reason, focus_airbag_protected
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


def reason(symbol="BTCUSDT", side="SHORT", state=None, *, exists=True, managed=lambda **_: False):
    state = {"ownedLegs": []} if state is None else state
    return bulk_profit_close_block_reason("u", symbol, side, state, strategy2_exists=exists, managed_check=managed)


class GuardTests(unittest.TestCase):
    def test_normal_short_allowed(self):
        self.assertIsNone(reason())

    def test_normal_long_not_allowed_in_bulk(self):
        self.assertIn("SHORT", reason(side="LONG"))

    def test_auto_hedge_short_blocked(self):
        self.assertIn("Auto Hedge", reason(managed=lambda **_: True))

    def test_focus_airbag_blocked(self):
        state = {"ownedLegs": [{"symbol": "ETHUSDT", "side": "SHORT", "role": "FOCUS_SLOT_AIRBAG:slot1"}]}
        self.assertIn("Focus Airbag", reason("ETHUSDT", state=state))
        self.assertIsNone(reason("SOLUSDT", state=state))

    def test_status_change_between_preview_and_execution_blocks(self):
        flag = {"managed": False}
        check = lambda **_: flag["managed"]
        self.assertIsNone(reason(managed=check))
        flag["managed"] = True  # Auto Hedge took the pair after the preview
        self.assertIsNotNone(reason(managed=check))

    def test_reader_failure_propagates(self):
        def boom(**_):
            raise lock.AutoHedgeCloseBlocked({"message": "unreadable"})
        with self.assertRaises(lock.AutoHedgeCloseBlocked):
            reason(managed=boom)


class FocusAirbagFailClosedTests(unittest.TestCase):
    """Proven 'no airbag' vs 'cannot tell'."""

    def test_proven_none(self):
        self.assertFalse(focus_airbag_protected(None, exists=False, symbol="BTCUSDT", side="SHORT"))      # no document ever
        self.assertFalse(focus_airbag_protected({}, exists=True, symbol="BTCUSDT", side="SHORT"))          # doc without focus state
        self.assertFalse(focus_airbag_protected({"ownedLegs": []}, exists=True, symbol="BTCUSDT", side="SHORT"))
        self.assertFalse(focus_airbag_protected(
            {"ownedLegs": [{"symbol": "BTCUSDT", "side": "SHORT", "role": "HARVEST"}], "focusLiveSlots": []},
            exists=True, symbol="BTCUSDT", side="SHORT"))

    def test_unreliable_cases_raise(self):
        bad_states = [
            "not a dict", ["x"],
            {"ownedLegs": None}, {"ownedLegs": {"a": 1}}, {"ownedLegs": "x"},
            {"ownedLegs": ["junk"]},
            {"ownedLegs": [{"symbol": "", "side": "SHORT", "role": "HARVEST"}]},
            {"ownedLegs": [{"symbol": "BTCUSDT", "side": "BOTH", "role": "HARVEST"}]},
            {"ownedLegs": [{"symbol": "BTCUSDT", "side": "SHORT"}]},               # role missing
            {"ownedLegs": [{"symbol": "BTCUSDT", "side": "SHORT", "role": ""}]},
            {"focusLiveSlots": [{"pair": "ETHUSDT", "side": "LONG"}]},              # focus state without ownedLegs
            {"focusV2State": {}},
            {"ownedLegs": [], "focusLiveSlots": "x"},
            {"ownedLegs": [], "focusLiveSlots": ["junk"]},
            {"ownedLegs": [], "focusLiveSlots": [{"pair": "", "side": "LONG", "airbag": {}}]},
        ]
        for state in bad_states:
            with self.assertRaises(BulkProtectionUnreliable, msg=repr(state)):
                focus_airbag_protected(state, exists=True, symbol="BTCUSDT", side="SHORT")

    def test_slot_with_airbag_protects_both_legs_of_pair(self):
        state = {"ownedLegs": [], "focusLiveSlots": [{"pair": "ETHUSDT", "side": "LONG", "airbag": {"active": True}}]}
        for side in ("LONG", "SHORT"):
            self.assertTrue(focus_airbag_protected(state, exists=True, symbol="ETHUSDT", side=side))
        self.assertFalse(focus_airbag_protected(state, exists=True, symbol="BTCUSDT", side="SHORT"))

    def test_missing_protection_status_blocks_bulk_close_via_guard(self):
        with self.assertRaises(BulkProtectionUnreliable):
            reason(state={"focusLiveSlots": []})   # focus state present, ownedLegs missing


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


def load_route_functions():
    """Real source of the close route and its protection-read helper, straight from main.py."""
    tree = ast.parse(MAIN_SRC)
    wanted = {"close_one_aster_position", "_bulk_profit_close_block_reason_live"}
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert len(fns) == 2
    for fn in fns:
        fn.decorator_list = []
    module = ast.Module(body=fns, type_ignores=[])
    ast.fix_missing_locations(module)
    names = {n.id for f in fns for n in ast.walk(f) if isinstance(n, ast.Name)}
    return compile(module, "main.py::close_route+guard", "exec"), names


try:
    from aster_gateway import AsterValidationError, ContractRules  # needs httpx
    HAVE_GATEWAY = True
except Exception:  # pragma: no cover - dependency missing in this sandbox
    HAVE_GATEWAY = False
from position_close import ALLOWED_CLOSE_PERCENTAGES, close_size

BTC_INFO = {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "filters": [
    {"filterType": "LOT_SIZE", "minQty": "1", "maxQty": "1000", "stepSize": "1"},
    {"filterType": "MARKET_LOT_SIZE", "minQty": "1", "maxQty": "1000", "stepSize": "1"},
    {"filterType": "MIN_NOTIONAL", "notional": "5"}]}]}


class FakeLease:
    """Models the per-account lease (`aster_account_coordination_reference`): exclusive, token based."""
    def __init__(self, busy=False):
        self.holder = "someone" if busy else None
        self.acquired, self.released = [], []

    def acquire(self, uid, owner, purpose):
        if self.holder:
            return None
        self.holder = owner
        self.acquired.append((owner, purpose))
        return f"token-{len(self.acquired)}"

    def release(self, uid, token):
        self.released.append(token)
        self.holder = None

    def auto_hedge_tick(self):
        """Auto Hedge live execution: takes the same lease before any order, PENDING when busy."""
        token = self.acquire("u", "AUTO_HEDGE", "POSITION_LOSS_EXACT_1_TO_1")
        if not token:
            return "PENDING"
        self.release("u", token)
        return "EXECUTED"


class FakeDoc:
    def __init__(self, data, exists=True, raises=False):
        self._data, self.exists, self._raises = data, exists, raises

    def get(self):
        if self._raises:
            raise RuntimeError("firestore unavailable")
        return self

    def to_dict(self):
        return self._data


class RouteBehaviourTests(unittest.TestCase):
    """Runs the REAL close route + protection-read source (ast-extracted from main.py)
    against mocks and a model of the account lease. No FastAPI, no Firestore, no orders."""

    def build(self, *, managed=lambda n: False, strategy2=None, strategy2_exists=True, strategy2_raises=False,
              bulk=True, qty=8.0, percentage=25, busy=False, order_hook=None, info=None, live_qty=8.0,
              real_rules=False):
        code, names = load_route_functions()
        ns = {n: mock.MagicMock(name=n) for n in names if not hasattr(builtins, n)}
        calls = SimpleNamespace(orders=[], intents=[], tick_during_order=None, managed_checks=0, lease=FakeLease(busy))

        class FakeHTTP(Exception):
            def __init__(self, status, detail):
                self.status_code, self.detail = status, detail

        class Intent:
            def create(self, data): calls.intents.append(("create", data))
            def set(self, data, merge=False): calls.intents.append(("set", data))

        live = [{"symbol": "BTCUSDT", "positionSide": "SHORT", "positionAmt": str(-live_qty), "markPrice": "100", "leverage": "5"}]
        client = mock.MagicMock()
        client.position_risk.return_value = live
        client.public_exchange_info.return_value = info or BTC_INFO

        def strict_check(*, account_uid, symbol):
            calls.managed_checks += 1
            return managed(calls.managed_checks)

        if real_rules:
            rules = ContractRules
            validation_error = AsterValidationError
        else:
            rules = SimpleNamespace(from_exchange_info=lambda i: SimpleNamespace(market_quantity=lambda q, m: q))
            validation_error = ValueError

        def execute(*a, **k):
            calls.orders.append(k)
            calls.tick_during_order = calls.lease.auto_hedge_tick()
            if order_hook:
                order_hook()
            live[0]["positionAmt"] = str(-(live_qty - close_size(live_qty, percentage) if percentage != 100 else 0.0))
            return {"status": "FILLED"}

        ns.update({
            "HTTPException": FakeHTTP, "AutoHedgeCloseBlocked": lock.AutoHedgeCloseBlocked,
            "BulkProtectionUnreliable": BulkProtectionUnreliable,
            "bulk_profit_close_block_reason": bulk_profit_close_block_reason,
            "auto_hedge_symbol_managed_strict": strict_check,
            "aster_strategy2_reference": lambda uid: FakeDoc(strategy2 if strategy2 is not None else {"ownedLegs": []},
                                                             exists=strategy2_exists, raises=strategy2_raises),
            "os": SimpleNamespace(getenv=lambda *a, **k: "true"),
            "hashlib": __import__("hashlib"), "datetime": __import__("datetime").datetime,
            "timezone": __import__("datetime").timezone,
            "google_exceptions": SimpleNamespace(AlreadyExists=type("AlreadyExists", (Exception,), {})),
            "user_reference": lambda user: SimpleNamespace(collection=lambda n: SimpleNamespace(document=lambda d: Intent())),
            "AsterV3Client": lambda **kw: client, "load_aster_secret": lambda u: SimpleNamespace(signer_address="a"),
            "local_eip712_signer": lambda s: None, "_block_order_during_close_all": lambda uid: None,
            "ALLOWED_CLOSE_PERCENTAGES": ALLOWED_CLOSE_PERCENTAGES, "close_size": close_size,
            "safe_float": lambda v, d=0.0: float(v) if v not in (None, "") else d,
            "Decimal": __import__("decimal").Decimal, "ContractRules": rules, "AsterValidationError": validation_error,
            "_position_loss_auto_hedge_pair": lambda uid, sym: {},
            "_MANUAL_AUTO_HEDGE_RELEASE_STATUSES": set(),
            "require_auto_hedge_close_allowed": lambda **kw: None,
            "begin_manual_action": lambda *a, **k: object(), "complete_manual_action": lambda *a, **k: None,
            "fail_manual_action": lambda *a, **k: None,
            "_fail_position_loss_auto_hedge_manual_release": lambda *a, **k: None,
            "_complete_position_loss_auto_hedge_manual_release": lambda *a, **k: None,
            "PairExecutionPlan": lambda *a, **k: object(), "PositionSide": lambda x: x,
            "_acquire_aster_account_coordination": calls.lease.acquire,
            "_release_aster_account_coordination": calls.lease.release,
            "time": SimpleNamespace(sleep=lambda x: None),
            "execute_aster_leg": execute,
        })
        exec(code, ns)
        request = SimpleNamespace(confirm=True, side="SHORT", expected_quantity=qty, percentage=percentage,
                                  idempotency_key="k" * 20, bulk_profit_close=bulk)
        return ns["close_one_aster_position"], request, calls, FakeHTTP

    def call(self, **kw):
        fn, request, calls, FakeHTTP = self.build(**kw)
        try:
            return fn("btcusdt", request, {"uid": "u1"}), calls, None
        except FakeHTTP as exc:
            return None, calls, exc

    def assertNoLeak(self, calls):
        self.assertEqual(len(calls.lease.acquired), len(calls.lease.released))
        self.assertIsNone(calls.lease.holder)

    # --- selection / protection -------------------------------------------------
    def test_normal_bulk_short_is_closed(self):
        result, calls, exc = self.call()
        self.assertIsNone(exc)
        self.assertEqual(len(calls.orders), 1)
        self.assertEqual(result["percentage"], 25)
        self.assertFalse(result["protectionChangedDuringClose"])
        self.assertNoLeak(calls)

    def test_auto_hedge_managed_blocked_before_any_order_with_stale_snapshot(self):
        _, calls, exc = self.call(managed=lambda n: True)
        self.assertEqual(exc.status_code, 409)
        self.assertIn("Auto Hedge", exc.detail)
        self.assertEqual(calls.orders, [])
        self.assertTrue(any(c[1].get("status") == "blocked_bulk_protected" for c in calls.intents if c[0] == "set"))
        self.assertNoLeak(calls)

    def test_focus_airbag_blocked(self):
        legs = [{"symbol": "BTCUSDT", "side": "SHORT", "role": "FOCUS_SLOT_AIRBAG:s"}]
        _, calls, exc = self.call(strategy2={"ownedLegs": legs})
        self.assertEqual(calls.orders, [])
        self.assertIn("Focus Airbag", exc.detail)
        self.assertNoLeak(calls)

    def test_missing_protection_status_blocked_not_treated_as_empty(self):
        for state in ({"focusLiveSlots": [{"pair": "ETHUSDT", "side": "LONG"}]}, {"ownedLegs": "garbage"},
                      {"ownedLegs": [{"symbol": "BTCUSDT", "side": "SHORT"}]}):
            _, calls, exc = self.call(strategy2=state)
            self.assertEqual(exc.status_code, 409, state)
            self.assertIn("onbetrouwbaar", exc.detail)
            self.assertEqual(calls.orders, [])
            self.assertTrue(any(c[1].get("status") == "blocked_bulk_unreliable" for c in calls.intents if c[0] == "set"))
            self.assertNoLeak(calls)

    def test_protection_document_unreadable_fails_closed(self):
        _, calls, exc = self.call(strategy2_raises=True)
        self.assertIsNotNone(exc)
        self.assertEqual(calls.orders, [])
        self.assertNoLeak(calls)

    def test_hedge_lock_reader_failure_fails_closed(self):
        def boom(n):
            raise lock.AutoHedgeCloseBlocked({"message": "Auto Hedge-lock kon niet betrouwbaar worden gelezen"})
        with self.assertRaises(lock.AutoHedgeCloseBlocked):
            fn, request, calls, _ = self.build(managed=boom)
            try:
                fn("btcusdt", request, {"uid": "u1"})
            except Exception as exc:
                # the real route converts this to HTTP 409 in its `except AutoHedgeCloseBlocked`
                self.assertEqual(calls.orders, [])
                self.assertNoLeak(calls)
                raise lock.AutoHedgeCloseBlocked({"message": str(exc)}) if not isinstance(exc, lock.AutoHedgeCloseBlocked) else exc

    def test_proven_no_airbag_document_missing_is_allowed(self):
        result, calls, exc = self.call(strategy2_exists=False)
        self.assertIsNone(exc)
        self.assertEqual(len(calls.orders), 1)

    # --- race / synchronisation -------------------------------------------------
    def test_lease_held_during_order_so_auto_hedge_cannot_act(self):
        _, calls, exc = self.call()
        self.assertIsNone(exc)
        self.assertEqual(calls.tick_during_order, "PENDING")     # Auto Hedge saw the lease busy
        self.assertEqual(calls.lease.acquired[0][0], "MANUAL_BULK_PROFIT_CLOSE")
        self.assertNoLeak(calls)
        self.assertEqual(calls.lease.auto_hedge_tick(), "EXECUTED")  # free again afterwards

    def test_account_busy_blocks_without_order(self):
        _, calls, exc = self.call(busy=True)
        self.assertEqual(exc.status_code, 409)
        self.assertIn("bulk sluiten is gestopt", exc.detail)
        self.assertEqual(calls.orders, [])
        self.assertEqual(calls.lease.acquired, [])               # never stole a held lease

    def test_auto_hedge_activates_between_first_check_and_order_is_caught_by_late_check(self):
        _, calls, exc = self.call(managed=lambda n: n >= 2)      # 1st check free, 2nd (late) check managed
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(calls.orders, [])
        self.assertNoLeak(calls)

    def test_protection_taken_during_order_is_reported_not_hidden(self):
        result, calls, exc = self.call(managed=lambda n: n >= 3)  # free for checks 1+2, managed after the order
        self.assertIsNone(exc)
        self.assertEqual(len(calls.orders), 1)
        self.assertTrue(result["protectionChangedDuringClose"])
        self.assertTrue(any(c[1].get("protectionChangedDuringClose") is True for c in calls.intents if c[0] == "set"))
        self.assertNoLeak(calls)

    def test_lease_released_when_order_fails(self):
        def boom():
            raise RuntimeError("exchange timeout")
        fn, request, calls, FakeHTTP = self.build(order_hook=boom)
        with self.assertRaises(FakeHTTP) as ctx:
            fn("btcusdt", request, {"uid": "u1"})
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(len(calls.orders), 1)
        self.assertNoLeak(calls)

    # --- individual close unchanged ----------------------------------------------
    def test_individual_close_unchanged_when_flag_not_set(self):
        result, calls, exc = self.call(managed=lambda n: True, strategy2={"focusLiveSlots": "garbage"}, bulk=False)
        self.assertIsNone(exc)
        self.assertEqual(len(calls.orders), 1)
        self.assertEqual([a for a in calls.lease.acquired if a[0].startswith("MANUAL")], [])  # individual button takes no lease
        self.assertEqual(calls.tick_during_order, "EXECUTED")    # ... so Auto Hedge is not delayed by it (unchanged)
        self.assertEqual(calls.managed_checks, 0)
        self.assertFalse(result["protectionChangedDuringClose"])

    # --- validation / idempotency / quantities -------------------------------------
    def test_stale_quantity_rejected(self):
        _, calls, exc = self.call(qty=5.0)
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(calls.orders, [])

    def test_duplicate_idempotency_key_places_no_second_order(self):
        fn, request, calls, FakeHTTP = self.build()
        already = fn.__globals__["google_exceptions"].AlreadyExists
        fn.__globals__["user_reference"] = lambda user: SimpleNamespace(collection=lambda n: SimpleNamespace(
            document=lambda d: SimpleNamespace(create=mock.Mock(side_effect=already()), set=lambda *a, **k: None)))
        with self.assertRaises(FakeHTTP) as ctx:
            fn("btcusdt", request, {"uid": "u1"})
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(calls.orders, [])
        self.assertEqual(calls.lease.acquired, [])               # rejected before taking the lease

    @unittest.skipUnless(HAVE_GATEWAY, "aster_gateway needs httpx (not installed in this sandbox)")
    def test_percentages_with_real_contract_rules(self):
        captured = {}
        for pct in (25, 50, 75, 100):
            fn, request, calls, _ = self.build(percentage=pct, real_rules=True)
            plans = []
            fn.__globals__["PairExecutionPlan"] = lambda sym, qty, notional, lev, plans=plans: plans.append(qty) or object()
            fn("btcusdt", request, {"uid": "u1"})
            captured[pct] = plans[0]
        self.assertEqual({k: float(v) for k, v in captured.items()}, {25: 2.0, 50: 4.0, 75: 6.0, 100: 8.0})

    @unittest.skipUnless(HAVE_GATEWAY, "aster_gateway needs httpx (not installed in this sandbox)")
    def test_exchange_minimum_filters_reject_without_order(self):
        # minQty 3: 25% of 8 = 2 is below the exchange minimum; 100% (no filter path) is fine
        info = {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "filters": [
            {"filterType": "LOT_SIZE", "minQty": "3", "maxQty": "1000", "stepSize": "1"},
            {"filterType": "MIN_NOTIONAL", "notional": "5"}]}]}
        _, calls, exc = self.call(percentage=25, real_rules=True, info=info)
        self.assertEqual(exc.status_code, 409)
        self.assertIn("contractregels", exc.detail)
        self.assertEqual(calls.orders, [])
        self.assertNoLeak(calls)
        # notional filter: qty 2 * mark 100 = 200 < 1000
        info["symbols"][0]["filters"] = [{"filterType": "LOT_SIZE", "minQty": "1", "maxQty": "1000", "stepSize": "1"},
                                         {"filterType": "MIN_NOTIONAL", "notional": "1000"}]
        _, calls, exc = self.call(percentage=25, real_rules=True, info=info)
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(calls.orders, [])


class RolloutCompatibilityTests(unittest.TestCase):
    """Real pydantic (2.x, as pinned in requirements.txt) against the old and new request models."""
    BODY = {"confirm": True, "side": "SHORT", "expected_quantity": 8.0, "percentage": 25,
            "idempotency_key": "k" * 20, "bulk_profit_close": True}

    def _model(self, src):
        from pydantic import BaseModel, Field
        ns = {"BaseModel": BaseModel, "Field": Field}
        exec(src, ns)
        return ns["AsterManualCloseRequest"]

    def test_old_backend_model_silently_ignores_the_bulk_flag(self):
        old = self._model('''
class AsterManualCloseRequest(BaseModel):
    confirm: bool
    side: str = Field(pattern="^(LONG|SHORT)$")
    expected_quantity: float = Field(gt=0)
    percentage: int = Field(default=100, ge=25, le=100)
    idempotency_key: str = Field(min_length=16, max_length=120)
''')
        parsed = old(**self.BODY)                      # accepted, no error ...
        self.assertFalse(hasattr(parsed, "bulk_profit_close"))   # ... and the flag is dropped = NO server guard
        # => that is why the frontend refuses to run without preview.bulkGuardVersion == 1
        # (web test "old backend ... is refused") and stops when a close response lacks the guard confirmation.

    def test_new_backend_model_parses_flag_and_defaults_false(self):
        tree = ast.parse(MAIN_SRC)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AsterManualCloseRequest")
        new = self._model(ast.unparse(cls))
        self.assertTrue(new(**self.BODY).bulk_profit_close)
        without = {k: v for k, v in self.BODY.items() if k != "bulk_profit_close"}
        self.assertFalse(new(**without).bulk_profit_close)   # individual Close button: flag absent -> False

    def test_preview_advertises_guard_version(self):
        preview = MAIN_SRC[MAIN_SRC.index("def preview_manual_profit_close_plan("):]
        preview = preview[:preview.index('@app.post("/v1/me/aster/positions/close-profitable")')]
        self.assertIn('"bulkGuardVersion": 1', preview)


class SourceContractTests(unittest.TestCase):
    def test_lease_then_guard_before_any_state_change_in_route(self):
        route = MAIN_SRC[MAIN_SRC.index("def close_one_aster_position("):]
        route = route[:route.index('@app.post("/v1/me/aster/simulate")')]
        flag = route.index("if request.bulk_profit_close:")
        lease = route.index('"MANUAL_BULK_PROFIT_CLOSE"')
        guard = route.index("_bulk_profit_close_block_reason_live(uid, normalized_symbol, request.side)")
        self.assertLess(flag, lease)
        self.assertLess(lease, guard)                       # lease first, then check
        for later in ("close_size(live_quantity", "_begin_position_loss_auto_hedge_manual_release(",
                      "begin_manual_action(", "execute_aster_leg("):
            self.assertLess(guard, route.index(later), later)
        late = route.index("late_reason = _bulk_profit_close_block_reason_live")
        self.assertLess(late, route.index("execute_aster_leg("))   # second check right before the order
        self.assertLess(route.index("begin_manual_action("), route.index("execute_aster_leg("))
        self.assertLess(route.index("expected_quantity"), flag)    # after live-quantity check
        self.assertIn("_release_aster_account_coordination(uid, str(account_token))", route.split("finally:")[-1])

    def test_auto_hedge_live_execution_takes_the_same_lease(self):
        src = (HERE / "aster_position_loss_auto_hedge_extension.py").read_text()
        self.assertIn('main._acquire_aster_account_coordination(\n                uid, "AUTO_HEDGE"', src)
        self.assertIn("ACCOUNT_COORDINATION_BUSY", src)
        self.assertIn("main._release_aster_account_coordination(uid, coordination_token)", src)

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
