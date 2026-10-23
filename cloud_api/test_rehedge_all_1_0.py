"""Re-Hedge All 1.0 — model tests of the REAL Auto Hedge extension + engine.

Real: aster_position_loss_auto_hedge_extension (new route + lifecycle), aster_position_loss_auto_hedge (engine,
untouched), ContractRules, the account-lease functions and the individual close route from main.py (via the Close
Profits offline harness). Mocked: Firestore (in-memory model; the emulator variant swaps in a real client), Aster
(ledger with scriptable fills). No network, no credentials, no orders. Model tests, not proof against real Aster.
"""
from __future__ import annotations

import importlib.util
import random
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).parent

try:
    import offline_close_harness as H
    from fastapi import HTTPException, Response
    HAVE = True
except Exception:  # pragma: no cover  (needs fastapi + aster_gateway deps)
    HAVE = False


class HedgeClient:
    """Aster position/order API as used by the Auto Hedge engine, on top of the harness ledger."""

    def __init__(self, ledger):
        self.L = ledger

    def position_risk(self):
        if self.L.on_before_read:
            self.L.on_before_read()
        rows = self.L.rows()
        for row in rows:
            row["entryPrice"] = str(self.L.entry[(row["symbol"], row["positionSide"])])
        return rows

    def open_orders(self):
        return [dict(row) for row in self.L.open_order_rows]

    def position_mode(self):
        return True

    def public_exchange_info(self):
        return self.L.exchange_info()

    def account_information(self):
        return {"availableBalance": str(self.L.available)}

    def submit_order_once(self, intent, *, config, confirm, hedge_mode_confirmed, risk_approved):
        sym, side, qty, action = intent.symbol, intent.position_side.value, float(intent.quantity), intent.action
        if self.L.on_before_order:
            self.L.on_before_order(sym)
        mode = self.L.hedge_modes.get(sym, "ok")
        if mode == "reject":
            raise RuntimeError("Aster rejected the order before acceptance")
        if mode == "margin":
            raise RuntimeError("Margin is insufficient (-2019)")
        filled = qty * (self.L.partial_ratio if mode == "partial" else 1.0)
        key = (sym, side)
        self.L.entry.setdefault(key, self.L.mark[sym])
        before = self.L.pos.get(key, 0.0)
        self.L.pos[key] = before + filled if action == "OPEN" else max(0.0, before - filled)
        self.L.hedge_orders.append({"symbol": sym, "positionSide": side, "action": action, "qty": qty,
                                    "filled": filled, "id": intent.intent_id})
        status = "PARTIALLY_FILLED" if filled < qty else "FILLED"
        self.L.order_log[intent.intent_id] = {"symbol": sym, "executed": filled, "status": status}
        if mode == "partial":
            self.L.hedge_modes[sym] = "ok"                     # the next attempt fills normally
        if mode == "timeout":
            self.L.hedge_modes[sym] = "ok"
            raise ConnectionError("read timeout after Aster accepted the order")
        return {"orderId": len(self.L.hedge_orders), "status": status, "executedQty": str(filled)}, False

    def query_order(self, symbol, intent_id):
        row = self.L.order_log.get(intent_id)
        if not row:
            raise RuntimeError("Order does not exist (-2013)")
        return {"orderId": 1, "status": row["status"], "executedQty": str(row["executed"])}


class _App:
    def __getattr__(self, name):
        return lambda *a, **k: (lambda fn: fn)


def load_extension(fs, ledger, real=None):
    _, ns, _ = H.build_backend(ledger, fs, real=real)
    entitled = {"auto_hedge_v2"}
    fake_main = SimpleNamespace(
        app=_App(), db=fs, user_reference=ns.user_reference,
        _acquire_aster_account_coordination=ns._acquire_aster_account_coordination,
        _release_aster_account_coordination=ns._release_aster_account_coordination,
        require_release_feature=lambda user, key: user["uid"],
        authenticated_user=None,
        _release_feature_enabled_for_uid=lambda uid, key: key in entitled,
        load_aster_secret=lambda user: SimpleNamespace(signer_address="a"),
        local_eip712_signer=lambda secret: None,
        AsterV3Client=lambda **kwargs: HedgeClient(ledger),
        _block_order_during_close_all=lambda uid, allow_auto_hedge_locked=False: (lambda intent: None),
    )
    previous = sys.modules.get("main")
    sys.modules["main"] = fake_main
    try:
        spec = importlib.util.spec_from_file_location(
            "rehedge_ext_under_test", HERE / "aster_position_loss_auto_hedge_extension.py")
        ext = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ext)
    finally:
        if previous is None:
            sys.modules.pop("main", None)
        else:
            sys.modules["main"] = previous
    ext.EXECUTION_ENABLED = True
    return ext, ns


def recovery_pair(symbol, survivor="LONG", status="RECOVERY", **extra):
    return {"symbol": symbol, "status": status, "protectedSide": "SHORT" if survivor == "LONG" else "LONG",
            "hedgeSide": survivor, "generation": 1, "generationId": "g1", "rehedgeEnabled": False, **extra}


@unittest.skipUnless(HAVE, "needs fastapi + aster_gateway deps")
class Base(unittest.TestCase):
    EMULATOR = False

    def make_store(self):
        self.uid = "u1"
        return H.FakeFirestore(), None

    def setUp(self):
        self.fs, real = self.make_store()
        self.L = H.Ledger(self.fs)
        self.L.open_order_rows, self.L.hedge_orders, self.L.hedge_modes = [], [], {}
        self.L.available = 1_000_000.0
        self.ext, self.ns = load_extension(self.fs, self.L, real=real)
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": True, "thresholdUsd": 10.0})

    # --- store helpers (model and emulator) -------------------------------------------------------------
    def get(self, *path):
        if self.EMULATOR:
            snap = self.fs.document("/".join(path)).get()
            return snap.to_dict() if snap.exists else None
        return self.fs.docs.get(path)

    def put(self, *path_and_data):
        *path, data = path_and_data
        if self.EMULATOR:
            self.fs.document("/".join(path)).set(data)
        else:
            self.fs.docs[tuple(path)] = data

    def seed(self, symbol, long_qty, short_qty=0.0, mark=15.0, pair=None, uid=None, **ledger):
        self.L.add(symbol, "LONG", long_qty, mark=mark, **ledger)            # LONG entry below mark: in PROFIT
        if short_qty:
            self.L.pos[(symbol, "SHORT")] = float(short_qty)
            self.L.entry[(symbol, "SHORT")] = mark + 1
        self.put("asterPositionLossAutoHedge", uid or self.uid, "pairs", symbol, pair or recovery_pair(symbol))

    def pair(self, symbol, uid=None):
        return self.get("asterPositionLossAutoHedge", uid or self.uid, "pairs", symbol) or {}

    def press(self, uid=None, confirm=True):
        return self.ext.post_position_loss_auto_hedge_rehedge_all(
            self.ext.RehedgeAllRequest(confirm=confirm, clientBuild="606"), Response(), {"uid": uid or self.uid},
        )["rehedgeAll"]

    def worker_tick(self, uid=None):
        return self.ext._run_uid(uid or self.uid)

    def item(self, result, symbol):
        return next(row for row in result["items"] if row["symbol"] == symbol)

    def long(self, s): return self.L.pos.get((s, "LONG"), 0.0)
    def short(self, s): return self.L.pos.get((s, "SHORT"), 0.0)

    def assert_invariant(self):
        for (symbol, side), qty in self.L.pos.items():
            if side == "SHORT":
                self.assertLessEqual(qty, self.long(symbol) + 1e-9, f"{symbol}: SHORT {qty} > LONG {self.long(symbol)}")
        for order in self.L.hedge_orders:                                       # never a LONG order, never a SHORT close
            self.assertEqual((order["positionSide"], order["action"]), ("SHORT", "OPEN"), order)

    def lease_free(self):
        lease = (self.get("asterAccountCoordination", self.uid) or {}).get("lease") or {}
        return not lease.get("token")


class SizingTests(Base):
    def test_single_recovery_long_in_profit_is_hedged_immediately_to_its_live_quantity(self):
        self.seed("ICPUSDT", 10.0)                                              # $150 LONG, no SHORT, LONG in profit
        result = self.press()
        self.assertEqual([(o["symbol"], o["qty"]) for o in self.L.hedge_orders], [("ICPUSDT", 10.0)])
        row = self.item(result, "ICPUSDT")
        self.assertEqual(row["outcome"], "PROTECTED")
        self.assertAlmostEqual(row["longNotional"], 150.0)
        self.assertAlmostEqual(row["shortNotionalBefore"], 0.0)
        self.assertAlmostEqual(row["shortNotionalAfter"], 150.0)
        self.assertAlmostEqual(row["hedgePercent"], 100.0)
        self.assertEqual(self.long("ICPUSDT"), 10.0)                            # LONG untouched
        self.assertEqual(self.pair("ICPUSDT")["status"], "HEDGED")
        self.assertEqual(self.pair("ICPUSDT")["protectedSide"], "LONG")
        self.assertEqual(self.pair("ICPUSDT")["triggerReason"], "USER_REHEDGE_ALL")
        self.assertTrue(self.lease_free())
        self.assert_invariant()

    def test_existing_partial_short_is_counted_example_b(self):
        self.seed("INJUSDT", 10.0, short_qty=40 / 15)                           # $150 LONG, $40 SHORT
        self.L.pos[("INJUSDT", "SHORT")] = round(40 / 15, 3)
        self.press()
        self.assertAlmostEqual(self.L.hedge_orders[0]["qty"], 10.0 - round(40 / 15, 3), places=9)
        self.assertAlmostEqual(self.short("INJUSDT"), 10.0, places=9)
        self.assert_invariant()

    def test_dca_grown_long_uses_the_live_size_not_history_example_d(self):
        self.seed("KORUUSDT", 27.5, short_qty=7.5, mark=10.0,
                  pair=recovery_pair("KORUUSDT", currentProtectedQty=3.0, preExistingOppositeQty=3.0, triggerPnl=-30))
        self.press()
        self.assertAlmostEqual(self.L.hedge_orders[0]["qty"], 20.0)             # $275 - $75 = $200
        self.assertAlmostEqual(self.short("KORUUSDT"), 27.5)
        self.assert_invariant()

    def test_multiple_pairs_each_get_exactly_their_own_gap(self):
        self.seed("AAAUSDT", 10.0)
        self.seed("BBBUSDT", 4.0, short_qty=1.0)
        self.seed("CCCUSDT", 2.5, short_qty=2.5)                               # already exact: no order
        result = self.press()
        self.assertEqual(sorted((o["symbol"], o["qty"]) for o in self.L.hedge_orders), [("AAAUSDT", 10.0), ("BBBUSDT", 3.0)])
        self.assertEqual({r["symbol"]: r["outcome"] for r in result["items"]},
                         {"AAAUSDT": "PROTECTED", "BBBUSDT": "PROTECTED", "CCCUSDT": "PROTECTED"})
        self.assertEqual(result["found"], 3)
        self.assertEqual(result["ordersSent"], 2)
        self.assert_invariant()

    def test_pending_short_order_is_counted(self):
        self.seed("NATGASUSDT", 10.0, short_qty=2.0)
        self.L.open_order_rows.append({"symbol": "NATGASUSDT", "positionSide": "SHORT", "side": "SELL",
                                       "origQty": "3", "executedQty": "0", "status": "NEW"})
        result = self.press()
        self.assertEqual([o["qty"] for o in self.L.hedge_orders], [5.0])        # 10 - 2 - 3 pending
        self.assertEqual(self.item(result, "NATGASUSDT")["outcome"], "PENDING")  # waits for the open order
        self.assert_invariant()

    def test_over_hedged_pair_is_skipped_and_reported_without_any_order(self):
        self.seed("INTCUSDT", 10.0, short_qty=12.0)
        result = self.press()
        self.assertEqual(self.L.hedge_orders, [])
        row = self.item(result, "INTCUSDT")
        self.assertEqual((row["outcome"], row["reason"]), ("SKIPPED", "OVER_HEDGED"))
        self.assertEqual(self.pair("INTCUSDT")["status"], "RECOVERY")           # untouched: no REDUCE either
        self.assertEqual(self.short("INTCUSDT"), 12.0)

    def test_gap_below_aster_minimum_places_no_order_and_hedges_after_a_later_dca(self):
        self.seed("ICPUSDT", 10.0, short_qty=9.99)                              # gap $0.15 < $5 minimum notional
        result = self.press()
        self.assertEqual(self.L.hedge_orders, [])
        self.assertEqual(self.item(result, "ICPUSDT")["outcome"], "TOO_SMALL")
        self.assertEqual(self.pair("ICPUSDT")["status"], "PRECISION_BLOCKED")   # cycle runs, no order
        self.L.pos[("ICPUSDT", "LONG")] = 11.0                                  # DCA buys 1 more
        self.worker_tick()
        self.assertEqual([o["qty"] for o in self.L.hedge_orders], [1.01])
        self.assertAlmostEqual(self.short("ICPUSDT"), 11.0)
        self.assertEqual(self.pair("ICPUSDT")["status"], "HEDGED")
        self.assert_invariant()

    def test_gap_not_on_the_contract_step_is_never_rounded_up(self):
        self.seed("STEPUSDT", 10.005, step=0.01, minimum=0.01)                 # floor(10.005) = 10.00 != gap
        self.press()
        self.assertEqual(self.L.hedge_orders, [])
        self.assertEqual(self.short("STEPUSDT"), 0.0)

    def test_insufficient_margin_places_nothing_and_reports_it(self):
        self.seed("ICPUSDT", 10.0)
        self.L.available = 1.0                                                  # $150 / 5x leverage needs $30
        result = self.press()
        self.assertEqual(self.L.hedge_orders, [])
        self.assertEqual(self.item(result, "ICPUSDT")["outcome"], "NO_MARGIN")


class SelectionTests(Base):
    def test_no_recovery_positions_is_a_noop(self):
        self.L.add("ICPUSDT", "LONG", 10.0)
        result = self.press()
        self.assertEqual((result["status"], result["found"], self.L.hedge_orders), ("NOTHING_TO_DO", 0, []))

    def test_survivor_short_gets_an_exact_long_hedge(self):
        # Build 623 (Amar 23-10): Re-Hedge All works for both sides; a surviving SHORT gets a 1:1 LONG hedge.
        self.L.add("ABCUSDT", "SHORT", 5.0)
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", "ABCUSDT", recovery_pair("ABCUSDT", survivor="SHORT"))
        result = self.press()
        self.assertEqual([(o["symbol"], o["positionSide"], o["action"], o["qty"]) for o in self.L.hedge_orders],
                         [("ABCUSDT", "LONG", "OPEN", 5.0)])
        self.assertEqual(self.item(result, "ABCUSDT")["outcome"], "PROTECTED")
        self.assertEqual((self.pair("ABCUSDT")["protectedSide"], self.pair("ABCUSDT")["hedgeSide"]), ("SHORT", "LONG"))

    def test_unconfirmed_manual_release_is_skipped(self):
        self.seed("ICPUSDT", 10.0, pair=recovery_pair("ICPUSDT", status="MANUAL_RELEASE_UNCERTAIN"))
        result = self.press()
        self.assertEqual(self.L.hedge_orders, [])
        self.assertEqual(self.item(result, "ICPUSDT")["reason"], "MANUAL_RELEASE_NOT_CONFIRMED")

    def test_armed_and_disabled_recovery_pairs_are_included(self):
        self.seed("AAAUSDT", 1.0, pair=recovery_pair("AAAUSDT", status="REHEDGE_ARMED", rehedgeEnabled=True))
        self.seed("BBBUSDT", 1.0, pair=recovery_pair("BBBUSDT", status="DISABLED"))
        self.press()
        self.assertEqual(sorted(o["symbol"] for o in self.L.hedge_orders), ["AAAUSDT", "BBBUSDT"])

    def test_closed_long_is_skipped(self):
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", "GONEUSDT", recovery_pair("GONEUSDT"))
        self.L.add("OTHERUSDT", "LONG", 1.0)
        result = self.press()
        self.assertEqual(self.item(result, "GONEUSDT")["reason"], "POSITION_CLOSED")
        self.assertEqual(self.L.hedge_orders, [])

    def test_other_account_is_never_touched(self):
        self.seed("ICPUSDT", 10.0)
        self.put("asterPositionLossAutoHedge", "u2", {"enabled": True, "thresholdUsd": 10.0})
        self.put("asterPositionLossAutoHedge", "u2", "pairs", "INJUSDT", recovery_pair("INJUSDT"))
        self.press()
        self.assertEqual(self.pair("INJUSDT", uid="u2")["status"], "RECOVERY")
        self.assertEqual([o["symbol"] for o in self.L.hedge_orders], ["ICPUSDT"])

    def test_refusals(self):
        self.seed("ICPUSDT", 10.0)
        with self.assertRaises(HTTPException) as ctx:
            self.press(confirm=False)
        self.assertEqual(ctx.exception.status_code, 422)
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": False, "thresholdUsd": 10.0})
        with self.assertRaises(HTTPException) as ctx:
            self.press()
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.L.hedge_orders, [])
        self.assertEqual(self.pair("ICPUSDT")["status"], "RECOVERY")

    def test_dynamic_hedge_conflict_refuses(self):
        self.seed("ICPUSDT", 10.0)
        self.put("users", self.uid, "asterDynamicHedge", "control", {"enabled": True})
        with self.assertRaises(HTTPException) as ctx:
            self.press()
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.L.hedge_orders, [])

    def test_shadow_mode_sends_nothing_and_changes_nothing(self):
        self.seed("ICPUSDT", 10.0)
        self.ext.EXECUTION_ENABLED = False
        result = self.press()
        self.assertEqual(self.L.hedge_orders, [])
        self.assertEqual(self.item(result, "ICPUSDT")["outcome"], "TEST_ONLY")
        self.assertEqual(self.pair("ICPUSDT")["status"], "RECOVERY")


class ExecutionSafetyTests(Base):
    def test_timeout_after_accept_reports_unknown_and_never_sends_a_second_order(self):
        self.seed("ICPUSDT", 10.0)
        self.L.hedge_modes["ICPUSDT"] = "timeout"
        result = self.press()
        self.assertEqual(self.item(result, "ICPUSDT")["outcome"], "UNKNOWN")
        for _ in range(3):
            self.worker_tick()
        self.assertEqual(len(self.L.hedge_orders), 1)
        self.assertAlmostEqual(self.short("ICPUSDT"), 10.0)
        self.assert_invariant()

    def test_partial_fill_is_completed_by_the_worker_up_to_exactly_the_long(self):
        self.seed("ICPUSDT", 10.0)
        self.L.hedge_modes["ICPUSDT"] = "partial"
        result = self.press()
        self.assertEqual(self.item(result, "ICPUSDT")["outcome"], "PARTIAL")
        self.worker_tick()
        self.assertAlmostEqual(self.short("ICPUSDT"), 10.0)
        self.assertEqual([round(o["qty"], 6) for o in self.L.hedge_orders], [10.0, 6.0])
        self.assert_invariant()

    def test_rejected_order_places_nothing_and_needs_attention(self):
        self.seed("ICPUSDT", 10.0)
        self.L.hedge_modes["ICPUSDT"] = "reject"
        result = self.press()
        self.assertEqual(self.item(result, "ICPUSDT")["outcome"], "UNKNOWN")
        self.assertEqual(self.short("ICPUSDT"), 0.0)

    def test_long_shrinking_during_processing_is_never_sold_back(self):
        # Build 623 vangnet: the engine no longer sells the SHORT to "straighten" an over-covered pair.
        self.seed("ICPUSDT", 10.0)
        self.L.on_before_order = lambda sym: self.L.pos.__setitem__((sym, "LONG"), 6.0)   # LONG shrinks mid-order
        self.press()
        self.L.on_before_order = None
        self.worker_tick()
        self.assertAlmostEqual(self.short("ICPUSDT"), 10.0)
        self.assertEqual([o["action"] for o in self.L.hedge_orders], ["OPEN"])

    def test_second_press_after_success_does_nothing(self):
        self.seed("ICPUSDT", 10.0)
        self.press()
        result = self.press()
        self.assertEqual(result["status"], "NOTHING_TO_DO")
        self.assertEqual(len(self.L.hedge_orders), 1)

    def test_more_pairs_than_one_tick_budget_are_finished_by_the_worker_without_duplicates(self):
        symbols = [f"S{i:02d}USDT" for i in range(20)]
        for s in symbols:
            self.seed(s, 2.0)
        result = self.press()
        self.assertEqual(result["ordersSent"], 15)
        self.assertEqual(sum(1 for r in result["items"] if r["outcome"] == "QUEUED"), 5)
        self.worker_tick()                                                        # interrupted batch resumes
        self.assertEqual(sorted(o["symbol"] for o in self.L.hedge_orders), symbols)
        self.worker_tick()
        self.assertEqual(len(self.L.hedge_orders), 20)
        self.assert_invariant()

    def test_two_simultaneous_presses_give_one_order_per_pair(self):
        for s in ("AAAUSDT", "BBBUSDT"):
            self.seed(s, 3.0)
        gate, out = threading.Event(), []
        self.L.on_before_order = lambda sym: (gate.set(), time.sleep(0.2))

        def press():
            try:
                out.append(self.press()["status"])
            except HTTPException as exc:
                out.append(exc.status_code)
        threads = [threading.Thread(target=press) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        self.assertEqual(sorted(o["symbol"] for o in self.L.hedge_orders), ["AAAUSDT", "BBBUSDT"])
        self.assertIn("DONE", out)
        self.assertTrue(all(x in ("DONE", "NOTHING_TO_DO", 409) for x in out), out)
        self.assert_invariant()

    def test_busy_account_lease_refuses_before_any_change(self):
        self.seed("ICPUSDT", 10.0)
        token = self.ns._acquire_aster_account_coordination(self.uid, "MANUAL_CLOSE", "TEST")
        try:
            with self.assertRaises(HTTPException) as ctx:
                self.press()
        finally:
            self.ns._release_aster_account_coordination(self.uid, token)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, self.ext.REHEDGE_ALL_BUSY)
        self.assertEqual(self.pair("ICPUSDT")["status"], "RECOVERY")
        self.assertEqual(self.L.hedge_orders, [])

    def test_auto_hedge_worker_running_at_the_same_time_never_doubles(self):
        self.seed("ICPUSDT", 10.0)
        started = threading.Event()
        self.L.on_before_order = lambda sym: (started.set(), time.sleep(0.3))
        t = threading.Thread(target=self.press)
        t.start()
        self.assertTrue(started.wait(10))                                       # Re-Hedge All holds the lease now
        for _ in range(3):
            self.worker_tick()
        t.join(20)
        self.L.on_before_order = None
        self.worker_tick()
        self.assertEqual(len(self.L.hedge_orders), 1)
        self.assertAlmostEqual(self.short("ICPUSDT"), 10.0)

    def test_individual_toggle_keeps_its_own_behaviour(self):
        self.seed("ICPUSDT", 10.0)
        self.ext.put_position_loss_auto_hedge_rehedge("ICPUSDT", self.ext.RehedgeRequest(enabled=True), Response(), {"uid": self.uid})
        self.assertEqual(self.pair("ICPUSDT")["status"], "REHEDGE_ARMED")      # LONG in profit: only armed
        self.assertEqual(self.L.hedge_orders, [])
        self.press()
        self.assertEqual(len(self.L.hedge_orders), 1)
        with self.assertRaises(HTTPException) as ctx:                          # now an active cycle: toggle refuses
            self.ext.put_position_loss_auto_hedge_rehedge("ICPUSDT", self.ext.RehedgeRequest(enabled=False), Response(), {"uid": self.uid})
        self.assertEqual(ctx.exception.status_code, 409)


class WorkflowTests(Base):
    def test_close_profits_then_rehedge_all_restores_exact_parity(self):
        """Amar's workflow: Close SHORT profits 50% on Auto Hedge pairs -> Recovery -> Re-Hedge All -> 1:1 again."""
        if self.EMULATOR:
            self.skipTest("close route covered on the emulator by the Close Profits suites")
        route, _, _ = H.build_backend(self.L, self.fs)
        for s in ("ICPUSDT", "INJUSDT"):
            self.L.add(s, "LONG", 10.0, mark=15.0)
            self.L.add(s, "SHORT", 10.0, mark=15.0)                              # profitable SHORT
            self.put("asterPositionLossAutoHedge", self.uid, "pairs", s, {
                "symbol": s, "status": "HEDGED", "protectedSide": "LONG", "hedgeSide": "SHORT",
                "rehedgeEnabled": False, "reservedHedgeQty": 10.0, "generation": 1, "generationId": "g1"})
        for n, s in enumerate(("ICPUSDT", "INJUSDT")):
            route(s.lower(), H.request(10.0, percentage=50, key=f"idempotency-key-{n:08d}"), {"uid": self.uid})
            self.assertEqual(self.pair(s)["status"], "RECOVERY")
            self.assertAlmostEqual(self.short(s), 5.0)
        result = self.press()
        self.assertEqual({r["symbol"]: r["outcome"] for r in result["items"]}, {"ICPUSDT": "PROTECTED", "INJUSDT": "PROTECTED"})
        for s in ("ICPUSDT", "INJUSDT"):
            self.assertAlmostEqual(self.short(s), 10.0)
            self.assertAlmostEqual(self.long(s), 10.0)
        self.assert_invariant()


class InvariantPropertyTests(Base):
    def test_random_worlds_never_exceed_the_long(self):
        rng = random.Random(606)
        for world in range(25):
            self.setUp()
            for i in range(rng.randint(1, 8)):
                s = f"W{i}USDT"
                long_qty = round(rng.uniform(0.5, 50), 3)
                short_qty = round(rng.choice([0, rng.uniform(0, long_qty * 1.2)]), 3)
                self.seed(s, long_qty, short_qty=short_qty, mark=round(rng.uniform(0.5, 300), 2))
                if rng.random() < 0.3:
                    self.L.open_order_rows.append({"symbol": s, "positionSide": "SHORT", "side": "SELL",
                                                   "origQty": str(round(rng.uniform(0, long_qty / 3), 3)),
                                                   "executedQty": "0", "status": "NEW"})
            before = {k: v for k, v in self.L.pos.items() if k[1] == "SHORT"}
            self.press()
            for _ in range(2):
                self.worker_tick()
            pending = {r["symbol"]: float(r["origQty"]) for r in self.L.open_order_rows}
            for (s, side), qty in self.L.pos.items():
                if side != "SHORT":
                    continue
                if before.get((s, side), 0) + pending.get(s, 0.0) > self.long(s):
                    self.assertEqual(qty, before.get((s, side), 0), (world, s))     # over-hedged: untouched
                else:
                    self.assertLessEqual(qty + pending.get(s, 0.0), self.long(s) + 1e-9, (world, s))
            for order in self.L.hedge_orders:
                self.assertEqual((order["positionSide"], order["action"]), ("SHORT", "OPEN"), (world, order))


@unittest.skipUnless(HAVE, "needs aster_gateway deps")
class FloatNoiseTests(unittest.TestCase):
    def test_one_step_gap_with_float_noise_is_executable_and_never_above_the_gap(self):
        from aster_gateway import ContractRules
        from aster_position_loss_auto_hedge import _exact_market_quantity
        rule = ContractRules.from_exchange_info({"symbol": "XUSDT", "status": "TRADING", "filters": [
            {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100000", "stepSize": "0.001"},
            {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "100000", "stepSize": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "5"}]})
        rng = random.Random(7)
        for _ in range(5000):
            long_qty = round(rng.uniform(1, 500), 3)
            short_qty = round(rng.uniform(0, long_qty - 0.5), 3)
            gap = long_qty - short_qty                                            # float noise included
            qty = _exact_market_quantity(rule, gap, 100.0, "XUSDT")
            self.assertLessEqual(float(qty) + short_qty, long_qty + 1e-9)
            self.assertAlmostEqual(float(qty), gap, places=9)
        self.assertEqual(str(_exact_market_quantity(rule, 11.0 - 9.99, 100.0, "XUSDT")), "1.010")
        with self.assertRaises(Exception):                                       # a real sub-step gap stays blocked
            _exact_market_quantity(rule, 1.0005, 100.0, "XUSDT")


class SourceContractTests(unittest.TestCase):
    def test_force_path_runs_under_the_lease_and_places_no_orders_itself(self):
        src = (HERE / "aster_position_loss_auto_hedge_extension.py").read_text()
        body = src[src.index("def _run_uid("):]
        body = body[:body.index("\n@main.app.get(")]
        self.assertLess(body.index("main._acquire_aster_account_coordination("), body.index("_prepare_lifecycle("))
        self.assertIn("force_rehedge_symbols=force_rehedge_symbols", body)
        route = src[src.index('"/v1/me/aster/position-loss-auto-hedge/rehedge-all"'):]
        route = route[:route.index("def _worker_loop")]
        for forbidden in ("submit_order", "AsterOrderIntent", "position_risk(", ".where(", ".order_by("):
            self.assertNotIn(forbidden, route)
        force = src[src.index("def _force_rehedge_cycle("):src.index("def _prepare_lifecycle(")]
        self.assertIn("protected_sides={symbol: remaining_side}", force)
        self.assertIn('action.status == "OVER_COVERED"', force)
        self.assertNotIn("submit_order", force)


if __name__ == "__main__":
    unittest.main()
