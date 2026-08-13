import unittest

from dca_universe import (
    merge_ranked_pages,
    minimum_complete_count,
    normalize_universe_size,
    page_starts,
    ranked_symbols, symbol_codes,
)


class DcaUniverseTests(unittest.TestCase):
    def test_every_value_inside_supported_range_remains_unchanged(self):
        for value in range(1, 501):
            self.assertEqual(value, normalize_universe_size(value))

    def test_only_documented_outer_bounds_are_clamped(self):
        self.assertEqual(1, normalize_universe_size(0))
        self.assertEqual(500, normalize_universe_size(501))

    def test_requested_rank_controls_returned_symbols(self):
        payload = {"data": [
            {"symbol": "AAA", "cmc_rank": 1},
            {"symbol": "ZZZ", "cmc_rank": 137},
            {"symbol": "OUT", "cmc_rank": 138},
        ]}
        self.assertEqual(["AAA", "ZZZ"], [item["symbol"] for item in ranked_symbols(payload, 137)])
        self.assertEqual(124, minimum_complete_count(137))

    def test_page_plan_supports_all_relevant_user_settings(self):
        self.assertEqual([1], page_starts(30))
        self.assertEqual([1], page_starts(50))
        self.assertEqual([1, 51], page_starts(100))
        self.assertEqual([1, 51, 101], page_starts(137))
        self.assertEqual([1, 51, 101, 151], page_starts(200))

    def test_multiple_fifty_row_pages_fill_top_two_hundred(self):
        pages = []
        for start in (1, 51, 101, 151):
            pages.append({"data": [
                {"symbol": f"PAIR{rank}", "cmc_rank": rank}
                for rank in range(start, start + 50)
            ]})
        merged = merge_ranked_pages(pages, 200)
        self.assertEqual(200, len(merged))
        self.assertEqual(1, merged[0]["rank"])
        self.assertEqual(200, merged[-1]["rank"])

    def test_missing_page_fails_completeness_gate(self):
        pages = [{"data": [
            {"symbol": f"PAIR{rank}", "cmc_rank": rank}
            for rank in range(1, 51)
        ]}]
        merged = merge_ranked_pages(pages, 100)
        self.assertEqual(50, len(merged))
        self.assertLess(len(merged), minimum_complete_count(100))

    def test_symbol_codes_accepts_ranked_objects_and_legacy_strings(self):
        self.assertEqual(["BTC", "ETH"], symbol_codes([{"symbol": "btc", "rank": 1}, "eth", {"symbol": "BTC"}]))


if __name__ == "__main__":
    unittest.main()
