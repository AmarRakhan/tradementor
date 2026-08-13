import unittest

from hyperliquid_scanner import (
    MarketSnapshot, ScannerSettings, add_on_due, balance_permits,
    choose_entries, select_candidates,
)


class HyperliquidScannerTests(unittest.TestCase):
    def test_direct_ranks_movement_and_excludes_btc_active_and_outside_universe(self):
        settings = ScannerSettings(entry_mode="direct", top_universe_size=100)
        markets = [
            MarketSnapshot("BTC", 100, 90, 50),
            MarketSnapshot("SOL", 110, 100, 20),
            MarketSnapshot("ENA", 90, 100, 10),
            MarketSnapshot("DOGE", 120, 100, 10),
            MarketSnapshot("APT", 70, 100, 10),
        ]
        result = select_candidates(markets, allowed_symbols={"SOL", "ENA", "DOGE", "APT"}, active_symbols={"DOGE"}, settings=settings)
        self.assertEqual([item.symbol for item in result], ["APT", "SOL", "ENA"])
        self.assertTrue(result[0].short)
        self.assertFalse(result[1].short)

    def test_bollinger_requires_direction_specific_extreme(self):
        closes = tuple([100.0] * 20)
        settings = ScannerSettings(entry_mode="bollinger")
        markets = [
            MarketSnapshot("LONG", 98, 90, 10, closes),
            MarketSnapshot("SHORT", 102, 110, 10, closes),
            MarketSnapshot("INSIDE", 100, 90, 10, closes),
        ]
        result = select_candidates(markets, allowed_symbols={"LONG", "SHORT", "INSIDE"}, active_symbols=set(), settings=settings)
        self.assertEqual([(item.symbol, item.short) for item in result], [("LONG", False), ("SHORT", True)])

    def test_balance_gate_recovers_and_stays_inside_three(self):
        self.assertFalse(balance_permits(False, 4, 1))
        self.assertTrue(balance_permits(True, 4, 1))
        candidates = select_candidates(
            [MarketSnapshot("A", 110, 100, 10), MarketSnapshot("B", 90, 100, 10), MarketSnapshot("C", 120, 100, 10)],
            allowed_symbols={"A", "B", "C"}, active_symbols=set(), settings=ScannerSettings(entry_mode="direct"),
        )
        selected = choose_entries(candidates, active_count=0, maximum=2, long_count=0, short_count=0)
        self.assertEqual(len(selected), 2)

    def test_dca_ladder_is_measured_from_initial_entry_for_long_and_short(self):
        settings = ScannerSettings(long_deviation_percent=2, short_deviation_percent=8, max_safety_orders=3)
        self.assertTrue(add_on_due(short=False, current_price=98, initial_entry_price=100, safety_orders_completed=0, settings=settings))
        self.assertFalse(add_on_due(short=False, current_price=97, initial_entry_price=100, safety_orders_completed=1, settings=settings))
        self.assertTrue(add_on_due(short=False, current_price=96, initial_entry_price=100, safety_orders_completed=1, settings=settings))
        self.assertTrue(add_on_due(short=True, current_price=108, initial_entry_price=100, safety_orders_completed=0, settings=settings))
        self.assertTrue(add_on_due(short=True, current_price=116, initial_entry_price=100, safety_orders_completed=1, settings=settings))

    def test_invalid_settings_fail_closed(self):
        settings = ScannerSettings(base_order_usd=8, max_safety_orders=30, top_universe_size=0)
        self.assertGreaterEqual(len(settings.validate()), 3)


if __name__ == "__main__":
    unittest.main()
