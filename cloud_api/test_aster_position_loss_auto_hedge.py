from __future__ import annotations

import unittest

from aster_position_loss_auto_hedge import evaluate_auto_hedge, reconcile_auto_hedge


def leg(symbol: str, side: str, qty: float, pnl: float, *, mark: float = 1.0):
    return {
        "symbol": symbol,
        "positionSide": side,
        "positionAmt": str(qty),
        "unRealizedProfit": str(pnl),
        "entryPrice": str(mark),
        "markPrice": str(mark),
        "leverage": "20",
    }


def rule(symbol: str = "DOGEUSDT", step: str = "1"):
    return {
        "symbol": symbol,
        "filters": [
            {"filterType": "PRICE_FILTER", "minPrice": "0.000001", "maxPrice": "1000000", "tickSize": "0.000001"},
            {"filterType": "LOT_SIZE", "minQty": step, "maxQty": "100000000", "stepSize": step},
            {"filterType": "MARKET_LOT_SIZE", "minQty": step, "maxQty": "100000000", "stepSize": step},
            {"filterType": "MIN_NOTIONAL", "notional": "0"},
        ],
    }


class PositionLossAutoHedgeTest(unittest.TestCase):
    def action(self, rows, threshold=10, orders=None, protected=None, skip=None):
        result = evaluate_auto_hedge(
            rows, threshold, open_orders=orders or [],
            protected_sides=protected, skip_symbols=skip,
        )
        return result[0] if result else None

    def test_threshold_contract(self):
        self.assertIsNone(self.action([leg("DOGEUSDT", "LONG", 100, -9.99)]))
        exact = self.action([leg("DOGEUSDT", "LONG", 100, -10)])
        self.assertEqual(exact.operation, "OPEN")
        self.assertEqual(exact.required_delta, 100)
        deep = self.action([leg("DOGEUSDT", "LONG", 100, -100)])
        self.assertEqual(deep.required_delta, 100)

    def test_missing_opposite_opens_only_difference(self):
        action = self.action([
            leg("DOGEUSDT", "SHORT", 1000, -105),
            leg("DOGEUSDT", "LONG", 600, 2),
        ])
        self.assertEqual(action.hedge_side, "LONG")
        self.assertEqual(action.operation, "OPEN")
        self.assertEqual(action.required_delta, 400)

    def test_exact_one_to_one_holds(self):
        action = self.action([
            leg("DOGEUSDT", "SHORT", 1000, -105),
            leg("DOGEUSDT", "LONG", 1000, 2),
        ])
        self.assertEqual(action.required_delta, 0)
        self.assertEqual(action.operation, "HOLD")
        self.assertEqual(action.status, "HEDGED")

    def test_over_hedged_hype_requires_reduce(self):
        action = self.action([
            leg("HYPEUSDT", "SHORT", 2.4, -26.53),
            leg("HYPEUSDT", "LONG", 3.0, 25.8),
        ])
        self.assertEqual(action.operation, "REDUCE")
        self.assertAlmostEqual(action.delta_qty, -0.6, places=12)
        self.assertAlmostEqual(action.required_delta, 0.6, places=12)

    def test_over_hedged_zec_requires_exact_reduce(self):
        action = self.action([
            leg("ZECUSDT", "SHORT", 0.194, -61.94),
            leg("ZECUSDT", "LONG", 0.200, 60.2),
        ])
        self.assertEqual(action.operation, "REDUCE")
        self.assertAlmostEqual(action.required_delta, 0.006, places=12)

    def test_pending_open_prevents_duplicate(self):
        order = {
            "symbol": "DOGEUSDT", "positionSide": "LONG", "side": "BUY",
            "status": "NEW", "origQty": "400", "executedQty": "0",
        }
        action = self.action([
            leg("DOGEUSDT", "SHORT", 1000, -105),
            leg("DOGEUSDT", "LONG", 600, 2),
        ], orders=[order])
        self.assertEqual(action.required_delta, 0)
        self.assertEqual(action.status, "PENDING")

    def test_pending_close_counts_toward_exact_target(self):
        order = {
            "symbol": "HYPEUSDT", "positionSide": "LONG", "side": "SELL",
            "status": "NEW", "origQty": "0.6", "executedQty": "0",
        }
        action = self.action([
            leg("HYPEUSDT", "SHORT", 2.4, -26),
            leg("HYPEUSDT", "LONG", 3.0, 20),
        ], orders=[order])
        self.assertEqual(action.required_delta, 0)
        self.assertEqual(action.status, "PENDING")

    def test_existing_protected_cycle_stays_protected_after_pnl_recovery(self):
        action = self.action([
            leg("DOGEUSDT", "SHORT", 921, 12),
            leg("DOGEUSDT", "LONG", 700, -8),
        ], protected={"DOGEUSDT": "SHORT"})
        self.assertIsNotNone(action)
        self.assertEqual(action.protected_side, "SHORT")
        self.assertEqual(action.required_delta, 221)

    def test_protected_dca_growth_adds_only_new_difference(self):
        action = self.action([
            leg("DOGEUSDT", "SHORT", 1100, -4),
            leg("DOGEUSDT", "LONG", 921, 2),
        ], protected={"DOGEUSDT": "SHORT"})
        self.assertEqual(action.operation, "OPEN")
        self.assertEqual(action.required_delta, 179)

    def test_partial_protected_close_reduces_hedge_to_new_exact_target(self):
        action = self.action([
            leg("DOGEUSDT", "SHORT", 700, 5),
            leg("DOGEUSDT", "LONG", 1100, -3),
        ], protected={"DOGEUSDT": "SHORT"})
        self.assertEqual(action.operation, "REDUCE")
        self.assertEqual(action.required_delta, 400)

    def test_recovery_symbol_can_be_skipped_even_when_below_threshold(self):
        self.assertIsNone(self.action(
            [leg("SOLUSDT", "LONG", 1.14, -25)],
            skip={"SOLUSDT"},
        ))

    def test_worst_leg_wins_if_both_are_below_threshold(self):
        action = self.action([
            leg("TESTUSDT", "LONG", 10, -12),
            leg("TESTUSDT", "SHORT", 8, -30),
        ])
        self.assertEqual(action.protected_side, "SHORT")

    def test_invalid_threshold_fails_closed(self):
        with self.assertRaises(ValueError):
            evaluate_auto_hedge([leg("DOGEUSDT", "LONG", 100, -20)], 0)

    def test_shadow_mode_never_submits_open_or_reduce(self):
        class Client:
            def __init__(self):
                self.submits = 0
            def position_risk(self):
                return [
                    leg("HYPEUSDT", "SHORT", 2.4, -20),
                    leg("HYPEUSDT", "LONG", 3.0, 10),
                ]
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
        self.assertEqual(report["actions"][0]["operation"], "REDUCE")

    def test_insufficient_margin_blocks_open_before_submit(self):
        class Client:
            def __init__(self):
                self.submits = 0
            def position_risk(self):
                return [leg("DOGEUSDT", "SHORT", 100, -20, mark=1)]
            def open_orders(self):
                return []
            def position_mode(self):
                return True
            def account_information(self):
                return {"availableBalance": "0"}
            def public_exchange_info(self):
                return {"symbols": [rule("DOGEUSDT", "1")]}
            def submit_order_once(self, *args, **kwargs):
                self.submits += 1
                raise AssertionError("insufficient margin must block before submission")

        client = Client()
        report = reconcile_auto_hedge(client=client, uid="u1", threshold_usd=10, execute=True)
        self.assertEqual(client.submits, 0)
        self.assertEqual(report["actions"][0]["status"], "INSUFFICIENT_MARGIN")

    def test_precision_block_prevents_non_exact_reduce(self):
        class Client:
            def position_risk(self):
                return [
                    leg("ZECUSDT", "SHORT", 0.194, -20, mark=100),
                    leg("ZECUSDT", "LONG", 0.200, 10, mark=100),
                ]
            def open_orders(self):
                return []
            def position_mode(self):
                return True
            def public_exchange_info(self):
                return {"symbols": [rule("ZECUSDT", "0.01")]}
            def submit_order_once(self, *args, **kwargs):
                raise AssertionError("precision block must happen before submit")

        report = reconcile_auto_hedge(client=Client(), uid="u1", threshold_usd=10, execute=True)
        self.assertEqual(report["ordersSent"], 0)
        self.assertEqual(report["actions"][0]["status"], "PRECISION_BLOCKED")

    def test_reduce_uses_close_action(self):
        class Client:
            def __init__(self):
                self.intents = []
            def position_risk(self):
                return [
                    leg("HYPEUSDT", "SHORT", 2, -20, mark=10),
                    leg("HYPEUSDT", "LONG", 3, 10, mark=10),
                ]
            def open_orders(self):
                return []
            def position_mode(self):
                return True
            def public_exchange_info(self):
                return {"symbols": [rule("HYPEUSDT", "1")]}
            def query_order(self, symbol, client_order_id):
                raise RuntimeError("not found")
            def submit_order_once(self, intent, **kwargs):
                self.intents.append(intent)
                return {"orderId": "1", "status": "FILLED", "executedQty": "1", "clientOrderId": intent.intent_id}, False

        client = Client()
        report = reconcile_auto_hedge(
            client=client, uid="u1", threshold_usd=10, execute=True,
            protected_sides={"HYPEUSDT": "SHORT"},
            intent_context={"HYPEUSDT": {"generationId": "g1", "revision": 0}},
        )
        self.assertEqual(client.intents[0].action, "CLOSE")
        self.assertEqual(client.intents[0].position_side.value, "LONG")
        self.assertEqual(report["ordersSent"], 1)

    def test_same_generation_retry_recovers_but_new_generation_gets_new_id(self):
        class Client:
            def __init__(self):
                self.intents = []
                self.orders = {}
            def position_risk(self):
                return [leg("DOGEUSDT", "SHORT", 100, -20, mark=1)]
            def open_orders(self):
                return []
            def position_mode(self):
                return True
            def account_information(self):
                return {"availableBalance": "1000"}
            def public_exchange_info(self):
                return {"symbols": [rule("DOGEUSDT", "1")]}
            def query_order(self, symbol, client_order_id):
                if client_order_id not in self.orders:
                    raise RuntimeError("not found")
                return self.orders[client_order_id]
            def submit_order_once(self, intent, **kwargs):
                self.intents.append(intent)
                row = {
                    "orderId": str(len(self.intents)), "status": "FILLED",
                    "executedQty": "100", "clientOrderId": intent.intent_id,
                }
                self.orders[intent.intent_id] = row
                return row, False

        client = Client()
        kwargs = dict(
            client=client, uid="u1", threshold_usd=10, execute=True,
            protected_sides={"DOGEUSDT": "SHORT"},
        )
        first = reconcile_auto_hedge(
            **kwargs,
            intent_context={"DOGEUSDT": {"generationId": "g1", "revision": 0}},
        )
        first_id = first["actions"][0]["clientOrderId"]
        self.assertEqual(first["ordersSent"], 1)

        retry = reconcile_auto_hedge(
            **kwargs,
            intent_context={"DOGEUSDT": {"generationId": "g1", "revision": 0}},
        )
        self.assertEqual(retry["ordersSent"], 0)
        self.assertEqual(retry["actions"][0]["clientOrderId"], first_id)
        self.assertEqual(len(client.intents), 1)

        second_generation = reconcile_auto_hedge(
            **kwargs,
            intent_context={"DOGEUSDT": {"generationId": "g2", "revision": 0}},
        )
        second_id = second_generation["actions"][0]["clientOrderId"]
        self.assertNotEqual(second_id, first_id)
        self.assertEqual(second_generation["ordersSent"], 1)
        self.assertEqual(len(client.intents), 2)


if __name__ == "__main__":
    unittest.main()
