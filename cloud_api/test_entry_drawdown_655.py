"""Build 652/655: gem. max drawdown vanaf instap, alleen afgeronde trades (pure logica)."""
import unittest

import entry_drawdown as ed

H = 3_600_000
M15 = 900_000


def record(symbol, side, key, opened, entry, closed, full=True):
    return {"symbol": symbol, "side": side, "closedAtMs": closed, "fullClose": full,
            "cycle": {"cycleKey": key, "openedAtMs": opened, "entryPriceAvg": entry}}


class FakeCandles:
    """Koers per 15m-candle: fn(t) -> (high, low)."""

    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    def __call__(self, symbol, interval, start, end):
        self.calls.append((symbol, interval, start, end))
        size = dict(ed.INTERVALS)[interval]
        rows, t = [], start
        while t <= end and len(rows) < ed.KLINE_LIMIT:
            high, low = self.fn(symbol, t)
            rows.append((t, high, low))
            t += size
        return rows


class EntryDrawdownTest(unittest.TestCase):
    def test_drawdown_formula_per_side(self):
        self.assertAlmostEqual(ed.drawdown_pct("LONG", 100.0, 95.2), 4.8)
        self.assertAlmostEqual(ed.drawdown_pct("SHORT", 100.0, 102.6), 2.6)
        self.assertEqual(ed.drawdown_pct("LONG", 100.0, 105.0), 0.0)   # nooit onder de instap: 0, niet negatief
        self.assertIsNone(ed.drawdown_pct("LONG", 100.0, None))

    def test_median_ignores_one_bad_entry(self):
        self.assertEqual(ed.median([4.0, 5.0, 31.2]), 5.0)
        self.assertEqual(ed.median([4.0, 6.0]), 5.0)
        self.assertIsNone(ed.median([]))

    def test_pick_interval_fits_one_read(self):
        self.assertEqual(ed.pick_interval(10 * 60_000)[0], "1m")
        self.assertEqual(ed.pick_interval(5 * 86_400_000)[0], "15m")
        self.assertEqual(ed.pick_interval(30 * 86_400_000)[0], "1h")

    def test_closed_cycles_only_full_closes_in_window_with_latest_entry(self):
        now = 100 * 86_400_000
        cutoff = now - 30 * 86_400_000
        rows = [
            record("BTCUSDT", "LONG", "a", now - 5 * H, 100.0, now - 3 * H, full=False),  # afbouwstap
            record("BTCUSDT", "LONG", "a", now - 5 * H, 98.0, now - 1 * H, full=True),    # na DCA: nieuwe gem. instap
            record("ETHUSDT", "SHORT", "b", now - 2 * H, 50.0, now - H, full=False),     # nog niet helemaal dicht
            record("SOLUSDT", "LONG", "c", cutoff - 9 * H, 10.0, cutoff - H, full=True),  # buiten het venster
        ]
        cycles = ed.closed_cycles(rows, cutoff)
        self.assertEqual(set(cycles), {"a"})
        self.assertEqual(cycles["a"]["entry"], 98.0)
        self.assertEqual(cycles["a"]["endMs"], now - H)

    def test_trackers_measure_from_entry_moment_only_and_closed_trades_only(self):
        now = 50 * 86_400_000
        opened = now - 10 * H
        closed = now - 2 * H

        def price(symbol, t):
            if t < opened:
                return 200.0, 1.0                       # voor de instap: wilde candles die niet mogen meetellen
            if t < opened + 4 * H:
                return 101.0, 95.0                       # 5% onder instap 100
            return 103.0, 99.0

        fetch = FakeCandles(price)
        cycles = {"a": {"key": "a", "symbol": "BTCUSDT", "side": "LONG", "openedAtMs": opened, "entry": 100.0, "endMs": closed},
                  "b": {"key": "b", "symbol": "BTCUSDT", "side": "SHORT", "openedAtMs": opened, "entry": 100.0, "endMs": closed},
                  "c": {"key": "c", "symbol": "ETHUSDT", "side": "LONG", "openedAtMs": now - H, "entry": 100.0, "endMs": None}}
        trackers = {}
        ed.update_trackers(trackers, cycles, fetch, now_ms=now, max_calls=10)
        summary = ed.summarize(trackers, set(cycles), now_ms=now)
        self.assertEqual(summary["long"]["avgMaxDrawdownPct"], 5.0)
        self.assertEqual(summary["long"]["count"], 1)          # de open ETH-positie telt niet mee
        self.assertEqual(summary["short"]["avgMaxDrawdownPct"], 3.0)
        self.assertTrue(summary["complete"])

        # een afgeronde trade wordt nooit opnieuw gelezen: het getal staat vast
        fetch.calls.clear()
        cycles.pop("c")
        ed.update_trackers(trackers, cycles, fetch, now_ms=now + 3_600_000, max_calls=10)
        self.assertEqual(fetch.calls, [])

    def test_new_open_positions_do_not_move_the_number(self):
        now = 50 * 86_400_000
        closed = {f"k{i}": {"key": f"k{i}", "symbol": f"S{i}USDT", "side": "LONG", "openedAtMs": now - 5 * H,
                            "entry": 100.0, "endMs": now - H} for i in range(3)}
        trackers = {}
        ed.update_trackers(trackers, closed, FakeCandles(lambda s, t: (101.0, 94.0)), now_ms=now, max_calls=10)
        before = ed.summarize(trackers, set(closed), now_ms=now)["long"]["avgMaxDrawdownPct"]
        fresh = {f"n{i}": {"key": f"n{i}", "symbol": f"N{i}USDT", "side": "LONG", "openedAtMs": now - 60_000,
                           "entry": 100.0, "endMs": None} for i in range(10)}
        both = {**closed, **fresh}
        ed.update_trackers(trackers, both, FakeCandles(lambda s, t: (100.1, 99.9)), now_ms=now, max_calls=20)
        self.assertEqual(ed.summarize(trackers, set(both), now_ms=now)["long"]["avgMaxDrawdownPct"], before)

    def test_recent_window_shows_new_strategy(self):
        now = 100 * 86_400_000
        trackers, keys = {}, set()
        for i, (days_ago, worst) in enumerate([(40, 90.0), (30, 92.0), (20, 91.0), (2, 97.0), (1, 98.0)]):
            key = f"t{i}"
            end = now - days_ago * 86_400_000
            trackers[key] = {"side": "LONG", "entry": 100.0, "worst": worst, "endMs": end, "coveredUntilMs": end}
            keys.add(key)
        summary = ed.summarize(trackers, keys, now_ms=now)
        self.assertEqual(summary["long"]["avgMaxDrawdownPct"], 8.0)
        self.assertEqual(summary["long"]["recentAvgMaxDrawdownPct"], 2.5)
        self.assertEqual(summary["long"]["recentCount"], 2)
        self.assertEqual((summary["windowDays"], summary["recentDays"]), (90, 7))

    def test_incomplete_until_every_trade_is_read(self):
        now = 50 * 86_400_000
        cycles = {f"k{i}": {"key": f"k{i}", "symbol": f"S{i}USDT", "side": "LONG", "openedAtMs": now - H,
                            "entry": 10.0, "endMs": now - 60_000} for i in range(5)}
        trackers = {}
        ed.update_trackers(trackers, cycles, FakeCandles(lambda s, t: (10.5, 9.5)), now_ms=now, max_calls=2)
        self.assertFalse(ed.summarize(trackers, set(cycles), now_ms=now)["complete"])
        ed.update_trackers(trackers, cycles, FakeCandles(lambda s, t: (10.5, 9.5)), now_ms=now, max_calls=10)
        self.assertTrue(ed.summarize(trackers, set(cycles), now_ms=now)["complete"])

    def test_symbol_without_candles_is_skipped_not_blocking(self):
        now = 50 * 86_400_000
        cycles = {"x": {"key": "x", "symbol": "GONEUSDT", "side": "LONG", "openedAtMs": now - H, "entry": 10.0, "endMs": now - 1}}
        trackers = {}
        ed.update_trackers(trackers, cycles, lambda *a: [], now_ms=now, max_calls=5)
        summary = ed.summarize(trackers, set(cycles), now_ms=now)
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["long"]["count"], 0)

    def test_budget_leaves_rest_pending(self):
        now = 50 * 86_400_000
        cycles = {f"k{i}": {"key": f"k{i}", "symbol": f"S{i}USDT", "side": "LONG", "openedAtMs": now - H,
                            "entry": 10.0, "endMs": now - 60_000} for i in range(5)}
        trackers = {}
        ed.update_trackers(trackers, cycles, FakeCandles(lambda s, t: (10.5, 9.5)), now_ms=now, max_calls=2)
        summary = ed.summarize(trackers, set(cycles), now_ms=now)
        self.assertEqual(summary["long"]["count"], 2)
        self.assertEqual(summary["long"]["pending"], 3)

    def test_fetch_error_does_not_stop_others(self):
        now = 50 * 86_400_000

        good = FakeCandles(lambda s, t: (10.2, 9.0))

        def fetch(symbol, interval, start, end):
            if symbol == "BADUSDT":
                raise RuntimeError("boom")
            return good(symbol, interval, start, end)

        cycles = {"x": {"key": "x", "symbol": "BADUSDT", "side": "LONG", "openedAtMs": now - H, "entry": 10.0, "endMs": now - 1},
                  "y": {"key": "y", "symbol": "OKUSDT", "side": "LONG", "openedAtMs": now - H, "entry": 10.0, "endMs": now - 1}}
        trackers = {}
        report = ed.update_trackers(trackers, cycles, fetch, now_ms=now, max_calls=10)
        self.assertEqual(report["errors"], 1)
        summary = ed.summarize(trackers, set(cycles), now_ms=now)
        self.assertAlmostEqual(summary["long"]["avgMaxDrawdownPct"], 10.0)
        self.assertFalse(summary["complete"])                 # BAD wordt opnieuw geprobeerd
        for _ in range(ed.MAX_FETCH_ERRORS):
            ed.update_trackers(trackers, cycles, fetch, now_ms=now, max_calls=10)
        self.assertTrue(ed.summarize(trackers, set(cycles), now_ms=now)["complete"])   # na 3 keer overgeslagen

    def test_prune_keeps_window_and_recent_open(self):
        now = 50 * 86_400_000
        cutoff = now - 30 * 86_400_000
        trackers = {
            "old": {"endMs": cutoff - 1, "seenAtMs": now},
            "inwindow": {"endMs": cutoff + 1, "seenAtMs": now - 9 * 86_400_000},
            "openfresh": {"endMs": None, "seenAtMs": now - 3_600_000},
            "openstale": {"endMs": None, "seenAtMs": now - 3 * 86_400_000},
        }
        ed.prune_trackers(trackers, set(), now_ms=now, cutoff_ms=cutoff)
        self.assertEqual(set(trackers), {"inwindow", "openfresh"})


class ExtensionContractTest(unittest.TestCase):
    def test_extension_is_read_only_and_registered(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent
        source = (root / "entry_drawdown_extension.py").read_text(encoding="utf-8")
        core = (root / "entry_drawdown.py").read_text(encoding="utf-8")
        for forbidden in ("submit_order", "cancel_order", "change_leverage", '"POST", "/fapi', "live_authorized=True",
                          "signed_request(", "position_risk"):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, core)
        self.assertIn('@main.app.get("/v1/me/aster/entry-drawdown")', source)
        self.assertIn("import entry_drawdown_extension", (root / "withdraw_app.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
