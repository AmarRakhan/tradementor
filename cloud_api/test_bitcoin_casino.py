import unittest

from bitcoin_casino import ALLOWED_DURATIONS, directional_signal, price_result, rolling_backtest, validate_trade


class BitcoinCasinoRulesTest(unittest.TestCase):
    def test_exact_supported_durations(self):
        self.assertEqual({60, 300, 900, 3600, 14400, 86400}, ALLOWED_DURATIONS)

    def test_limits_reject_invalid_trade(self):
        validate_trade(60, 10)
        with self.assertRaises(ValueError):
            validate_trade(120, 10)
        with self.assertRaises(ValueError):
            validate_trade(60, 5)

    def test_directional_result_is_symmetric(self):
        self.assertAlmostEqual(5.0, price_result(False, 100, 105))
        self.assertAlmostEqual(-5.0, price_result(True, 100, 105))

    def test_signal_always_has_direction(self):
        self.assertIn(directional_signal([100.0] * 20)["direction"], {"long", "short"})
        self.assertIn(directional_signal([100.0] * 5)["direction"], {"long", "short"})
        self.assertEqual("long", directional_signal([100.0] * 15 + [110.0] * 5)["direction"])

    def test_walk_forward_backtest_is_limited_and_resolved(self):
        closes = [100.0 + index * 0.1 for index in range(1100)]
        result = rolling_backtest(closes, list(range(1100)), 1000)
        self.assertEqual(1000, len(result["predictions"]))
        self.assertEqual(1000, result["won"] + result["lost"])
        self.assertTrue(all(row["outcome"] in {"win", "loss"} for row in result["predictions"]))


if __name__ == "__main__":
    unittest.main()
