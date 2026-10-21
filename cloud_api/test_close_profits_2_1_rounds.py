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
        self.route_requests = []
        self.extra_rows = []
        self.snapshot_broken = False
        self.inject = {}                       # symbol -> list of HTTP(status, detail) raised BEFORE the real route
        self.lose_response = set()            # symbols whose route answer is "lost" once (raised after success)
        ledger = self.L

        test = self

        class Reader:
            """Read-only Aster client as seen by the round engine: position_risk, exchange info, order query."""
            def position_risk(self):
                if test.snapshot_broken:
                    raise RuntimeError("Aster positionRisk unreadable")
                return ledger.rows() + [dict(r) for r in test.extra_rows]
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
            self.route_requests.append((symbol, dict(vars(request))))
            queue = self.inject.get(symbol)
            if queue:
                status, detail = queue.pop(0)
                raise self.HTTP(status, detail)
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
            except Exception as exc:                                          # must never escape as a raw error
                errors.append(repr(exc))
        threads = [threading.Thread(target=go, args=(i,)) for i in range(20)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(len([r for r in results if r["created"]]), 1)
        self.assertEqual(len(results) + len(errors), 20)
        self.assertTrue(all(e in (409, 503) for e in errors), errors)          # refused or "try again", never raw
        self.assertEqual(R.get_active(self.env, self.uid)["roundId"],
                         next(r["round"]["roundId"] for r in results if r["created"]))
        self.assertEqual(self.L.orders, [])

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


PAIR = {"status": "HEDGED", "protectedSide": "LONG", "hedgeSide": "SHORT", "rehedgeEnabled": True,
        "reservedHedgeQty": 0.0, "generationId": "g1"}
BUSY = "Auto Hedge verwerkt momenteel dezelfde accountstatus; probeer de sluiting zo opnieuw"


def floor_step(value, step=0.001):
    from decimal import Decimal, ROUND_DOWN
    d = Decimal(str(step))
    return float((Decimal(repr(value)) / d).to_integral_value(rounding=ROUND_DOWN) * d)


class ContractParityTests(RoundBase):
    """The safety contracts of the five removed 2.0 browser-loop test files, proven on the 2.1 server round.
    Each test names the 2.0 file it replaces (see the contract matrix in the release dossier)."""

    def seed_pair(self, symbol):
        self.L.add(symbol, "LONG", 8.0, mark=100.0)
        self.fs.collection("asterPositionLossAutoHedge").document(self.uid).collection("pairs").document(symbol).set(
            {**PAIR, "symbol": symbol})
        self.fs.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": True})

    def pair_status(self, symbol):
        snap = self.fs.collection("asterPositionLossAutoHedge").document(self.uid).collection("pairs").document(symbol).get()
        return (snap.to_dict() or {}).get("status")

    # --- release-guards / scope / short-handler: exact request body ----------------------------------------
    def test_every_close_carries_the_series_safeguards_and_the_full_live_quantity(self):
        syms = self.shorts(3, qty=12.345)
        rid = self.create(syms, pct=50, qty=12.345)["round"]["roundId"]
        self.run_round(rid)
        self.assertEqual(len(self.route_requests), 3)
        for sym, req in self.route_requests:
            self.assertEqual(sorted(req), ["bulk_series", "confirm", "expected_quantity", "idempotency_key",
                                           "min_open_pnl_usd", "percentage", "side"])
            self.assertEqual((req["confirm"], req["side"], req["percentage"]), (True, "SHORT", 50))
            self.assertEqual(req["expected_quantity"], 12.345)                 # FULL position, never the close size
            self.assertEqual(req["min_open_pnl_usd"], 0.5)
            self.assertIs(req["bulk_series"], True)
            self.assertEqual(req["idempotency_key"], f"round:{rid}:{sym}:0")

    # --- short-handler / integration: once per symbol, exact sizes, all percentages, LONGs untouched --------
    def test_all_percentages_once_per_symbol_exact_step_rounded_sizes_longs_untouched(self):
        for pct in (25, 50, 75, 100):
            self.setUp()
            syms = [f"P{i:02d}USDT" for i in range(6)]
            for i, s in enumerate(syms):
                self.L.add(s, "SHORT", 8.0 + i * 1.37, mark=100.0)
                self.L.add(s, "LONG", 5.0, mark=100.0)
            rid = R.create_round(self.env, self.user, percentage=pct, idempotency_key=self.key(),
                                 targets=[{"symbol": s, "side": "SHORT", "quantity": 8.0 + i * 1.37}
                                          for i, s in enumerate(syms)])["round"]["roundId"]
            done = self.run_round(rid)
            self.assertEqual(done["counts"]["done"], 6, pct)
            self.assertEqual(sorted(o[0] for o in self.L.orders), sorted(syms))
            for sym, side, qty, _ in self.L.orders:
                i = syms.index(sym)
                expected = (8.0 + i * 1.37) if pct == 100 else floor_step((8.0 + i * 1.37) * pct / 100)
                self.assertEqual(side, "SHORT")
                self.assertAlmostEqual(qty, expected, places=9, msg=f"{sym} {pct}%")
                self.assertEqual(self.L.pos[(sym, "LONG")], 5.0)

    # --- round6: fresh position check right before every close -----------------------------------------
    def test_position_missing_right_before_its_close_is_skipped_without_order(self):
        syms = self.shorts(3)
        rid = self.create(syms)["round"]["roundId"]
        self.L.pos[(syms[1], "SHORT")] = 0.0
        done = self.run_round(rid)
        self.assertEqual(self.item(done, syms[1])["reason"], "position_gone")
        self.assertEqual(self.orders_for(syms[1]), [])
        self.assertEqual(done["counts"]["done"], 2)

    def test_duplicate_or_contradictory_position_rows_need_check_without_order(self):
        syms = self.shorts(3)
        rid = self.create(syms)["round"]["roundId"]
        self.extra_rows = [r for r in self.L.rows() if r["symbol"] == syms[0]]     # same SHORT reported twice
        done = self.run_round(rid)
        self.assertEqual(self.item(done, syms[0])["status"], "NEEDS_CHECK")
        self.assertEqual(self.item(done, syms[0])["reason"], "position_ambiguous")
        self.assertEqual(self.orders_for(syms[0]), [])
        self.assertEqual(done["counts"]["done"], 2)

    def test_unreadable_position_snapshot_pauses_the_round_without_any_order(self):
        syms = self.shorts(2)
        rid = self.create(syms)["round"]["roundId"]
        self.snapshot_broken = True
        paused = self.run_round(rid)
        self.assertEqual((paused["status"], paused["pauseReason"]), ("PAUSED", "system_errors"))
        self.assertEqual(self.L.orders, [])
        self.assertEqual(self.route_calls, [])                                 # stopped BEFORE the route

    def test_unreadable_profit_pauses_the_round_without_any_order(self):
        syms = self.shorts(2)
        rid = self.create(syms)["round"]["roundId"]
        original = self.L.rows
        self.L.rows = lambda: [{**r, "unRealizedProfit": "n/a"} if r["symbol"] == syms[0] else r for r in original()]
        paused = self.run_round(rid)
        self.assertEqual(paused["status"], "PAUSED")
        self.assertEqual(self.L.orders, [])
        self.assertNotEqual(self.item(paused, syms[0])["status"], "DONE")

    def test_profit_gone_before_each_close_is_rechecked_and_skipped_without_order(self):
        syms = self.shorts(3)
        rid = self.create(syms)["round"]["roundId"]
        R.advance(self.env, self.user, rid)                                    # first closes
        self.L.mark[syms[1]] = 104.99                                          # second falls to ~$0,08
        done = self.run_round(rid)
        self.assertEqual(self.item(done, syms[1])["reason"], "not_profitable")
        self.assertEqual(self.orders_for(syms[1]), [])
        self.assertEqual(done["counts"]["done"], 2)

    # --- release-guards: earlier unconfirmed close of the same symbol ------------------------------------
    def test_earlier_unconfirmed_close_of_the_symbol_needs_check_and_the_rest_continues(self):
        syms = self.shorts(3)
        rid = self.create(syms)["round"]["roundId"]
        R._guard_ref(self.env, self.uid, syms[1], "an-earlier-unconfirmed-intent").set(
            {"status": "order_started", "orderStartedAt": datetime.now(timezone.utc)})
        done = self.run_round(rid)
        self.assertEqual(self.item(done, syms[1])["status"], "NEEDS_CHECK")
        self.assertEqual(self.item(done, syms[1])["reason"], "earlier_close_unconfirmed")
        self.assertEqual(self.orders_for(syms[1]), [])
        self.assertEqual(done["counts"]["done"], 2)

    # --- release-guards / round6 / scope: account busy (real lease held by the Auto Hedge worker) ----------
    def test_account_busy_is_retried_at_most_three_times_with_a_new_key_then_skipped(self):
        self.L.add("BUSYUSDT", "SHORT", 8.0, mark=100.0); self.seed_pair("BUSYUSDT")
        other = self.shorts(1)
        rid = self.create(["BUSYUSDT"] + other)["round"]["roundId"]
        self.assertTrue(self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "worker"))
        for _ in range(4):
            R.advance(self.env, self.user, rid)
        keys = [k for s, k in self.route_calls if s == "BUSYUSDT"]
        self.assertEqual(keys, [f"round:{rid}:BUSYUSDT:{n}" for n in range(4)])   # 1 + 3 retries, new key each
        rnd = R.get_round(self.env, self.uid, rid)
        self.assertEqual(self.item(rnd, "BUSYUSDT")["status"], "SKIPPED")
        self.assertEqual(self.item(rnd, "BUSYUSDT")["reason"], "account_busy")
        self.assertEqual(self.orders_for("BUSYUSDT"), [])
        self.assertEqual(self.pair_status("BUSYUSDT"), "HEDGED")                 # nothing frozen

    def test_busy_twice_then_success_one_order_full_quantity_new_key_each_time(self):
        self.L.add("BUSYUSDT", "SHORT", 8.0, mark=100.0); self.seed_pair("BUSYUSDT")
        rid = self.create(["BUSYUSDT"])["round"]["roundId"]
        token = self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "worker")
        R.advance(self.env, self.user, rid); R.advance(self.env, self.user, rid)
        self.ns._release_aster_account_coordination(self.uid, token)
        done = self.run_round(rid)
        self.assertEqual(self.item(done, "BUSYUSDT")["status"], "DONE")
        self.assertEqual(len(self.orders_for("BUSYUSDT")), 1)
        reqs = [r for s, r in self.route_requests if s == "BUSYUSDT"]
        self.assertEqual([r["idempotency_key"] for r in reqs], [f"round:{rid}:BUSYUSDT:{n}" for n in range(3)])
        self.assertTrue(all(r["expected_quantity"] == 8.0 for r in reqs))
        self.assertEqual(self.pair_status("BUSYUSDT"), "RECOVERY")             # existing manual transition

    def test_quantity_changed_during_the_busy_wait_is_skipped_without_order(self):
        self.L.add("BUSYUSDT", "SHORT", 8.0, mark=100.0); self.seed_pair("BUSYUSDT")
        rid = self.create(["BUSYUSDT"])["round"]["roundId"]
        token = self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "worker")
        R.advance(self.env, self.user, rid)
        self.ns._release_aster_account_coordination(self.uid, token)
        self.L.pos[("BUSYUSDT", "SHORT")] = 6.0                                # the worker changed the SHORT
        done = self.run_round(rid)
        self.assertEqual(self.item(done, "BUSYUSDT")["reason"], "size_changed")
        self.assertEqual(self.orders_for("BUSYUSDT"), [])

    def test_snapshot_failure_during_the_busy_wait_places_no_order(self):
        self.L.add("BUSYUSDT", "SHORT", 8.0, mark=100.0); self.seed_pair("BUSYUSDT")
        rid = self.create(["BUSYUSDT"])["round"]["roundId"]
        token = self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "worker")
        R.advance(self.env, self.user, rid)
        self.ns._release_aster_account_coordination(self.uid, token)
        self.snapshot_broken = True
        paused = self.run_round(rid)
        self.assertEqual(paused["status"], "PAUSED")
        self.assertEqual(self.L.orders, [])

    def test_unknown_after_a_busy_retry_is_reconciled_and_never_ordered_twice(self):
        self.L.add("BUSYUSDT", "SHORT", 8.0, mark=100.0); self.seed_pair("BUSYUSDT")
        rid = self.create(["BUSYUSDT"])["round"]["roundId"]
        token = self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "worker")
        R.advance(self.env, self.user, rid)
        self.ns._release_aster_account_coordination(self.uid, token)
        self.L.modes["BUSYUSDT"] = "drop_after_accept"
        done = self.run_round(rid)
        self.assertEqual(len(self.orders_for("BUSYUSDT")), 1)
        self.assertEqual(self.item(done, "BUSYUSDT")["status"], "DONE")

    # --- scope / short-handler: contract errors -----------------------------------------------------------
    def test_only_the_exact_minimum_refusals_are_skips_other_contract_errors_never_skip_or_order(self):
        for msg in ("Deze gedeeltelijke sluiting past niet binnen de Aster contractregels: Order ligt onder de minimale Aster-hoeveelheid",
                    "Deze gedeeltelijke sluiting past niet binnen de Aster contractregels: Order ligt onder de minimale Aster-orderwaarde",
                    "Deze gedeeltelijke sluiting past niet binnen de Aster contractregels: Hoeveelheid en marktprijs moeten positief zijn"):
            self.assertEqual(R._classify_refusal(msg), ("SKIPPED", "too_small"), msg)
        syms = self.shorts(2)
        rid = self.create(syms)["round"]["roundId"]
        broad = "Deze gedeeltelijke sluiting past niet binnen de Aster contractregels: Order ligt boven de maximale Aster-hoeveelheid"
        self.inject[syms[0]] = [(409, broad), (409, broad)]
        paused = self.run_round(rid)
        self.assertEqual(paused["status"], "PAUSED")                            # not skipped, not ordered
        self.assertNotEqual(self.item(paused, syms[0])["status"], "SKIPPED")
        self.assertEqual(self.L.orders, [])

    def test_classification_is_anchored_lookalikes_never_skip_or_retry(self):
        lookalikes = [
            "xx " + BUSY, BUSY + " (timeout, status onbekend)", BUSY.upper(), "HTTP 500", "HTTP 502", "HTTP 504",
            "TradeMentor Cloud is tijdelijk niet bereikbaar",
            "Sluitstatus is niet betrouwbaar bevestigd; er wordt niet opnieuw besteld",
            "xx Open winst is niet meer boven de ingestelde grens; geen order geplaatst",
            "Open winst is niet meer boven de ingestelde grens; geen order geplaatst (onbekend)",
            "Deze gedeeltelijke sluiting past niet binnen de Aster contractregels: Order ligt onder de minimale Aster-hoeveelheid en meer",
            "BTCUSDT: sluiting van 1 SHORT zou Auto Hedge-dekking onder de gereserveerde 2 brengen; daarna onbekend",
            "xx Vorige sluiting van dit symbool is nog niet bevestigd; controleer Aster en gebruik de individuele Close-knop",
        ]
        for msg in lookalikes:
            self.assertIsNone(R._classify_refusal(msg), msg)
            self.assertNotIn(msg, R._BUSY, msg)
        # and on the round: a look-alike busy text is NOT retried as busy, it counts as a system error
        syms = self.shorts(1)
        rid = self.create(syms)["round"]["roundId"]
        self.inject[syms[0]] = [(409, "xx " + BUSY), (409, "xx " + BUSY)]
        paused = self.run_round(rid)
        self.assertEqual(paused["status"], "PAUSED")
        self.assertEqual(self.L.orders, [])

    # --- integration: Auto Hedge consequence never stops the run; worker deferred while ordering -----------
    def test_auto_hedge_shorts_get_the_existing_recovery_transition_and_the_run_continues(self):
        for s in ("AH1USDT", "AH2USDT"):
            self.L.add(s, "SHORT", 8.0, mark=100.0); self.seed_pair(s)
        plain = self.shorts(2)
        deferred = []
        self.L.on_before_order = lambda sym: deferred.append(
            (sym, self.ns._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "POSITION_LOSS_EXACT_1_TO_1")))
        rid = self.create(["AH1USDT", "AH2USDT"] + plain)["round"]["roundId"]
        done = self.run_round(rid)
        self.assertEqual(done["counts"]["done"], 4)
        for s in ("AH1USDT", "AH2USDT"):
            self.assertEqual(self.pair_status(s), "RECOVERY")
            self.assertEqual(self.L.pos[(s, "LONG")], 8.0)
        self.assertEqual([tok for sym, tok in deferred if sym in ("AH1USDT", "AH2USDT")], [None, None])  # worker deferred

    def test_plain_short_that_becomes_an_auto_hedge_pair_after_the_preview_gets_the_manual_transition(self):
        self.L.add("NEWUSDT", "SHORT", 8.0, mark=100.0)
        rid = self.create(["NEWUSDT"])["round"]["roundId"]
        self.seed_pair("NEWUSDT")                                               # pair created after the preview
        done = self.run_round(rid)
        self.assertEqual(self.item(done, "NEWUSDT")["status"], "DONE")
        self.assertEqual(self.pair_status("NEWUSDT"), "RECOVERY")
        self.assertEqual(self.L.pos[("NEWUSDT", "LONG")], 8.0)

    def test_edge_selection_exactly_050_excluded_051_included_losing_and_long_only_never(self):
        self.L.add("EDGE50USDT", "SHORT", 1.0, mark=100.0, entry=100.5)          # pnl exactly 0.50
        self.L.add("EDGE51USDT", "SHORT", 1.0, mark=100.0, entry=100.51)         # pnl 0.51
        self.L.add("LOSSUSDT", "SHORT", 3.0, mark=100.0, entry=95.0)
        self.L.add("LONGUSDT", "LONG", 3.0, mark=100.0)
        rnd = R.create_round(self.env, self.user, percentage=25, idempotency_key=self.key(), targets=[
            {"symbol": s, "side": "SHORT", "quantity": q} for s, q in
            (("EDGE50USDT", 1.0), ("EDGE51USDT", 1.0), ("LOSSUSDT", 3.0), ("LONGUSDT", 3.0))])["round"]
        self.assertEqual(self.item(rnd, "EDGE50USDT")["status"], "SKIPPED")
        self.assertEqual(self.item(rnd, "EDGE51USDT")["status"], "PENDING")
        self.assertEqual(self.item(rnd, "LOSSUSDT")["status"], "SKIPPED")
        self.assertEqual(self.item(rnd, "LONGUSDT")["status"], "SKIPPED")       # no SHORT row -> not selected
        done = self.run_round(rnd["roundId"])
        self.assertEqual([o[0] for o in self.L.orders], ["EDGE51USDT"])
        self.assertTrue(all(o[1] == "SHORT" for o in self.L.orders))


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
