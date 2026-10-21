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
from manual_profit_close_guard import (BulkProtectionUnreliable, OwnershipContext, bulk_profit_close_block_reason,
                                       focus_airbag_protected)
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


def ctx(**over):
    """OwnershipContext where every system is proven absent/unconfigured unless overridden."""
    base = dict(pair={}, dynamic_hedge=None, dynamic_hedge_exists=False, emergency_hedge=None,
                emergency_hedge_exists=False, auto_hedge_settings=None, auto_hedge_settings_exists=False,
                sniper=None, sniper_exists=False, has_same_symbol_long=False)
    base.update(over)
    return OwnershipContext(**base)


def reason(symbol="BTCUSDT", side="SHORT", state=None, *, exists=True, managed=lambda **_: False, ownership=None):
    state = {"ownedLegs": []} if state is None else state
    return bulk_profit_close_block_reason("u", symbol, side, state, strategy2_exists=exists, managed_check=managed,
                                          ownership=ownership or ctx())


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
    wanted = {"close_one_aster_position", "_bulk_profit_close_block_reason_live", "_bulk_reason_from_globals",
              "_read_bulk_ownership_globals"}
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert len(fns) == 4
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
    """Models the per-account lease (`aster_account_coordination_reference`): exclusive, token based,
    expirable. The REAL acquire/renew/release functions are tested separately (LeaseSemanticsTests)."""
    def __init__(self, busy=False):
        self.holder = "someone" if busy else None
        self.token = None
        self.expired = False
        self.acquired, self.released, self.renewals = [], [], []

    def acquire(self, uid, owner, purpose):
        if self.holder:
            return None
        self.holder = owner
        self.expired = False
        self.acquired.append((owner, purpose))
        self.token = f"token-{len(self.acquired)}"
        return self.token

    def release(self, uid, token):
        self.released.append(token)
        if token == self.token:
            self.holder = None   # stale tokens never release a newer holder's lease

    def renew(self, uid, token):
        ok = bool(token) and token == self.token and not self.expired
        self.renewals.append((token, ok))
        return ok

    def held(self, uid, token):
        return bool(token) and token == self.token and not self.expired

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


class RouteHarness:
    """Runs the REAL close route + protection-read source (ast-extracted from main.py)
    against mocks and a model of the account lease. No FastAPI, no Firestore, no orders."""

    def build(self, *, managed=lambda n: False, strategy2=None, strategy2_exists=True, strategy2_raises=False,
              bulk=True, qty=8.0, percentage=25, busy=False, order_hook=None, info=None, live_qty=8.0,
              real_rules=False, pre_submit_hook=None, docs=None, pair=None, extra_rows=()):
        # docs: {"dynamic"|"emergency"|"settings"|"sniper": dict | FakeDoc}; unset => proven absent
        docs = docs if docs is not None else {}
        pair = {} if pair is None else pair
        code, names = load_route_functions()
        ns = {n: mock.MagicMock(name=n) for n in names if not hasattr(builtins, n)}
        calls = SimpleNamespace(orders=[], intents=[], tick_during_order=None, managed_checks=0, lease=FakeLease(busy))

        class FakeHTTP(Exception):
            def __init__(self, status, detail):
                self.status_code, self.detail = status, detail

        class Intent:
            def create(self, data): calls.intents.append(("create", data))
            def set(self, data, merge=False): calls.intents.append(("set", data))

        live = [{"symbol": "BTCUSDT", "positionSide": "SHORT", "positionAmt": str(-live_qty), "markPrice": "100", "leverage": "5"},
                *extra_rows]

        def doc_for(key):
            value = docs.get(key)
            if isinstance(value, FakeDoc):
                return value
            return FakeDoc(value, exists=value is not None)

        class _Collection:
            def __init__(self, name): self.name = name
            def document(self, d):
                if self.name == "asterDynamicHedge":
                    return doc_for("dynamic")
                return Intent()
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
            if pre_submit_hook:
                pre_submit_hook(calls.lease)          # e.g. the close was slow and the lease expired
            calls.hook(SimpleNamespace(action="CLOSE", symbol="BTCUSDT"))   # gateway: before_order_submit(intent)
            calls.orders.append(k)
            calls.tick_during_order = calls.lease.auto_hedge_tick()
            if order_hook:
                order_hook()
            live[0]["positionAmt"] = str(-(live_qty - close_size(live_qty, percentage) if percentage != 100 else 0.0))
            return {"status": "FILLED"}

        ns.update({
            "HTTPException": FakeHTTP, "AutoHedgeCloseBlocked": lock.AutoHedgeCloseBlocked,
            "BulkProtectionUnreliable": BulkProtectionUnreliable, "OwnershipContext": OwnershipContext,
            "bulk_profit_close_block_reason": bulk_profit_close_block_reason,
            "db": SimpleNamespace(collection=lambda name: SimpleNamespace(
                document=lambda d: doc_for("emergency" if name == "aster_portfolio_emergency_hedges" else "settings"))),
            "aster_sniper_reference": lambda uid: doc_for("sniper"),
            "auto_hedge_symbol_managed_strict": strict_check,
            "aster_strategy2_reference": lambda uid: FakeDoc(strategy2 if strategy2 is not None else {"ownedLegs": []},
                                                             exists=strategy2_exists, raises=strategy2_raises),
            "os": SimpleNamespace(getenv=lambda *a, **k: "true"),
            "hashlib": __import__("hashlib"), "datetime": __import__("datetime").datetime,
            "timezone": __import__("datetime").timezone,
            "google_exceptions": SimpleNamespace(AlreadyExists=type("AlreadyExists", (Exception,), {})),
            "user_reference": lambda user: SimpleNamespace(collection=_Collection),
            "AsterV3Client": lambda **kw: (setattr(calls, "hook", kw["before_order_submit"]) or client),
            "load_aster_secret": lambda u: SimpleNamespace(signer_address="a"),
            "local_eip712_signer": lambda s: None, "_block_order_during_close_all": lambda uid: (lambda intent: None),
            "_renew_aster_account_coordination": calls.lease.renew,
            "_aster_account_coordination_held": calls.lease.held,
            "ALLOWED_CLOSE_PERCENTAGES": ALLOWED_CLOSE_PERCENTAGES, "close_size": close_size,
            "safe_float": lambda v, d=0.0: float(v) if v not in (None, "") else d,
            "Decimal": __import__("decimal").Decimal, "ContractRules": rules, "AsterValidationError": validation_error,
            "_position_loss_auto_hedge_pair": (lambda uid, sym: pair) if not isinstance(pair, Exception) else mock.Mock(side_effect=pair),
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


class RouteBehaviourTests(RouteHarness, unittest.TestCase):
    # --- selection / protection -------------------------------------------------
    def test_normal_bulk_short_is_closed(self):
        result, calls, exc = self.call()
        self.assertIsNone(exc)
        self.assertEqual(len(calls.orders), 1)
        self.assertEqual(result["percentage"], 25)
        self.assertFalse(result["protectionChangedDuringClose"])
        self.assertFalse(result["leaseLostDuringClose"])
        self.assertEqual(calls.lease.renewals, [("token-1", True)])   # fenced exactly once, right before the order
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

    # --- lease expiry / fencing -------------------------------------------------
    def test_delayed_close_with_expired_lease_never_sends_the_order(self):
        _, calls, exc = self.call(pre_submit_hook=lambda lease: setattr(lease, "expired", True))
        self.assertIsNotNone(exc)
        self.assertEqual(exc.status_code, 502)                    # fail closed, no retry
        self.assertEqual(calls.orders, [])
        self.assertEqual(calls.lease.renewals, [("token-1", False)])
        self.assertNoLeak(calls)

    def test_lease_taken_over_by_someone_else_blocks_the_order(self):
        def takeover(lease):
            lease.token = "token-of-someone-else"                 # expired + re-acquired by another worker
        _, calls, exc = self.call(pre_submit_hook=takeover)
        self.assertEqual(calls.orders, [])
        self.assertIsNotNone(exc)

    def test_lease_expiring_during_exchange_verification_is_reported_not_retried(self):
        holder = []
        fn, request, calls, FakeHTTP = self.build(order_hook=lambda: setattr(holder[0].lease, "expired", True))
        holder.append(calls)
        result = fn("btcusdt", request, {"uid": "u1"})
        self.assertEqual(len(calls.orders), 1)                    # exactly one order, never a second
        self.assertTrue(result["leaseLostDuringClose"])
        self.assertTrue(any(c[1].get("leaseLostDuringClose") is True for c in calls.intents if c[0] == "set"))

    def test_unknown_order_status_is_not_retried_and_lease_released(self):
        def boom():
            raise RuntimeError("UNKNOWN order status")
        fn, request, calls, FakeHTTP = self.build(order_hook=boom)
        with self.assertRaises(FakeHTTP) as ctx:
            fn("btcusdt", request, {"uid": "u1"})
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(len(calls.orders), 1)                    # one submit, no automatic second order
        self.assertNoLeak(calls)

    def test_individual_close_has_no_fence_and_no_lease(self):
        result, calls, exc = self.call(bulk=False)
        self.assertIsNone(exc)
        self.assertEqual(calls.lease.renewals, [])

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


# ---------------------------------------------------------------------------------
# ROUND 4: cross-system ownership (Dynamic Hedge, Emergency Hedge, Short Recovery 2.0, in-flight claims)
# ---------------------------------------------------------------------------------
RECOVERY_ON = {"shortRecoveryPlan": {"enabled": True, "version": 2}}


class OwnershipGuardTests(unittest.TestCase):
    def test_all_systems_absent_or_off_allows_plain_short(self):
        self.assertIsNone(reason(ownership=ctx()))
        self.assertIsNone(reason(ownership=ctx(
            dynamic_hedge={"enabled": False}, dynamic_hedge_exists=True,
            emergency_hedge={"status": "OFF"}, emergency_hedge_exists=True,
            auto_hedge_settings={"enabled": True}, auto_hedge_settings_exists=True,
            sniper={"activeTrades": [], "pendingIntent": None}, sniper_exists=True)))

    def test_dynamic_hedge_enabled_blocks_and_malformed_fails_closed(self):
        self.assertIn("Dynamic Hedge", reason(ownership=ctx(dynamic_hedge={"enabled": True}, dynamic_hedge_exists=True)))
        self.assertIn("Dynamic Hedge", reason(ownership=ctx(
            dynamic_hedge={"enabled": False, "ownershipState": "MANUAL_ACTION_LOCK"}, dynamic_hedge_exists=True)))
        for bad in ("x", {"enabled": "yes"}, None):
            with self.assertRaises(BulkProtectionUnreliable, msg=repr(bad)):
                reason(ownership=ctx(dynamic_hedge=bad, dynamic_hedge_exists=True))

    def test_emergency_hedge_blocking_statuses(self):
        for status in ("EXECUTING", "LOCKED"):
            self.assertIn("Noodhedge", reason(ownership=ctx(emergency_hedge={"status": status}, emergency_hedge_exists=True)))
        for status in ("OFF", "ARMED"):
            self.assertIsNone(reason(ownership=ctx(emergency_hedge={"status": status}, emergency_hedge_exists=True)))
        for bad in ({"status": "WHATEVER"}, {"status": 5}, "x"):
            with self.assertRaises(BulkProtectionUnreliable, msg=repr(bad)):
                reason(ownership=ctx(emergency_hedge=bad, emergency_hedge_exists=True))

    def test_recovery_cycle_fields_in_pair_block(self):
        for pair in ({"state": "PARTIAL"}, {"state": "FINAL_PENDING"}, {"ownerSide": "SHORT", "cycleConfirmed": True}):
            self.assertIn("Short Recovery 2.0", reason(ownership=ctx(pair=pair)), pair)
        self.assertIsNone(reason(ownership=ctx(pair={"ownerSide": "SHORT", "cycleConfirmed": False})))
        with self.assertRaises(BulkProtectionUnreliable):
            reason(ownership=ctx(pair={"state": 7}))
        with self.assertRaises(BulkProtectionUnreliable):
            reason(ownership=ctx(pair="garbage"))

    def test_recovery_plan_enabled_blocks_only_shorts_with_same_symbol_long(self):
        on = dict(auto_hedge_settings=RECOVERY_ON, auto_hedge_settings_exists=True)
        self.assertIn("Short Recovery 2.0", reason(ownership=ctx(has_same_symbol_long=True, **on)))
        self.assertIsNone(reason(ownership=ctx(has_same_symbol_long=False, **on)))   # lone SHORT: plain profit close
        off = dict(auto_hedge_settings={"shortRecoveryPlan": {"enabled": False}}, auto_hedge_settings_exists=True)
        self.assertIsNone(reason(ownership=ctx(has_same_symbol_long=True, **off)))   # Classic: unchanged

    def test_invalid_recovery_settings_fail_closed(self):
        for plan in ({"enabled": "maybe"}, "garbage"):
            with self.assertRaises(BulkProtectionUnreliable, msg=repr(plan)):
                reason(ownership=ctx(auto_hedge_settings={"shortRecoveryPlan": plan},
                                     auto_hedge_settings_exists=True, has_same_symbol_long=True))

    def test_inflight_strategy2_and_sniper_claims_block_only_their_symbol(self):
        s2 = {"ownedLegs": [], "pendingReopens": [{"symbol": "BTCUSDT"}]}
        self.assertIn("order in uitvoering", reason(state=s2))
        self.assertIsNone(reason("ETHUSDT", state=s2))
        s2 = {"ownedLegs": [], "orderQueueState": {"currentIntent": {"symbol": "btcusdt"}}}
        self.assertIn("order in uitvoering", reason(state=s2))
        sn = ctx(sniper={"activeTrades": [{"symbol": "BTCUSDT"}]}, sniper_exists=True)
        self.assertIn("Sniper", reason(ownership=sn))
        sn = ctx(sniper={"pendingIntent": {"symbol": "BTCUSDT"}}, sniper_exists=True)
        self.assertIn("Sniper", reason(ownership=sn))
        self.assertIsNone(reason("ETHUSDT", ownership=sn))
        for bad in ({"ownedLegs": [], "pendingReopens": "x"}, {"ownedLegs": [], "pendingReopens": ["x"]},
                    {"ownedLegs": [], "orderQueueState": "x"}):
            with self.assertRaises(BulkProtectionUnreliable, msg=repr(bad)):
                reason(state=bad)
        with self.assertRaises(BulkProtectionUnreliable):
            reason(ownership=ctx(sniper="x", sniper_exists=True))

    def test_protected_reasons_share_the_frontend_marker(self):
        samples = [
            reason(ownership=ctx(dynamic_hedge={"enabled": True}, dynamic_hedge_exists=True)),
            reason(ownership=ctx(emergency_hedge={"status": "LOCKED"}, emergency_hedge_exists=True)),
            reason(ownership=ctx(pair={"state": "PARTIAL"})),
            reason(state={"ownedLegs": [], "pendingReopens": [{"symbol": "BTCUSDT"}]}),
        ]
        for text in samples:
            self.assertIn("bulk Close Profits sluit haar niet", text)

    def test_long_is_never_bulk_closed(self):
        self.assertIn("SHORT", reason(side="LONG", ownership=ctx(has_same_symbol_long=True)))


class OwnershipRouteTests(RouteHarness, unittest.TestCase):
    """Real route + real live-read helpers; ownership documents come from the fake Firestore."""

    def assertBlocked(self, **kw):
        _, calls, exc = self.call(**kw)
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(calls.orders, [])
        self.assertNoLeak(calls)
        return exc, calls

    def test_dynamic_hedge_enabled_blocks_before_any_order(self):
        exc, calls = self.assertBlocked(docs={"dynamic": {"enabled": True}})
        self.assertIn("Dynamic Hedge", exc.detail)
        self.assertTrue(any(c[1].get("status") == "blocked_bulk_protected" for c in calls.intents if c[0] == "set"))

    def test_emergency_hedge_locked_blocks(self):
        exc, _ = self.assertBlocked(docs={"emergency": {"status": "EXECUTING"}})
        self.assertIn("Noodhedge", exc.detail)

    def test_recovery_pair_state_blocks(self):
        exc, _ = self.assertBlocked(pair={"state": "PARTIAL", "ownerSide": "SHORT", "cycleConfirmed": True})
        self.assertIn("Short Recovery 2.0", exc.detail)

    def test_recovery_plan_blocks_hedged_short_but_not_lone_short(self):
        long_row = {"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "8", "markPrice": "100", "leverage": "5"}
        exc, _ = self.assertBlocked(docs={"settings": RECOVERY_ON}, extra_rows=[long_row])
        self.assertIn("Short Recovery 2.0", exc.detail)
        result, calls, exc = self.call(docs={"settings": RECOVERY_ON})
        self.assertIsNone(exc)
        self.assertEqual(len(calls.orders), 1)

    def test_unreadable_ownership_documents_fail_closed(self):
        for key in ("dynamic", "emergency", "settings", "sniper"):
            _, calls, exc = self.call(docs={key: FakeDoc(None, raises=True)})
            self.assertEqual(exc.status_code, 409, key)
            self.assertIn("onbetrouwbaar", exc.detail)
            self.assertEqual(calls.orders, [])
            self.assertNoLeak(calls)
        _, calls, exc = self.call(pair=RuntimeError("boom"))
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(calls.orders, [])

    def test_ownership_change_between_first_check_and_order_is_caught_by_late_check(self):
        state = {"n": 0}

        class Flip(FakeDoc):
            def get(self_inner):
                state["n"] += 1                                  # 1st read free, later reads Dynamic Hedge ON
                self_inner._data = {"enabled": state["n"] >= 2}
                return self_inner
        _, calls, exc = self.call(docs={"dynamic": Flip({"enabled": False})})
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(calls.orders, [])
        self.assertNoLeak(calls)

    def test_individual_close_ignores_all_ownership_documents(self):
        result, calls, exc = self.call(bulk=False, docs={"dynamic": {"enabled": True}, "emergency": {"status": "LOCKED"}},
                                       pair={"state": "PARTIAL"})
        self.assertIsNone(exc)
        self.assertEqual(len(calls.orders), 1)

    def test_guard_reads_are_read_only(self):
        src = MAIN_SRC[MAIN_SRC.index("def _read_bulk_ownership_globals("):MAIN_SRC.index("def _profitable_aster_close_candidates(")]
        for forbidden in (".set(", ".update(", ".create(", ".delete(", "transaction", "batch(", "merge="):
            self.assertNotIn(forbidden, src)


# ---------------------------------------------------------------------------------
# REAL lease functions from main.py against an in-memory Firestore model, real threads, fake clock
# ---------------------------------------------------------------------------------
import copy
import threading
from datetime import datetime as _real_datetime, timedelta, timezone

LEASE_FUNCS = ("_acquire_aster_account_coordination", "_release_aster_account_coordination",
               "_renew_aster_account_coordination", "_aster_account_coordination_held")


class _Clock:
    def __init__(self):
        self.now = _real_datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class _Meta(type(_real_datetime)):
    def __instancecheck__(cls, instance):
        return isinstance(instance, _real_datetime)


def _deep_merge(base, patch):
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)          # Firestore set(..., merge=True) merges nested maps
        else:
            base[key] = copy.deepcopy(value)


class _Snapshot:
    def __init__(self, data):
        self._data = copy.deepcopy(data)

    def to_dict(self):
        return copy.deepcopy(self._data)


class _Ref:
    def __init__(self, store):
        self.store = store

    def get(self, transaction=None):
        return _Snapshot(self.store.data)


class _Txn:
    def set(self, ref, data, merge=False):
        if merge:
            _deep_merge(ref.store.data, data)
        else:
            ref.store.data = copy.deepcopy(data)


class _Store:
    def __init__(self):
        self.data = {}
        self.mutex = threading.RLock()


def load_lease_functions(clock, store):
    tree = ast.parse(MAIN_SRC)
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in LEASE_FUNCS:
            nodes.append(node)
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "ACCOUNT_COORDINATION_LEASE_SECONDS" for t in node.targets):
            nodes.append(node)
    assert len(nodes) == len(LEASE_FUNCS) + 1, [getattr(n, "name", "assign") for n in nodes]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)

    class FakeDT(_real_datetime, metaclass=_Meta):
        @classmethod
        def now(cls, tz=None):
            return clock.now

    def transactional(fn):
        def run(txn):
            with store.mutex:                      # serializable transaction
                return fn(txn)
        return run

    ns = {
        "datetime": FakeDT, "timezone": timezone, "timedelta": timedelta,
        "python_secrets": SimpleNamespace(token_hex=lambda n: __import__("secrets").token_hex(n)),
        "aster_account_coordination_reference": lambda uid: _Ref(store),
        "db": SimpleNamespace(transaction=lambda: _Txn()),
        "firestore": SimpleNamespace(transactional=transactional),
    }
    exec(compile(module, "main.py::lease", "exec"), ns)
    return SimpleNamespace(**{n: ns[n] for n in LEASE_FUNCS}, seconds=ns["ACCOUNT_COORDINATION_LEASE_SECONDS"])


class LeaseSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.store = _Clock(), _Store()
        self.lease = load_lease_functions(self.clock, self.store)

    def acquire(self, owner="W"):
        return self.lease._acquire_aster_account_coordination("u", owner, "P")

    def test_ttl_constant_is_45(self):
        self.assertEqual(self.lease.seconds, 45)

    def test_concurrent_acquire_has_exactly_one_winner(self):
        winners, barrier = [], threading.Barrier(16)

        def worker(i):
            barrier.wait()
            token = self.acquire(f"w{i}")
            if token:
                winners.append(token)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(winners), 1)

    def test_expiry_takeover_and_stale_holder_is_fenced_out(self):
        old = self.acquire("AUTO_HEDGE")
        self.clock.advance(44)
        self.assertIsNone(self.acquire("BULK"))                      # still held at 44 s
        self.clock.advance(2)                                        # 46 s: expired
        self.assertFalse(self.lease._aster_account_coordination_held("u", old))
        self.assertFalse(self.lease._renew_aster_account_coordination("u", old))   # no resurrection, nobody took it yet
        new = self.acquire("BULK")
        self.assertTrue(new)
        self.assertFalse(self.lease._renew_aster_account_coordination("u", old))   # taken over -> fenced
        self.assertFalse(self.lease._aster_account_coordination_held("u", old))
        self.lease._release_aster_account_coordination("u", old)                   # stale release is a no-op
        self.assertTrue(self.lease._aster_account_coordination_held("u", new))
        self.assertIsNone(self.acquire("THIRD"))

    def test_renew_extends_ownership_beyond_original_ttl(self):
        token = self.acquire()
        self.clock.advance(30)
        self.assertTrue(self.lease._renew_aster_account_coordination("u", token))
        self.clock.advance(30)                                       # 60 s after acquire, 30 s after renew
        self.assertTrue(self.lease._aster_account_coordination_held("u", token))
        self.assertIsNone(self.acquire("OTHER"))
        self.clock.advance(16)                                       # 46 s after renew
        self.assertFalse(self.lease._aster_account_coordination_held("u", token))

    def test_crash_recovery_after_ttl_without_release(self):
        self.acquire("CRASHED_WORKER")                               # never released
        self.assertIsNone(self.acquire("RESTARTED"))
        self.clock.advance(46)
        self.assertTrue(self.acquire("RESTARTED"))

    def test_release_then_reacquire_and_empty_token_never_holds(self):
        token = self.acquire()
        self.lease._release_aster_account_coordination("u", token)
        self.assertFalse(self.lease._aster_account_coordination_held("u", token))
        self.assertTrue(self.acquire("NEXT"))
        self.assertFalse(self.lease._renew_aster_account_coordination("u", ""))
        self.assertFalse(self.lease._aster_account_coordination_held("u", ""))

    def test_concurrent_renew_and_takeover_never_both_succeed(self):
        for _ in range(20):
            store = _Store()
            lease = load_lease_functions(self.clock, store)
            old = lease._acquire_aster_account_coordination("u", "A", "P")
            self.clock.advance(46)
            results, barrier = {}, threading.Barrier(2)

            def renew():
                barrier.wait()
                results["renew"] = lease._renew_aster_account_coordination("u", old)

            def take():
                barrier.wait()
                results["take"] = lease._acquire_aster_account_coordination("u", "B", "P")
            t1, t2 = threading.Thread(target=renew), threading.Thread(target=take)
            t1.start(); t2.start(); t1.join(); t2.join()
            self.assertFalse(results["renew"])                       # expired lease can only be taken over
            self.assertTrue(results["take"])


# ---------------------------------------------------------------------------------
# REAL Auto Hedge _run_uid / _client source: lease before any state read or mutation
# ---------------------------------------------------------------------------------
AH_SRC = (HERE / "aster_position_loss_auto_hedge_extension.py").read_text()


def load_auto_hedge(execute=True, busy=False, renew_ok=True, prepare_raises=False):
    tree = ast.parse(AH_SRC)
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"_run_uid", "_client"}]
    assert len(fns) == 2
    for fn in fns:
        fn.decorator_list = []
    module = ast.Module(body=fns, type_ignores=[])
    ast.fix_missing_locations(module)
    names = {n.id for f in fns for n in ast.walk(f) if isinstance(n, ast.Name)}
    events = []
    lease = FakeLease(busy)
    hooks = {}

    class Done(Exception):
        pass

    def rec(name, value=None):
        def f(*a, **k):
            events.append(name)
            if name == "_prepare_lifecycle" and prepare_raises:
                raise Done("boom")
            return value
        return f

    main = SimpleNamespace(
        _release_feature_enabled_for_uid=lambda uid, feature: True,
        _acquire_aster_account_coordination=lambda uid, o, p: (events.append("acquire") or lease.acquire(uid, o, p)),
        _renew_aster_account_coordination=lambda uid, token: (events.append("renew") or (renew_ok and lease.renew(uid, token))),
        _release_aster_account_coordination=lambda uid, token: (events.append("release") or lease.release(uid, token)),
        _block_order_during_close_all=lambda uid, allow_auto_hedge_locked=False: (lambda intent: None),
        load_aster_secret=lambda user: SimpleNamespace(signer_address="a"),
        local_eip712_signer=lambda s: None,
        AsterValidationError=ValueError,
        AsterV3Client=lambda **kw: (hooks.update(kw) or events.append("_client") or SimpleNamespace(
            position_risk=lambda: [], open_orders=lambda: [])),
    )
    ns = {n: mock.MagicMock(name=n) for n in names if not hasattr(builtins, n)}
    ns.update({
        "main": main, "EXECUTION_ENABLED": True, "datetime": __import__("datetime").datetime,
        "timezone": timezone, "os": SimpleNamespace(getenv=lambda *a, **k: "false"),
        "_pair_states": lambda uid: {}, "ACTIVE_STATUSES": {"HEDGING", "HEDGED"},
        "_current": lambda uid: {"enabled": True, "thresholdUsd": 10.0},
        "_doc": lambda uid: SimpleNamespace(set=lambda *a, **k: events.append("doc.set")),
        "_prepare_lifecycle": rec("_prepare_lifecycle", ({}, set(), {}, [])),
        "_dynamic_hedge_enabled": lambda uid: False,
        "reconcile_auto_hedge": rec("reconcile_auto_hedge", SimpleNamespace(ordersSent=0, actions=[])),
        "_sync_pair_views": rec("_sync_pair_views"),
        "_serialize": lambda v: v,
        "Any": object,
    })
    exec(compile(module, "auto_hedge::_run_uid", "exec"), ns)
    return ns, events, lease, hooks


class AutoHedgeLeaseOrderTests(unittest.TestCase):
    def run_uid(self, **kw):
        ns, events, lease, hooks = load_auto_hedge(**kw)
        try:
            ns["_run_uid"]("u1", force_shadow=False)
        except Exception:
            pass
        return events, lease, hooks, ns

    def test_lease_is_acquired_before_any_read_or_state_mutation(self):
        events, lease, _, _ = self.run_uid()
        self.assertIn("_prepare_lifecycle", events)
        self.assertLess(events.index("acquire"), events.index("_client"))
        self.assertLess(events.index("acquire"), events.index("_prepare_lifecycle"))
        self.assertLess(events.index("_prepare_lifecycle"), events.index("renew"))
        self.assertLess(events.index("renew"), events.index("reconcile_auto_hedge"))
        self.assertEqual(events[-1], "release")                      # released after everything, in finally
        self.assertEqual(len(lease.acquired), len(lease.released))

    def test_busy_lease_defers_everything_no_state_write_no_client_no_order(self):
        events, lease, _, _ = self.run_uid(busy=True)
        for forbidden in ("_client", "_prepare_lifecycle", "reconcile_auto_hedge", "_sync_pair_views", "release"):
            self.assertNotIn(forbidden, events)

    def test_lease_released_when_lifecycle_preparation_crashes(self):
        events, lease, _, _ = self.run_uid(prepare_raises=True)
        self.assertEqual(events.count("release"), 1)
        self.assertNotIn("reconcile_auto_hedge", events)
        self.assertIsNone(lease.holder)

    def test_lost_lease_before_reconcile_blocks_orders(self):
        events, lease, _, _ = self.run_uid(renew_ok=False)
        self.assertNotIn("reconcile_auto_hedge", events)
        self.assertIn("release", events)

    def test_every_auto_hedge_order_is_fenced_by_the_lease(self):
        events, lease, hooks, _ = self.run_uid()
        guard = hooks["before_order_submit"]
        guard(SimpleNamespace(action="OPEN"))                        # lease valid -> allowed
        lease.expired = True
        with self.assertRaises(ValueError):
            guard(SimpleNamespace(action="OPEN"))                    # lease lost -> order blocked

    def test_shadow_mode_is_unchanged_no_lease_no_fence(self):
        ns, events, lease, hooks = load_auto_hedge()
        ns["EXECUTION_ENABLED"] = True
        try:
            ns["_run_uid"]("u1", force_shadow=True)
        except Exception:
            pass
        self.assertNotIn("acquire", events)
        self.assertNotIn("renew", events)
        guard = hooks["before_order_submit"]
        guard(SimpleNamespace(action="OPEN"))                        # no lease configured -> no fence


# ---------------------------------------------------------------------------------
# Focus Airbag canonical contract: scan ALL writers (fails when a new writer appears)
# ---------------------------------------------------------------------------------
class FocusAirbagContractScanTests(unittest.TestCase):
    FOCUS = {"focusLiveSlots", "focusLiveState", "focusCycleState", "focusV2State"}
    # Known writers that set focus state WITHOUT ownedLegs in the same write (merge updates).
    # The guard treats "focus keys present but ownedLegs missing" as UNRELIABLE (fail closed).
    KNOWN_WITHOUT_OWNED_LEGS = {("aster_strategy2_focus_live.py", "focusCycleState"),
                                ("aster_strategy2_focus_live.py", "focusLiveState"),
                                ("aster_strategy2_focus_v2.py", "focusV2State")}

    def writers(self):
        for path in sorted(HERE.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in {"set", "update", "create"} and node.args):
                    first = node.args[0]
                    if isinstance(first, ast.Dict):
                        keys = {k.value for k in first.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                        yield path.name, keys
                    elif any(isinstance(x, ast.Constant) and x.value in self.FOCUS for x in ast.walk(first)):
                        yield path.name, {"<NON-LITERAL>"}

    def test_no_unreviewed_writer_of_focus_state(self):
        for name, keys in self.writers():
            self.assertNotIn("<NON-LITERAL>", keys, f"{name}: non-literal write of focus state needs review")
            for focus_key in keys & self.FOCUS:
                if "ownedLegs" not in keys:
                    self.assertIn((name, focus_key), self.KNOWN_WITHOUT_OWNED_LEGS, f"{name} writes {focus_key} without ownedLegs")

    def test_airbag_role_is_only_created_by_focus_multi_and_only_persisted_in_owned_legs(self):
        creators = [p.name for p in sorted(HERE.glob("*.py")) if not p.name.startswith("test_")
                    and p.name not in {"main.py", "manual_profit_close_guard.py"} and "FOCUS_SLOT_AIRBAG" in p.read_text()]
        self.assertEqual(creators, ["aster_strategy2_focus_multi.py"])
        # main.py only filters/reads/labels the role (never assigns it to ownedLegs)
        for line in MAIN_SRC.splitlines():
            if "FOCUS_SLOT_AIRBAG" in line:
                self.assertTrue(any(w in line for w in ("startswith", "return f", "role")), line)

    def test_focus_keys_without_owned_legs_is_unreliable_per_guard(self):
        for key in self.FOCUS:
            with self.assertRaises(BulkProtectionUnreliable):
                focus_airbag_protected({key: {}}, exists=True, symbol="BTCUSDT", side="SHORT")

    def test_strategy2_management_holds_the_same_lease_so_airbag_cannot_change_mid_close(self):
        # realtime strategy-2/airbag management takes the account lease (main.py REALTIME_MANAGEMENT)
        self.assertIn('_acquire_aster_account_coordination(uid,"ASTER","REALTIME_MANAGEMENT")', MAIN_SRC)
        self.assertIn('_acquire_aster_account_coordination(uid,"ASTER","SCHEDULER")', MAIN_SRC)


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
        guard = route.index("_bulk_profit_close_block_reason_live(uid, normalized_symbol, request.side, user, live_rows)")
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
        self.assertIn("_bulk_reason_from_globals", preview)          # same guard as the route
        self.assertIn("_read_bulk_ownership_globals", preview)
        self.assertEqual(MAIN_SRC.count('"/v1/me/aster/positions/{symbol}/close"'), 1)
        self.assertNotIn("bulk-close", MAIN_SRC.lower().replace("bulk_close", ""))

    def test_no_order_submission_in_preview(self):
        preview = MAIN_SRC[MAIN_SRC.index("def preview_manual_profit_close_plan("):]
        preview = preview[:preview.index('@app.post("/v1/me/aster/positions/close-profitable")')]
        for forbidden in ("execute_aster_leg", "submit_order", "live=True"):
            self.assertNotIn(forbidden, preview)


if __name__ == "__main__":
    unittest.main()
