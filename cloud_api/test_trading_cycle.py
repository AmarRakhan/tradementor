import unittest

from trading_cycle import adjusted_start_value, cycle_payload_values, cycle_start_decision


class TradingCycleTest(unittest.TestCase):
    def test_eighty_percent_target(self):
        before = cycle_payload_values(400.0, 719.99, 80.0)
        reached = cycle_payload_values(400.0, 720.0, 80.0)
        self.assertAlmostEqual(720.0, reached["targetPortfolioValue"])
        self.assertFalse(before["targetReached"])
        self.assertTrue(reached["targetReached"])

    def test_three_hundred_percent_target(self):
        before = cycle_payload_values(400.0, 1599.99, 300.0)
        reached = cycle_payload_values(400.0, 1600.0, 300.0)
        self.assertAlmostEqual(1600.0, reached["targetPortfolioValue"])
        self.assertFalse(before["targetReached"])
        self.assertTrue(reached["targetReached"])

    def test_target_change_never_mutates_start_value(self):
        eighty = cycle_payload_values(400.0, 500.0, 80.0)
        three_hundred = cycle_payload_values(400.0, 500.0, 300.0)
        self.assertAlmostEqual(720.0, eighty["targetPortfolioValue"])
        self.assertAlmostEqual(1600.0, three_hundred["targetPortfolioValue"])

    def test_withdrawal_reduces_baseline_without_becoming_a_trading_loss(self):
        self.assertAlmostEqual(400.0, adjusted_start_value(425.0, -25.0))
        values = cycle_payload_values(425.0, 408.0, 2.0, external_cash_flow=-25.0)
        self.assertAlmostEqual(400.0, values["adjustedStartPortfolioValue"])
        self.assertAlmostEqual(408.0, values["targetPortfolioValue"])
        self.assertTrue(values["targetReached"])

    def test_deposit_raises_baseline_without_becoming_trading_profit(self):
        values = cycle_payload_values(100.0, 150.0, 10.0, external_cash_flow=50.0)
        self.assertAlmostEqual(150.0, values["adjustedStartPortfolioValue"])
        self.assertAlmostEqual(165.0, values["targetPortfolioValue"])
        self.assertFalse(values["targetReached"])

    def test_active_cycle_continues_without_resetting_its_baseline(self):
        self.assertEqual("continue", cycle_start_decision("active", 11))

    def test_finished_cycle_needs_zero_exchange_positions(self):
        self.assertEqual("blocked", cycle_start_decision("completed", 1))
        self.assertEqual("start", cycle_start_decision("completed", 0))


if __name__ == "__main__":
    unittest.main()
