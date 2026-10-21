"""Close Profits 2.1 — resumable rounds, model-based tests.

Real: profit_close_rounds (engine), the individual close route + helpers from main.py, execute_leg_once (fill
confirmation), ContractRules, the planner. Mocked: Firestore (in-memory model; the emulator variant swaps in a real
client) and Aster (ledger). No network, no credentials, no orders. Model-based: not proof against real Aster."""
from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

try:
    import offline_close_harness as H
    from aster_execution import client_order_id
    from aster_gateway import AsterApiError
    from manual_profit_close_planner import build_profit_close_plan, filters_from_aster_exchange_info
    import profit_close_rounds as R
    HAVE = True
except Exception:  # pragma: no cover  (aster_gateway needs httpx)
    HAVE = False


@unittest.skipUnless(HAVE, "needs aster_gateway (httpx)")
class RoundBase(unittest.TestCase):
    EMULATOR = False

    def make_store(self):
        self.uid = "u1"
        return H.FakeFirestore(), None

    def setUp(self):
        self.fs, real = self.make_store()
        self.L = H.Ledger(self.fs)
        self.route, self.ns, self.HTTP = H.build_backend(self.L, self.fs, real=real, real_leg=True)
        self.user = {"uid": self.uid}
        self.route_calls = []
        self.lose_response = set()            # symbols whose route answer is "lost" once (raised after success)
        ledger = self.L

        class Reader:
            """Read-only Aster client as seen by the round engine: position_risk, exchange info, order query."""
            def position_risk(self): return ledger.rows()
            def public_exchange_info(self): return ledger.exchange_info()
            def query_order(self, symbol, cid):
                if symbol in ledger.query_fails:
                    raise AsterApiError("Aster API 500: internal")
                row = ledger.order_log.get(cid)
                if row is None:
                    raise AsterApiError('Aster API 400: {"code":-2013,"msg":"Order does not exist."}')
                return {"status": row["status"], "executedQty": str(row["executed"])}

        def route(symbol, request, user):
            self.route_calls.append((symbol, request.idempotency_key))
            result = self.route(symbol, request, user)
            if symbol in self.lose_response:
                self.lose_response.discard(symbol)
                raise ConnectionError("response lost")    # the server DID close; the answer never arrives
            return result

        if real:
            transactional = real[0].transactional
            already = real[1].AlreadyExists
        else:
            transactional = lambda f: (lambda txn: H._locked(self.fs, f, txn))
            already = H.AlreadyExists
        self.env = R.RoundEnv(
            db=self.fs, transactional=transactional, already_exists=already, http_exception=self.HTTP,
            close_route=route, make_request=lambda **kw: SimpleNamespace(**kw), client_for=lambda user: Reader(),
            plan=lambda rows, pct, filters: build_profit_close_plan(rows, pct, filters, hedge_links={},
                                                                   include_short_below_minimum=True),
            filters=filters_from_aster_exchange_info, client_order_id=client_order_id,
            now=lambda: datetime.now(timezone.utc) + self.ns.clock.offset,
        )
        self.k = 0

    # ---------------------------------------------------------------------------------------------- helpers
    def key(self):
        self.k += 1
        return f"round-confirm-key-{self.k:08d}"

    def shorts(self, n, qty=8.0, prefix="C"):
        symbols = [f"{prefix}{i:02d}USDT" for i in range(n)]
        for s in symbols:
            self.L.add(s, "SHORT", qty, mark=100.0)
        return symbols

    def targets(self, symbols, qty=8.0):
        return [{"symbol": s, "side": "SHORT", "quantity": qty} for s in symbols]

    def create(self, symbols, pct=25, key=None, qty=8.0):
        return R.create_round(self.env, self.user, percentage=pct, idempotency_key=key or self.key(),
                              targets=self.targets(symbols, qty))

    def run_round(self, round_id, max_steps=200):
        for _ in range(max_steps):
            out = R.advance(self.env, self.user, round_id)
            if out["round"]["status"] in R.ROUND_TERMINAL | {"PAUSED"}:
                return out["round"]
            if out.get("waiting"):
                self.ns.clock.offset += timedelta(seconds=2)
        self.fail("round did not finish")

    def orders_for(self, symbol):
        return [o for o in self.L.orders if o[0] == symbol]

    def item(self, rnd, symbol):
        return next(i for i in rnd["items"] if i["symbol"] == symbol)


class CreateTests(RoundBase):
    def test_same_confirmation_twice_gives_one_round(self):
        syms = self.shorts(3)
        key = self.key()
        a = self.create(syms, key=key)
        b = self.create(syms, key=key)
        self.assertTrue(a["created"]); self.assertFalse(b["created"])
        self.assertEqual(a["round"]["roundId"], b["round"]["roundId"])
        self.assertEqual(self.L.orders, [])                               # creating never orders

    def test_only_one_active_round_and_a_new_press_is_refused_while_unfinished(self):
        syms = self.shorts(3)
        first = self.create(syms)["round"]
        with self.assertRaises(R.RoundError) as ctx:
            self.create(syms)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.round_view["roundId"], first["roundId"])
        self.assertEqual(R.get_active(self.env, self.uid)["roundId"], first["roundId"])

    def test_twenty_concurrent_creates_give_exactly_one_active_round(self):
        syms = self.shorts(4)
        results, errors = [], []

        def go(i):
            try:
                results.append(R.create_round(self.env, self.user, percentage=25,
                                              idempotency_key=f"concurrent-key-{i:08d}", targets=self.targets(syms)))
            except R.RoundError as exc:
                errors.append(exc.status_code)
        threads = [threading.Thread(target=go, args=(i,)) for i in range(20)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(len([r for r in results if r["created"]]), 1)
        self.assertEqual(errors, [409] * 19)

    def test_server_only_keeps_shorts_its_own_plan_still_selects(self):
        self.L.add("GOODUSDT", "SHORT", 8.0, mark=100.0)
        self.L.add("LOSSUSDT", "SHORT", 8.0, mark=100.0, entry=99.0)       # losing SHORT: not selected
        rnd = self.create(["GOODUSDT", "LOSSUSDT", "GHOSTUSDT"])["round"]
        self.assertEqual(self.item(rnd, "GOODUSDT")["status"], "PENDING")
        self.assertEqual(self.item(rnd, "LOSSUSDT")["status"], "SKIPPED")
        self.assertEqual(self.item(rnd, "GHOSTUSDT")["reason"], "no_longer_eligible")


class ResumeTests(RoundBase):
    def test_interrupted_after_first_item_resume_closes_the_rest_never_the_first_again(self):
        """Amar's case of 22-10 ~00:11: 15 SHORTs, the phone loses the connection after the first close."""
        syms = self.shorts(15)
        rnd = self.create(syms)["round"]
        R.advance(self.env, self.user, rnd["roundId"])                     # first item closed
        self.assertEqual(len(self.L.orders), 1)
        # ... the phone is gone. Later the user presses "Hervat ronde": the SAME round continues.
        with self.assertRaises(R.RoundError):
            self.create(syms)                                             # a new round is refused
        done = self.run_round(rnd["roundId"])
        self.assertEqual(done["status"], "FINISHED")
        self.assertEqual(done["counts"]["done"], 15)
        for s in syms:
            self.assertEqual(len(self.orders_for(s)), 1, s)                 # every SHORT exactly once
            self.assertAlmostEqual(self.L.pos[(s, "SHORT")], 6.0)          # 25% of 8
        self.assertIsNone(R.get_active(self.env, self.uid))

    def test_after_finishing_a_later_press_is_a_new_round_on_the_new_level(self):
        syms = self.shorts(2)
        first = self.create(syms)["round"]
        self.run_round(first["roundId"])
        second = self.create(syms, qty=6.0)["round"]                        # deeper later: new round, new 25%
        self.assertNotEqual(first["roundId"], second["roundId"])
        self.run_round(second["roundId"])
        for s in syms:
            self.assertEqual(len(self.orders_for(s)), 2)
            self.assertAlmostEqual(self.L.pos[(s, "SHORT")], 4.5)

    def test_abandon_stops_remaining_items_and_allows_a_new_round(self):
        syms = self.shorts(5)
        rnd = self.create(syms)["round"]
        R.advance(self.env, self.user, rnd["roundId"])
        out = R.abandon(self.env, self.user, rnd["roundId"])
        self.assertEqual(out["round"]["status"], "ABANDONED")
        again = R.advance(self.env, self.user, rnd["roundId"])
        self.assertEqual(again["round"]["status"], "ABANDONED")
        self.assertEqual(len(self.L.orders), 1)                             # nothing after abandon
        self.assertTrue(self.create(syms)["created"])                     # a new round is allowed again


class NetworkLossTests(RoundBase):
    def test_lost_response_after_the_order_returns_the_stored_result_and_never_orders_twice(self):
        syms = self.shorts(3)
        rnd = self.create(syms)["round"]
        self.lose_response.add(syms[0])
        out = R.advance(self.env, self.user, rnd["roundId"])               # route closed, answer lost
        self.assertEqual(len(self.orders_for(syms[0])), 1)
        self.assertEqual(self.item(out["round"], syms[0])["status"], "DONE")  # intent says confirmed_closed
        done = self.run_round(rnd["roundId"])
        self.assertEqual(len(self.L.orders), 3)
        self.assertEqual(done["counts"]["done"], 3)

    def test_order_accepted_then_connection_drops_inside_the_route_is_reconciled_with_aster(self):
        syms = self.shorts(3)
        rnd = self.create(syms)["round"]
        self.L.modes[syms[1]] = "drop_after_accept"
        done = self.run_round(rnd["roundId"])
        self.assertEqual(len(self.orders_for(syms[1])), 1)                  # never a second order
        self.assertEqual(self.item(done, syms[1])["status"], "DONE")
        self.assertEqual(self.item(done, syms[1])["reason"], "confirmed_by_aster_query")
        self.assertEqual(done["counts"]["done"], 3)

    def test_two_concurrent_advances_never_close_the_same_item_twice(self):
        syms = self.shorts(6)
        rnd = self.create(syms)["round"]

        def worker():
            for _ in range(30):
                try:
                    R.advance(self.env, self.user, rnd["roundId"])
                except R.RoundError:
                    pass
        threads = [threading.Thread(target=worker) for _ in range(2)]
        [t.start() for t in threads]; [t.join() for t in threads]
        for s in syms:
            self.assertEqual(len(self.orders_for(s)), 1, s)


class ReconciliationTests(RoundBase):
    def _uncertain_round(self, mode, symbol="FILUSDT"):
        self.L.add(symbol, "SHORT", 8.0, mark=100.0)
        other = self.shorts(1, prefix="Z")
        rnd = self.create([symbol] + other)["round"]
        self.L.modes[symbol] = mode
        return rnd, symbol, other[0]

    def test_filled_on_aster_is_done(self):
        rnd, sym, other = self._uncertain_round("drop_after_accept")
        done = self.run_round(rnd["roundId"])
        self.assertEqual(self.item(done, sym)["status"], "DONE")
        self.assertEqual(len(self.orders_for(sym)), 1)

    def test_partially_filled_is_needs_check_never_reordered_and_the_rest_continues(self):
        rnd, sym, other = self._uncertain_round("partial_fill")
        done = self.run_round(rnd["roundId"])
        self.assertEqual(self.item(done, sym)["status"], "NEEDS_CHECK")
        self.assertEqual(len(self.orders_for(sym)), 1)
        self.assertEqual(self.item(done, other)["status"], "DONE")            # other symbol still closed
        self.assertEqual(done["status"], "FINISHED")

    def test_query_failure_is_needs_check_and_nothing_is_ordered_again(self):
        rnd, sym, other = self._uncertain_round("timeout_after_accept")
        self.L.query_fails.add(sym)
        done = self.run_round(rnd["roundId"])
        self.assertEqual(self.item(done, sym)["status"], "NEEDS_CHECK")
        self.assertEqual(len(self.orders_for(sym)), 1)
        self.assertEqual(self.item(done, other)["status"], "DONE")

    def test_order_absent_on_aster_is_retried_once_with_a_new_fixed_key_after_the_grace_period(self):
        self.L.add("FILUSDT", "SHORT", 8.0, mark=100.0)
        rnd = self.create(["FILUSDT"])["round"]
        rid = rnd["roundId"]
        # Simulate: the attempt-0 request reached the route, wrote the durable marker, and died before Aster got it.
        h0 = R.intent_hash(self.uid, R.item_key(rid, "FILUSDT", 0))
        started = datetime.now(timezone.utc)
        R._intent_ref(self.env, self.uid, h0).set({"status": "prepared", "symbol": "FILUSDT", "side": "SHORT",
                                                  "createdAt": started, "orderMayHaveBeenSent": True,
                                                  "orderStartedAt": started})
        R._guard_ref(self.env, self.uid, "FILUSDT", h0).set({"status": "order_started", "orderStartedAt": started})
        out = R.advance(self.env, self.user, rid)                              # still within the request window
        self.assertTrue(out["waiting"]); self.assertEqual(self.L.orders, [])
        self.ns.clock.offset += timedelta(seconds=400)                        # request window and grace passed
        out = R.advance(self.env, self.user, rid)                              # Aster: order does not exist
        self.assertEqual(self.item(out["round"], "FILUSDT")["attempt"], 1)
        self.assertEqual(self.L.orders, [])
        done = self.run_round(rid)
        self.assertEqual(len(self.orders_for("FILUSDT")), 1)                   # exactly one real order in total
        self.assertEqual(self.item(done, "FILUSDT")["status"], "DONE")


class RefusalTests(RoundBase):
    def test_too_small_and_unprofitable_are_skipped_and_the_round_continues(self):
        self.L.add("TINYUSDT", "SHORT", 0.002, mark=100.0, entry=400.0, minimum=0.001, step=0.001)
        syms = self.shorts(2)
        rnd = R.create_round(self.env, self.user, percentage=25, idempotency_key=self.key(),
                             targets=[{"symbol": "TINYUSDT", "side": "SHORT", "quantity": 0.002}] + self.targets(syms))
        rid = rnd["round"]["roundId"]
        self.L.mark[syms[0]] = 104.99                                          # profit falls to ~$0.08 before its turn
        done = self.run_round(rid)
        self.assertEqual(self.item(done, "TINYUSDT")["reason"], "too_small")
        self.assertEqual(self.item(done, syms[0])["reason"], "not_profitable")
        self.assertEqual(self.item(done, syms[1])["status"], "DONE")
        self.assertEqual(len(self.L.orders), 1)

    def test_changed_size_is_skipped_without_order(self):
        syms = self.shorts(2)
        rid = self.create(syms)["round"]["roundId"]
        self.L.pos[(syms[0], "SHORT")] = 7.0                                   # Auto Hedge / manual change meanwhile
        done = self.run_round(rid)
        self.assertEqual(self.item(done, syms[0])["reason"], "size_changed")
        self.assertEqual(self.orders_for(syms[0]), [])
        self.assertEqual(self.item(done, syms[1])["status"], "DONE")

    def test_two_consecutive_system_errors_pause_and_resume_continues_at_the_same_item(self):
        syms = self.shorts(2)
        rid = self.create(syms)["round"]["roundId"]
        outage = {"on": True}

        def aster_down():                                                      # position reads fail BEFORE any order
            if outage["on"]:
                raise ConnectionError("Aster unreachable")
        self.L.on_before_read = aster_down
        paused = self.run_round(rid)
        self.assertEqual(paused["status"], "PAUSED")
        self.assertEqual(paused["pauseReason"], "system_errors")
        self.assertEqual(self.L.orders, [])
        outage["on"] = False
        R.resume(self.env, self.user, rid)
        done = self.run_round(rid)
        self.assertEqual(done["status"], "FINISHED")
        self.assertEqual(len(self.L.orders), 2)


class StaticTests(unittest.TestCase):
    def test_rounds_use_no_filtered_query_and_need_no_index(self):
        from pathlib import Path
        for name in ("profit_close_rounds.py", "profit_close_rounds_extension.py"):
            src = (Path(__file__).parent / name).read_text()
            for forbidden in (".where(", ".order_by(", "collection_group(", ".limit("):
                self.assertNotIn(forbidden, src, f"{name}: {forbidden}")

    def test_round_never_places_orders_itself(self):
        """The engine only CALLS the injected individual close route; it has no order path of its own."""
        import ast
        from pathlib import Path
        tree = ast.parse((Path(__file__).parent / "profit_close_rounds.py").read_text())
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
               {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("submit_order_once", "execute_aster_leg", "execute_leg_once", "signed_request"):
            self.assertNotIn(forbidden, used, forbidden)
        imported = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        self.assertFalse(imported & {"httpx", "aster_gateway", "aster_execution", "main"}, imported)

    def test_extension_binds_the_existing_individual_route_and_a_read_only_client(self):
        from pathlib import Path
        src = (Path(__file__).parent / "profit_close_rounds_extension.py").read_text()
        self.assertIn("close_route=main.close_one_aster_position", src)
        self.assertIn("main.AsterManualCloseRequest(**kw)", src)
        self.assertIn("main._portfolio_growth_client(user, live=False)", src)       # reads + order query only
        self.assertIn("transactional=main.firestore.transactional", src)

    def test_router_is_registered_on_the_production_entrypoint(self):
        from pathlib import Path
        src = (Path(__file__).parent / "withdraw_app.py").read_text()
        self.assertIn("main.app.include_router(profit_close_rounds_router)", src)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE, "needs aster_gateway (httpx)")
class RejectBeforeAcceptTests(RoundBase):
    def test_reject_after_the_durable_marker_is_treated_as_maybe_sent_and_never_blindly_repeated(self):
        """The route writes 'order may have been sent' BEFORE the POST. A rejection after that point is
        indistinguishable from a lost order, so the round asks Aster each time and retries only after Aster
        proves the order does not exist; after MAX_ATTEMPTS it stops and asks the user."""
        syms = self.shorts(2)
        rid = self.create(syms)["round"]["roundId"]
        self.L.modes[syms[0]] = "reject_before"
        done = self.run_round(rid)
        self.assertEqual(self.item(done, syms[0])["status"], "NEEDS_CHECK")
        self.assertEqual(self.item(done, syms[0])["reason"], "too_many_attempts")
        self.assertEqual(self.orders_for(syms[0]), [])
        self.assertEqual(self.item(done, syms[1])["status"], "DONE")
