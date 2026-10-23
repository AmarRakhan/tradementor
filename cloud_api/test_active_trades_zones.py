import math
import unittest

from active_trades_zones import basket_index_candles, derive_sr_zones, kline_candles, long_basket


def bars(closes, start=1_700_000_000_000, step=900_000, wick=0.3):
    rows = []
    previous = closes[0]
    for index, close in enumerate(closes):
        opened = previous
        rows.append({"atMs": start + index * step, "open": opened, "high": max(opened, close) + wick,
                     "low": min(opened, close) - wick, "close": close})
        previous = close
    return rows


class LongBasketTests(unittest.TestCase):
    def test_short_hedges_are_excluded_and_weights_use_current_notional(self):
        basket = long_basket([
            {"symbol": "BTCUSDT", "side": "LONG", "quantity": 1, "markPrice": 300, "notionalUsd": 300},
            {"symbol": "BTCUSDT", "side": "SHORT", "quantity": 1, "markPrice": 300, "notionalUsd": 300},
            {"symbol": "ETHUSDT", "side": "LONG", "quantity": 2, "markPrice": 50},
        ])
        symbols = {row["symbol"]: row for row in basket["symbols"]}
        self.assertEqual(set(symbols), {"BTCUSDT", "ETHUSDT"})
        self.assertAlmostEqual(symbols["BTCUSDT"]["weight"], 0.75)
        self.assertAlmostEqual(symbols["ETHUSDT"]["weight"], 0.25)
        self.assertEqual(basket["weighting"], "CURRENT_NOTIONAL_LONG_ONLY")

    def test_only_shorts_gives_empty_basket(self):
        self.assertEqual(long_basket([{"symbol": "X", "side": "SHORT", "quantity": 1, "markPrice": 1}])["symbols"], [])

    def test_max_symbols_reports_coverage(self):
        rows = [{"symbol": f"C{i}", "side": "LONG", "notionalUsd": 10 + i} for i in range(5)]
        basket = long_basket(rows, max_symbols=2)
        self.assertEqual([row["symbol"] for row in basket["symbols"]], ["C4", "C3"])
        self.assertAlmostEqual(basket["coveragePercent"], (14 + 13) / sum(10 + i for i in range(5)) * 100)


class IndexTests(unittest.TestCase):
    def test_kline_rows_parse_and_dedupe(self):
        rows = kline_candles([[2, "1", "2", "0.5", "1.5"], [1, "1", "1", "1", "1"], [2, "1", "3", "0.5", "2"], ["x"]])
        self.assertEqual([row["atMs"] for row in rows], [1, 2])
        self.assertEqual(rows[-1]["close"], 2.0)

    def test_constant_weight_index_starts_at_100_and_tracks_weighted_returns(self):
        a = bars([100, 110, 120], wick=0)
        b = bars([10, 10, 5], wick=0)
        basket = {"symbols": [{"symbol": "A", "weight": 0.5}, {"symbol": "B", "weight": 0.5}]}
        result = basket_index_candles(basket, {"A": a, "B": b})
        closes = [round(row["close"], 6) for row in result["candles"]]
        self.assertAlmostEqual(result["candles"][0]["open"], 100.0)
        self.assertEqual(closes, [100.0, 105.0, 85.0])
        for candle in result["candles"]:
            self.assertGreaterEqual(candle["high"], max(candle["open"], candle["close"]))
            self.assertLessEqual(candle["low"], min(candle["open"], candle["close"]))

    def test_short_history_symbol_is_dropped_and_weights_renormalised(self):
        long_series = bars([100 + i for i in range(20)], wick=0)
        short_series = bars([50, 51], wick=0)
        basket = {"symbols": [{"symbol": "A", "weight": 0.5}, {"symbol": "NEW", "weight": 0.5}]}
        result = basket_index_candles(basket, {"A": long_series, "NEW": short_series})
        self.assertEqual(result["usedSymbols"], ["A"])
        self.assertEqual(result["droppedSymbols"], ["NEW"])
        self.assertEqual(len(result["candles"]), 20)
        self.assertAlmostEqual(result["candles"][-1]["close"], 119.0)


class SupportResistanceTests(unittest.TestCase):
    def range_then_breakout(self):
        cycle = [100, 102, 104, 106, 108, 110, 108, 106, 104, 102]
        closes = cycle * 4 + [104, 108, 112, 116, 113, 110.6, 112, 115, 118, 117, 116]
        return bars(closes, wick=0.4)

    def test_range_produces_support_and_resistance_with_touches(self):
        result = derive_sr_zones(bars([100, 102, 104, 106, 108, 110, 108, 106, 104, 102] * 5 + [104], wick=0.4))
        prices = [level["price"] for level in result["levels"]]
        self.assertTrue(any(abs(price - 110.4) < 1 for price in prices), prices)
        self.assertTrue(any(abs(price - 99.6) < 1.5 for price in prices), prices)
        top = max(result["levels"], key=lambda level: level["price"])
        self.assertGreaterEqual(top["touches"], 3)
        self.assertEqual(top["kind"], "resistance")
        self.assertIsNotNone(result["activeZone"])
        self.assertEqual(result["activeZone"]["index"], 0)

    def test_break_and_retest_flips_resistance_to_support(self):
        result = derive_sr_zones(self.range_then_breakout())
        old_top = min((level for level in result["levels"] if abs(level["price"] - 110.4) < 1), key=lambda level: abs(level["price"] - 110.4))
        self.assertEqual(old_top["kind"], "support")
        self.assertTrue(old_top["flipped"])
        self.assertIsNotNone(old_top["flipAtMs"])

    def test_break_without_retest_is_not_a_flip(self):
        cycle = [100, 102, 104, 106, 108, 110, 108, 106, 104, 102]
        closes = cycle * 4 + [104, 108, 112, 116, 120, 124, 128, 132, 136, 140]
        result = derive_sr_zones(bars(closes, wick=0.4))
        old_top = min(result["levels"], key=lambda level: abs(level["price"] - 110.4))
        self.assertFalse(old_top["flipped"])
        self.assertTrue(old_top["brokenAwaitingRetest"])

    def test_zones_are_contiguous_and_unequal_widths_allowed(self):
        result = derive_sr_zones(self.range_then_breakout())
        for previous, current in zip(result["zones"], result["zones"][1:]):
            self.assertAlmostEqual(previous["upper"], current["lower"])
            self.assertEqual(current["index"], previous["index"] + 1)

    def test_untouched_old_resistance_is_not_flipped(self):
        result = derive_sr_zones(bars([100, 102, 104, 106, 108, 110, 108, 106, 104, 102] * 5 + [104], wick=0.4))
        self.assertFalse(any(level["flipped"] for level in result["levels"]))

    def test_fresh_breakdown_gets_provisional_support_and_active_zone(self):
        closes = [100, 102, 104, 106, 108, 110, 108, 106, 104, 102] * 4 + [100, 97, 94, 91, 88]
        result = derive_sr_zones(bars(closes, wick=0.4))
        self.assertTrue(result["levels"][0].get("provisional"))
        self.assertEqual(result["levels"][0]["kind"], "support")
        self.assertIsNotNone(result["activeZone"])
        self.assertLessEqual(result["activeZone"]["lower"], result["lastClose"])

    def test_too_few_candles(self):
        self.assertEqual(derive_sr_zones(bars([1, 2, 3]))["reason"], "TOO_FEW_CANDLES")

    def test_no_nan_in_output(self):
        result = derive_sr_zones(self.range_then_breakout())
        for level in result["levels"]:
            self.assertTrue(math.isfinite(level["price"]))



class RouteWiringTests(unittest.TestCase):
    def test_route_is_read_only_and_feature_gated(self):
        from pathlib import Path
        source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        start = source.index('@app.get("/v1/me/aster/portfolio-chart/active-zones")')
        body = source[start:source.index('@app.get("/v1/me/aster/portfolio-chart")', start)]
        self.assertIn('require_release_feature(user, "active_trades_chart")', body)
        self.assertIn('"ordersSent": 0', body)
        for forbidden in ("submit_order", "place_order", "signed_request", "load_aster_secret", ".set(", ".update("):
            self.assertNotIn(forbidden, body)


if __name__ == "__main__":
    unittest.main()
