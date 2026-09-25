import unittest

from friends_analytics import _performance, _risk_components, _safe_settings, _public_friend_id


class FriendsAnalyticsTest(unittest.TestCase):
    def test_performance_uses_percentages_only(self):
        daily = {
            "history": [
                {"date": "2026-09-20", "percentage": 2.0, "startEquity": 100.0, "endEquity": 102.0},
                {"date": "2026-09-21", "percentage": -1.0, "startEquity": 102.0, "endEquity": 100.98},
            ],
            "referenceEquity": 100.0,
            "referenceCashflow": 0.0,
            "lastObservedEquity": 101.0,
            "lastObservedCashflow": 0.0,
            "lastObservedDate": "2026-09-22",
        }
        result = _performance(daily, "7D")
        self.assertTrue(result["reliable"])
        self.assertIn("growthPercent", result)
        self.assertNotIn("equity", result)
        self.assertNotIn("usd", result)

    def test_risk_is_reproducible_and_bounded(self):
        settings = {
            "leverage": 100,
            "longDcaDistance": .003,
            "shortDcaDistance": .003,
            "maxDcaLong": 8,
            "maxDcaShort": 8,
            "maximumPositions": 40,
            "stopLossEnabled": False,
            "protectionEnabled": True,
            "trendBollingerEntryEnabled": True,
        }
        perf = {"maxDrawdownPercent": -12.0, "volatilityPercent": 4.0, "measuredDays": 30}
        a = _risk_components(settings, {}, perf)
        b = _risk_components(settings, {}, perf)
        self.assertEqual(a, b)
        self.assertGreaterEqual(a["score"], 0)
        self.assertLessEqual(a["score"], 10)

    def test_safe_settings_never_include_absolute_sizing(self):
        settings = {
            "entryMarginLongUsd": 500,
            "entryMarginShortUsd": 600,
            "entryNotionalLongUsd": 50000,
            "focusStartOrderNotional": 10000,
            "leverage": 50,
            "longDcaDistance": .003,
            "maxDcaLong": 5,
        }
        risk = _risk_components(settings, {}, {"maxDrawdownPercent": -4, "volatilityPercent": 1, "measuredDays": 7})
        rows = _safe_settings(settings, risk, {})
        serialized = str(rows)
        self.assertNotIn("50000", serialized)
        self.assertNotIn("10000", serialized)
        self.assertNotIn("$", serialized)

    def test_public_id_does_not_expose_uid(self):
        uid = "sensitive-user-identifier"
        value = _public_friend_id(uid)
        self.assertNotIn(uid, value)
        self.assertEqual(len(value), 16)


if __name__ == "__main__":
    unittest.main()
