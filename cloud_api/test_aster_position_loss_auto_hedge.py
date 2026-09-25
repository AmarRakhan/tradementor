from __future__ import annotations

import unittest

from aster_position_loss_auto_hedge import evaluate_auto_hedge, reconcile_auto_hedge


def leg(symbol: str, side: str, qty: float, pnl: float):
    return {
        "symbol": symbol,
        "positionSide": side,
        "positionAmt": str(qty),
        "unRealizedProfit": str(pnl),
        "entryPrice": "1",
        "markPrice": "1",
        "leverage": "20",
    }


class PositionLossAutoHedgeTest(unittest.TestCase):
    def action(self, rows, threshold=10, orders=None):
        result = evaluate_auto_hedge(rows, threshold, open_orders=orders or [])
        return result[0] if result else None

    def test_under_threshold_no_hedge(self):
        self.assertIsNone(self.action([leg("DOGEUSDT", "LONG", 100, -9)]))

    def test_exact_threshold_opens_full_opposite(self):
        action = self.action([leg("DOGEUSDT", "LONG", 100, -10)])
        self.assertEqual(action.hedge_side, "SHORT")
        self.assertEqual(action.required_delta, 100)

    def test_far_beyond_threshold_is_immediately_due(self):
        action = self.action([leg("DOGEUSDT", "LONG", 100, -105)])
        self.assertEqual(action.required_delta, 100)

    def test_existing_opposite_only_missing_delta(self):
        action = self.action([
            leg("DOGEUSDT", "LONG", 1000, -105),
            leg("DOGEUSDT", "SHORT", 600, 2),
        ])
        self.assertEqual(action.required_delta, 400)

    def test_already_one_to_one_does_not_stack(self):
        action = self.action([
            leg("DOGEUSDT", "LONG", 1000, -105),
            leg("DOGEUSDT", "SHORT", 1000, 2),
        ])
        self.assertEqual(action.required_delta, 0)
        self.assertEqual(action.status, "HEDGED")

    def test_short_loss_tops_up_long(self):
        action = self.action([
            leg("XRPUSDT", "SHORT", 750, -12),
            leg("XRPUSDT", "LONG", 200, 1),
        ])
        self.assertEqual(action.hedge_side, "LONG")
        self.assertEqual(action.required_delta, 550)

    def test_position_already_below_threshold_before_enable_is_due(self):
        action = self.action([leg("SOLUSDT", "LONG", 8, -80)])
        self.assertEqual(action.required_delta, 8)

    def test_new_position_only_due_after_reaching_threshold(self):
        self.assertIsNone(self.action([leg("SOLUSDT", "LONG", 8, -3)]))
        self.assertEqual(self.action([leg("SOLUSDT", "LONG", 8, -10)]).required_delta, 8)

    def test_pending_order_prevents_duplicate(self):
        order = {
            "symbol": "DOGEUSDT", "positionSide": "SHORT", "side": "SELL",
            "status": "NEW", "origQty": "400", "executedQty": "0",
        }
        action = self.action([
            leg("DOGEUSDT", "LONG", 1000, -105),
            leg("DOGEUSDT", "SHORT", 600, 2),
        ], orders=[order])
        self.assertEqual(action.required_delta, 0)
        self.assertEqual(action.status, "PENDING")

    def test_partial_fill_only_leaves_residual(self):
        order = {
            "symbol": "DOGEUSDT", "positionSide": "SHORT", "side": "SELL",
            "status": "PARTIALLY_FILLED", "origQty": "400", "executedQty": "250",
        }
        action = self.action([
            leg("DOGEUSDT", "LONG", 1000, -105),
            leg("DOGEUSDT", "SHORT", 850, 2),
        ], orders=[order])
        self.assertEqual(action.required_delta, 0)
        self.assertEqual(action.pending_opposite_qty, 150)

    def test_restart_reconciliation_already_hedged_no_order(self):
        action = self.action([
            leg("DOGEUSDT", "LONG", 1000, -105),
            leg("DOGEUSDT", "SHORT", 1000, 3),
        ])
        self.assertEqual(action.required_delta, 0)

    def test_losing_quantity_growth_only_adds_difference(self):
        action = self.action([
            leg("DOGEUSDT", "LONG", 1250, -105),
            leg("DOGEUSDT", "SHORT", 1000, 3),
        ])
        self.assertEqual(action.required_delta, 250)

    def test_multiple_symbols_are_independent(self):
        actions = evaluate_auto_hedge([
            leg("DOGEUSDT", "LONG", 1000, -105),
            leg("DOGEUSDT", "SHORT", 600, 2),
            leg("XRPUSDT", "SHORT", 750, -12),
            leg("XRPUSDT", "LONG", 200, 1),
        ], 10)
        self.assertEqual({a.symbol: a.required_delta for a in actions}, {
            "DOGEUSDT": 400,
            "XRPUSDT": 550,
        })

    def test_non_open_close_order_does_not_count_as_pending_hedge(self):
        close_long = {
            "symbol": "DOGEUSDT", "positionSide": "LONG", "side": "SELL",
            "status": "NEW", "origQty": "100", "executedQty": "0",
        }
        action = self.action([leg("DOGEUSDT", "SHORT", 100, -11)], orders=[close_long])
        self.assertEqual(action.required_delta, 100)

    def test_invalid_threshold_fails_closed(self):
        with self.assertRaises(ValueError):
            evaluate_auto_hedge([leg("DOGEUSDT", "LONG", 100, -20)], 0)

    def test_shadow_mode_never_submits_an_order(self):
        class Client:
            def __init__(self):
                self.submits = 0
            def position_risk(self):
                return [leg("DOGEUSDT", "LONG", 100, -20)]
            def open_orders(self):
                return []
            def submit_order_once(self, *args, **kwargs):
                self.submits += 1
                raise AssertionError("shadow mode must not submit")

        client = Client()
        report = reconcile_auto_hedge(client=client, uid="u1", threshold_usd=10, execute=False)
        self.assertEqual(report["mode"], "SHADOW")
        self.assertEqual(report["ordersSent"], 0)
        self.assertEqual(client.submits, 0)
        self.assertEqual(report["actions"][0]["requiredDelta"], 100)

    def test_insufficient_margin_fails_closed_without_order(self):
        class Client:
            def __init__(self):
                self.submits = 0
            def position_risk(self):
                return [leg("DOGEUSDT", "LONG", 100, -20)]
            def open_orders(self):
                return []
            def position_mode(self):
                return True
            def account_information(self):
                return {"availableBalance": "0"}
            def submit_order_once(self, *args, **kwargs):
                self.submits += 1
                raise AssertionError("insufficient margin must block before submission")

        client = Client()
        report = reconcile_auto_hedge(client=client, uid="u1", threshold_usd=10, execute=True)
        self.assertEqual(client.submits, 0)
        self.assertEqual(report["actions"][0]["status"], "INSUFFICIENT_MARGIN")


if __name__ == "__main__":
    unittest.main()
