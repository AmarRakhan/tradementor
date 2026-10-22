"""Chart-label fix (#738): the chart routes keep the confirmed fill-activity cache warm themselves.

Unit tests of the warm-up helper (pure, no network) plus static wiring checks on main.py. The real-stack proof
(FastAPI + Firestore emulator + HTTP-fake Aster) is test_chart_markers_cold_cache_e2e.py."""
from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path

from closed_trades_warmup import (CHANGE_BACKOFF_SECONDS, RETRY_BACKOFF_SECONDS, WARM_MAX_AGE_SECONDS,
                                  ClosedTradesWarmup, account_fingerprint)

ACTIVITY = {"entries": [{"symbol": "BTCUSDT", "side": "LONG"}], "exits": [{"symbol": "AAOIUSDT", "side": "SHORT"}]}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class WarmupTests(unittest.TestCase):
    def setUp(self):
        self.cache, self.lock, self.clock, self.calls = {}, threading.RLock(), Clock(), []

        def loader(user):                                  # what aster_closed_trades does on success
            self.calls.append(user["uid"])
            with self.lock:
                self.cache[user["uid"]] = (self.clock(), [], [], ACTIVITY, {})
        self.loader = loader
        self.w = ClosedTradesWarmup(self.cache, self.lock, lambda user: self.loader(user), clock=self.clock)

    def test_cold_cache_is_loaded_once_and_returned(self):
        entry = self.w.ensure("u1", {"uid": "u1"})
        self.assertEqual(entry[3], ACTIVITY)
        self.assertEqual(self.calls, ["u1"])
        self.w.ensure("u1", {"uid": "u1"})                   # fresh: no second exchange round-trip
        self.assertEqual(self.calls, ["u1"])

    def test_fresh_cache_from_the_flip_card_is_reused_without_a_call(self):
        self.cache["u1"] = (self.clock(), [], [], ACTIVITY, {})
        self.assertEqual(self.w.ensure("u1", {"uid": "u1"})[3], ACTIVITY)
        self.assertEqual(self.calls, [])

    def test_stale_cache_is_refreshed_after_ten_minutes(self):
        self.cache["u1"] = (self.clock(), [], [], {"entries": [], "exits": []}, {})
        self.clock.t += WARM_MAX_AGE_SECONDS - 1
        self.w.ensure("u1", {"uid": "u1"})
        self.assertEqual(self.calls, [])
        self.clock.t += 2
        self.assertEqual(self.w.ensure("u1", {"uid": "u1"})[3], ACTIVITY)
        self.assertEqual(self.calls, ["u1"])

    def test_failing_history_never_breaks_the_chart_and_is_backed_off(self):
        def failing(user):
            self.calls.append("fail")
            raise RuntimeError("Aster unreachable")
        self.loader = failing
        self.assertIsNone(self.w.ensure("u1", {"uid": "u1"}))   # no exception, chart renders without labels
        self.w.ensure("u1", {"uid": "u1"})
        self.assertEqual(self.calls, ["fail"])                  # backoff: no hammering of Aster's shared-IP quota
        self.clock.t += RETRY_BACKOFF_SECONDS + 1
        self.w.ensure("u1", {"uid": "u1"})
        self.assertEqual(self.calls, ["fail", "fail"])

    def test_a_failure_keeps_the_last_cache_entry(self):
        old = (self.clock(), [], [], ACTIVITY, {})
        self.cache["u1"] = old
        self.clock.t += WARM_MAX_AGE_SECONDS + 1
        self.loader = lambda user: (_ for _ in ()).throw(RuntimeError("x"))
        self.assertIs(self.w.ensure("u1", {"uid": "u1"}), old)

    def test_accounts_are_isolated(self):
        self.w.ensure("u1", {"uid": "u1"})
        self.w.ensure("u2", {"uid": "u2"})
        self.assertEqual(self.calls, ["u1", "u2"])
        self.assertEqual(set(self.cache), {"u1", "u2"})

    def test_concurrent_chart_requests_trigger_one_load(self):
        gate = threading.Event()

        def slow(user):
            self.calls.append(user["uid"])
            gate.wait(2)
            with self.lock:
                self.cache[user["uid"]] = (self.clock(), [], [], ACTIVITY, {})
        self.loader = slow
        threads = [threading.Thread(target=self.w.ensure, args=("u1", {"uid": "u1"})) for _ in range(8)]
        [t.start() for t in threads]
        time.sleep(0.2)
        gate.set()
        [t.join() for t in threads]
        self.assertEqual(self.calls, ["u1"])


    # --- Live refresh: a close made right now must reach the chart without waiting 10 minutes -----------------------
    def fp(self, ms, wallet, positions=124):
        return account_fingerprint({"walletBalance": str(wallet), "activePositions": positions}, ms)

    def test_a_new_close_refreshes_the_fresh_cache_at_once(self):
        self.w.ensure("u1", {"uid": "u1"}, self.fp(1_000, "250.10"))        # cold load
        self.clock.t += CHANGE_BACKOFF_SECONDS + 1                           # well inside the 10-minute window
        self.w.ensure("u1", {"uid": "u1"}, self.fp(2_000, "250.10"))        # nothing happened: no call
        self.assertEqual(self.calls, ["u1"])
        self.w.ensure("u1", {"uid": "u1"}, self.fp(3_000, "250.76"))        # Close Profits realized +$0.66
        self.assertEqual(self.calls, ["u1", "u1"])

    def test_a_full_close_with_unchanged_wallet_rounding_still_counts_by_position_count(self):
        self.w.ensure("u1", {"uid": "u1"}, self.fp(1_000, "250.10", 124))
        self.clock.t += CHANGE_BACKOFF_SECONDS + 1
        self.w.ensure("u1", {"uid": "u1"}, self.fp(2_000, "250.10", 123))
        self.assertEqual(self.calls, ["u1", "u1"])

    def test_an_older_snapshot_from_another_route_never_counts_as_a_change(self):
        self.w.ensure("u1", {"uid": "u1"}, self.fp(5_000, "250.76"))
        self.clock.t += CHANGE_BACKOFF_SECONDS + 1
        self.w.ensure("u1", {"uid": "u1"}, self.fp(4_000, "250.10"))        # stale stored snapshot
        self.w.ensure("u1", {"uid": "u1"}, self.fp(5_000, "250.10"))        # same moment, other source
        self.assertEqual(self.calls, ["u1"])

    def test_a_change_inside_the_backoff_is_remembered_and_refreshed_afterwards(self):
        self.w.ensure("u1", {"uid": "u1"}, self.fp(1_000, "250.10"))
        self.clock.t += 5
        self.w.ensure("u1", {"uid": "u1"}, self.fp(2_000, "251.00"))        # change, but within 45 s of the load
        self.assertEqual(self.calls, ["u1"])
        self.clock.t += CHANGE_BACKOFF_SECONDS
        self.w.ensure("u1", {"uid": "u1"}, self.fp(3_000, "251.00"))        # same value again, change not lost
        self.assertEqual(self.calls, ["u1", "u1"])
        self.clock.t += CHANGE_BACKOFF_SECONDS + 1
        self.w.ensure("u1", {"uid": "u1"}, self.fp(4_000, "251.00"))
        self.assertEqual(self.calls, ["u1", "u1"])                          # and refreshed only once

    def test_continuous_trading_refreshes_at_most_once_per_backoff(self):
        self.w.ensure("u1", {"uid": "u1"}, self.fp(1, "100"))
        for i in range(2, 121):                                              # 10 minutes of 5 s polls, a fill each time
            self.clock.t += 5
            self.w.ensure("u1", {"uid": "u1"}, self.fp(i * 5_000, str(100 + i)))
        self.assertLessEqual(len(self.calls), 1 + 600 // CHANGE_BACKOFF_SECONDS + 1)

    def test_no_fingerprint_keeps_the_old_age_behaviour(self):
        self.w.ensure("u1", {"uid": "u1"})
        self.clock.t += CHANGE_BACKOFF_SECONDS + 1
        self.w.ensure("u1", {"uid": "u1"}, None)
        self.w.ensure("u1", {"uid": "u1"}, account_fingerprint({}, 5_000))  # snapshot without wallet balance
        self.assertEqual(self.calls, ["u1"])

    def test_fingerprint_is_stable_for_identical_snapshots(self):
        a = account_fingerprint({"walletBalance": "250.1000", "activePositions": 3}, 1)
        b = account_fingerprint({"walletBalance": 250.1, "activePositions": "3"}, 2)
        self.assertEqual(a[1], b[1])
        self.assertIsNone(account_fingerprint({"walletBalance": "x"}, 1))
        self.assertIsNone(account_fingerprint({"walletBalance": "1"}, 0))


class WiringTests(unittest.TestCase):
    SRC = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")

    def block(self, start, end):
        s = self.SRC.index(start)
        return self.SRC[s:self.SRC.index(end, s + 1)]

    def test_both_chart_routes_use_the_warmup_for_their_markers(self):
        chart = self.block('@app.get("/v1/me/aster/portfolio-chart")', '@app.get("/v1/me/aster/trade-events")')
        self.assertIn("history_cache = _closed_trades_warmup.ensure(uid, user, account_fingerprint(snapshot, captured_ms))", chart)
        self.assertIn("recent_activity = _chart_recent_activity(uid, history_cache)", chart)
        self.assertNotIn("history_cache = _aster_closed_trades_cache.get(uid)", chart)
        active = self.block("def aster_portfolio_chart_active_trades(", "\n@app.")
        self.assertIn("history_cache = _closed_trades_warmup.ensure(uid, user, account_fingerprint(snapshot, captured_ms))", active)
        self.assertIn("recent_activity = _chart_recent_activity(uid, history_cache)", active)

    def test_warmup_uses_the_lean_read_only_fill_loader(self):
        # Kostenreductie 4.1: the warm-up must NOT re-run the full closed-trades loader, which re-reads up to
        # 2 x 5,000 realized-event documents and all profit sweeps from Firestore on every refresh.
        self.assertIn("_closed_trades_warmup = ClosedTradesWarmup(_chart_fill_activity_cache, _cache_lock,", self.SRC)
        self.assertIn("lambda user: _load_chart_fill_activity(user))", self.SRC)
        self.assertNotIn("lambda user: aster_closed_trades(user))", self.SRC)
        loader = self.block("def _load_chart_fill_activity(", "\ndef ")
        self.assertIn("live_authorized=False", loader)
        for forbidden in ("submit_order", "execute_aster_leg", "live_authorized=True", "_stored_aster_realized_events",
                          "_persist_aster_realized_events", "_verified_aster_daily_close_summary",
                          "_stored_aster_closed_trades(", ".stream()", "aster_closed_trades(user)"):
            self.assertNotIn(forbidden, loader)

    def test_flip_card_reuse_keeps_its_own_load_time(self):
        loader = self.block("def _load_chart_fill_activity(", "\ndef ")
        self.assertIn("_chart_fill_activity_cache[uid] = (flip_card[0], [], [], activity, meta)", loader)
        self.assertNotIn("_chart_fill_activity_cache[uid] = (now, [], [], activity", loader)

    def test_symbols_with_a_new_close_are_always_fetched(self):
        loader = self.block("def _load_chart_fill_activity(", "\ndef ")
        self.assertIn('int(safe_float(row.get("time"))) > income_cursor_ms', loader)
        self.assertIn("symbols = list(dict.fromkeys([*new_close_symbols, *symbols]))", loader)
        self.assertIn('{"incomeCursorMs": max(newest_income_ms, income_cursor_ms)}', loader)

    def test_events_feed_and_marker_builders_are_unchanged(self):
        events = self.block('@app.get("/v1/me/aster/portfolio-chart/events")', '@app.get("/v1/me/aster/portfolio-chart/audit")')
        self.assertNotIn("_closed_trades_warmup", events)     # the fast feed stays exchange-free

    def test_helper_has_no_order_path(self):
        src = (Path(__file__).parent / "closed_trades_warmup.py").read_text(encoding="utf-8")
        for forbidden in ("import main", "aster_gateway", "aster_execution", "submit", "httpx"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
