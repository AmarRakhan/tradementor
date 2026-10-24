"""Build 652: gem. max drawdown vanaf instap (pure logica)."""
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

    def test_open_cycles_use_journal_then_bot_start_else_unknown(self):
        positions = [
            {"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "0.5", "entryPrice": "100"},
            {"symbol": "ETHUSDT", "positionSide": "SHORT", "positionAmt": "-2", "entryPrice": "50"},
            {"symbol": "XRPUSDT", "positionSide": "SHORT", "positionAmt": "-10", "entryPrice": "1"},
            {"symbol": "DOGEUSDT", "positionSide": "LONG", "positionAmt": "0", "entryPrice": "0"},
        ]
        journal = {"BTCUSDT": {"LONG": {"cycleKey": "BTCUSDT|LONG|7", "openedAtMs": 1000, "exposure": 0.5}}}
        bot = {"ETHUSDT|SHORT": {"cycleStartedAtMs": 2000}}
        cycles, unknown = ed.open_cycles(positions, journal, bot)
        self.assertEqual(set(cycles), {"BTCUSDT|LONG|7", "ETHUSDT|SHORT|bot2000"})
        self.assertEqual(cycles["BTCUSDT|LONG|7"]["entry"], 100.0)   # instapprijs van Aster
        self.assertIsNone(cycles["ETHUSDT|SHORT|bot2000"]["endMs"])
        self.assertEqual(unknown, {"XRPUSDT"})

    def test_trackers_measure_from_entry_moment_only(self):
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
                  "b": {"key": "b", "symbol": "BTCUSDT", "side": "SHORT", "openedAtMs": opened, "entry": 100.0, "endMs": None}}
        trackers = {}
        report = ed.update_trackers(trackers, cycles, fetch, now_ms=now, max_calls=10)
        self.assertEqual(report["calls"], 1)                # zelfde munt: één lezing voor beide posities
        summary = ed.summarize(trackers, set(cycles))
        self.assertEqual(summary["long"]["avgMaxDrawdownPct"], 5.0)
        self.assertEqual(summary["short"]["avgMaxDrawdownPct"], 3.0)
        self.assertEqual(summary["long"]["closedCount"], 1)
        self.assertEqual(summary["short"]["openCount"], 1)

        # gesloten positie wordt niet opnieuw gelezen; open positie leest alleen het nieuwe stuk
        fetch.calls.clear()
        ed.update_trackers(trackers, cycles, fetch, now_ms=now + 10 * 60_000, max_calls=10)
        self.assertEqual(len(fetch.calls), 1)
        self.assertGreaterEqual(fetch.calls[0][2], now - M15)

    def test_budget_leaves_rest_pending(self):
        now = 50 * 86_400_000
        cycles = {f"k{i}": {"key": f"k{i}", "symbol": f"S{i}USDT", "side": "LONG", "openedAtMs": now - H,
                            "entry": 10.0, "endMs": now - 60_000} for i in range(5)}
        trackers = {}
        ed.update_trackers(trackers, cycles, FakeCandles(lambda s, t: (10.5, 9.5)), now_ms=now, max_calls=2)
        summary = ed.summarize(trackers, set(cycles))
        self.assertEqual(summary["long"]["count"], 2)
        self.assertEqual(summary["long"]["pending"], 3)

    def test_fetch_error_does_not_stop_others(self):
        now = 50 * 86_400_000

        def fetch(symbol, interval, start, end):
            if symbol == "BADUSDT":
                raise RuntimeError("boom")
            return [(start, 10.2, 9.0)]

        cycles = {"x": {"key": "x", "symbol": "BADUSDT", "side": "LONG", "openedAtMs": now - H, "entry": 10.0, "endMs": now - 1},
                  "y": {"key": "y", "symbol": "OKUSDT", "side": "LONG", "openedAtMs": now - H, "entry": 10.0, "endMs": now - 1}}
        trackers = {}
        report = ed.update_trackers(trackers, cycles, fetch, now_ms=now, max_calls=10)
        self.assertEqual(report["errors"], 1)
        self.assertAlmostEqual(ed.summarize(trackers, set(cycles))["long"]["avgMaxDrawdownPct"], 10.0)

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
        for forbidden in ("submit_order", "cancel_order", "change_leverage", '"POST", "/fapi', "live_authorized=True", "signed_request("):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, core)
        self.assertIn('@main.app.get("/v1/me/aster/entry-drawdown")', source)
        self.assertIn("import entry_drawdown_extension", (root / "withdraw_app.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
