"""Build 656 (Amar 24-10): VIRTUAL stood on "FOUT" while the hedge was already (almost) 1:1.

A hedge rest that is smaller than the smallest order Aster accepts can never be topped up; it used to be
PRECISION_BLOCKED on every tick. It now counts as reached, while a sendable gap is still added as before.
"""
from __future__ import annotations

import unittest

from aster_position_loss_auto_hedge import evaluate_auto_hedge, reconcile_auto_hedge


def leg(symbol, side, qty, pnl, mark):
    return {"symbol": symbol, "positionSide": side, "positionAmt": str(qty), "unRealizedProfit": str(pnl),
            "entryPrice": str(mark), "markPrice": str(mark), "leverage": "20"}


def rule(symbol, step="1", min_notional="5"):
    return {"symbol": symbol, "filters": [
        {"filterType": "PRICE_FILTER", "minPrice": "0.0001", "maxPrice": "100000", "tickSize": "0.0001"},
        {"filterType": "LOT_SIZE", "minQty": step, "maxQty": "10000000", "stepSize": step},
        {"filterType": "MARKET_LOT_SIZE", "minQty": step, "maxQty": "10000000", "stepSize": step},
        {"filterType": "MIN_NOTIONAL", "notional": min_notional},
    ]}


class Client:
    def __init__(self, rows):
        self.rows, self.intents = rows, []

    def position_risk(self): return self.rows
    def open_orders(self): return []
    def position_mode(self): return True
    def public_exchange_info(self): return {"symbols": [rule("VIRTUALUSDT")]}
    def account_information(self): return {"availableBalance": "1000"}
    def query_order(self, symbol, cid): raise RuntimeError("not found")

    def submit_order_once(self, intent, **kwargs):
        self.intents.append(intent)
        return {"orderId": "9", "status": "FILLED", "executedQty": str(intent.quantity)}, False


class RestBelowMinimumTest(unittest.TestCase):
    def test_virtual_rest_below_min_order_value_is_hedged_not_fout(self):
        # LONG 33 protected, SHORT hedge 32: 1 VIRTUAL x $0.61 = $0.61 < $5 Aster minimum -> unsendable rest.
        client = Client([leg("VIRTUALUSDT", "LONG", 33, -2.75, 0.61), leg("VIRTUALUSDT", "SHORT", 32, 0.43, 0.61)])
        report = reconcile_auto_hedge(client=client, uid="u", threshold_usd=0.25, execute=True,
                                      protected_sides={"VIRTUALUSDT": "LONG"})
        self.assertEqual(client.intents, [])
        self.assertEqual(report["actions"][0]["status"], "HEDGED")
        self.assertEqual(report["actions"][0]["reason"], "REST_BELOW_ASTER_MINIMUM")
        self.assertEqual(report["final"][0]["status"], "HEDGED")

    def test_sendable_gap_is_still_added(self):
        # Gap 10 x $0.61 = $6.10 >= $5 -> Auto Hedge still adds it.
        client = Client([leg("VIRTUALUSDT", "LONG", 42, -2.75, 0.61), leg("VIRTUALUSDT", "SHORT", 32, 0.43, 0.61)])
        report = reconcile_auto_hedge(client=client, uid="u", threshold_usd=0.25, execute=True,
                                      protected_sides={"VIRTUALUSDT": "LONG"})
        self.assertEqual(len(client.intents), 1)
        self.assertEqual(str(client.intents[0].quantity), "10")
        self.assertEqual(report["actions"][0]["status"], "HEDGED")

    def test_first_hedge_without_existing_hedge_is_unchanged(self):
        # No hedge yet and too small to send: still reported as blocked, never shown as protected.
        client = Client([leg("VIRTUALUSDT", "LONG", 3, -1, 0.61)])
        report = reconcile_auto_hedge(client=client, uid="u", threshold_usd=0.25, execute=True)
        self.assertEqual(report["actions"][0]["status"], "PRECISION_BLOCKED")

    def test_evaluate_without_rules_behaves_as_before(self):
        rows = [leg("VIRTUALUSDT", "LONG", 33, -2.75, 0.61), leg("VIRTUALUSDT", "SHORT", 32, 0.43, 0.61)]
        action = evaluate_auto_hedge(rows, 0.25, protected_sides={"VIRTUALUSDT": "LONG"})[0]
        self.assertEqual(action.operation, "OPEN")
        self.assertEqual(action.required_delta, 1)


if __name__ == "__main__":
    unittest.main()
