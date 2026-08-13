import unittest

from hyperliquid_account_state import direction_available, normalize_hyperliquid_account_state


class HyperliquidAccountStateTests(unittest.TestCase):
    def test_unified_account_matches_exchange_economic_values(self):
        positions = [
            {"position": {"coin": "BTC", "szi": "0.1", "unrealizedPnl": "-7.50"}},
            {"position": {"coin": "ETH", "szi": "-1", "unrealizedPnl": "-4.33"}},
        ]
        state = normalize_hyperliquid_account_state(
            {
                "marginSummary": {
                    "accountValue": "132.06", "totalNtlPos": "737.91574",
                    "totalMarginUsed": "129.52",
                },
                "crossMaintenanceMarginUsed": "64.75",
                "withdrawable": "0",
                "assetPositions": positions,
            },
            {"balances": [{"coin": "USDC", "token": 0, "total": "300.60", "hold": "132.06"}]},
            "unifiedAccount",
            {"availableToTrade": ["171.64", "171.05"]},
            asset="BTC",
        )
        self.assertEqual(state["portfolioValue"], 300.60)
        self.assertEqual(state["availableToTrade"], 171.64)
        self.assertEqual(direction_available(state, False), 171.64)
        self.assertEqual(direction_available(state, True), 171.05)
        self.assertAlmostEqual(state["unrealizedPnl"], -11.83)
        self.assertEqual(state["maintenanceMargin"], 64.75)
        self.assertEqual(state["activeTradeCapital"], 129.52)
        self.assertAlmostEqual(state["unifiedAccountLeverage"], 737.91574 / 300.60)
        self.assertEqual(state["activePositionCount"], 2)

    def test_default_account_keeps_legacy_exchange_fields(self):
        state = normalize_hyperliquid_account_state(
            {"marginSummary": {"accountValue": "95", "totalNtlPos": "190"}, "withdrawable": "40"},
            {"balances": [{"coin": "USDC", "total": "500"}]},
            "defaultAccount",
        )
        self.assertEqual(state["portfolioValue"], 95)
        self.assertEqual(state["availableToTrade"], 40)
        self.assertEqual(state["unifiedAccountLeverage"], 2)


if __name__ == "__main__":
    unittest.main()
