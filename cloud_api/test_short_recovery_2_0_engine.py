"""SHORT Recovery 2.0 — the existing Auto Hedge engine with an optional lower SHORT target.

Proves: no override = byte-identical legacy behaviour; an override turns a 1:1 pair into a
REDUCE through the SAME canonical submit path; an override can never make SHORT > LONG and
never opens a SHORT for a SHORT-protected pair; a reduced pair is not topped up.
"""
from __future__ import annotations

import unittest

from aster_position_loss_auto_hedge import evaluate_auto_hedge, reconcile_auto_hedge


def leg(symbol, side, qty, pnl, *, mark=10.0):
    return {"symbol": symbol, "positionSide": side, "positionAmt": str(qty),
            "unRealizedProfit": str(pnl), "entryPrice": str(mark), "markPrice": str(mark), "leverage": "20"}


def rule(symbol, step="1"):
    return {"symbol": symbol, "filters": [
        {"filterType": "PRICE_FILTER", "minPrice": "0.000001", "maxPrice": "1000000", "tickSize": "0.000001"},
        {"filterType": "LOT_SIZE", "minQty": step, "maxQty": "100000000", "stepSize": step},
        {"filterType": "MARKET_LOT_SIZE", "minQty": step, "maxQty": "100000000", "stepSize": step},
        {"filterType": "MIN_NOTIONAL", "notional": "0"},
    ]}


class Client:
    def __init__(self, rows):
        self.rows = rows
        self.intents = []

    def position_risk(self):
        return self.rows

    def open_orders(self):
        return []

    def position_mode(self):
        return True

    def account_information(self):
        return {"availableBalance": "100000"}

    def public_exchange_info(self):
        return {"symbols": [rule(r["symbol"]) for r in self.rows]}

    def query_order(self, symbol, client_order_id):
        return None

    def submit_order_once(self, intent, **kwargs):
        self.intents.append(intent)
        return {"orderId": str(len(self.intents)), "status": "FILLED",
                "executedQty": str(intent.quantity), "clientOrderId": intent.intent_id}, False


HEDGED = [leg("SOLUSDT", "LONG", 100, -40), leg("SOLUSDT", "SHORT", 100, 40)]


class Evaluate(unittest.TestCase):
    def one(self, rows, overrides=None, protected=None):
        acts = evaluate_auto_hedge(rows, 0.25, open_orders=[], protected_sides=protected or {"SOLUSDT": "LONG"},
                                   target_overrides=overrides)
        return acts[0]

    def test_no_override_is_legacy(self):
        a = self.one(HEDGED)
        self.assertEqual((a.operation, a.reason, a.target_qty), ("HOLD", "EXACT_1_TO_1", 100))

    def test_reduced_pair_without_override_is_topped_up_legacy(self):
        a = self.one([leg("SOLUSDT", "LONG", 100, -40), leg("SOLUSDT", "SHORT", 75, 30)])
        self.assertEqual((a.operation, a.required_delta), ("OPEN", 25))

    def test_override_reduces(self):
        a = self.one(HEDGED, {"SOLUSDT": 75})
        self.assertEqual((a.operation, a.reason, a.required_delta), ("REDUCE", "SHORT_RECOVERY_STEP", 25))

    def test_override_holds_reduced_pair_no_topup(self):
        a = self.one([leg("SOLUSDT", "LONG", 100, -40), leg("SOLUSDT", "SHORT", 75, 30)], {"SOLUSDT": 75})
        self.assertEqual((a.operation, a.status, a.reason), ("HOLD", "HEDGED", "SHORT_RECOVERY_TARGET"))

    def test_override_never_above_long(self):
        a = self.one(HEDGED, {"SOLUSDT": 500})
        self.assertEqual((a.operation, a.target_qty), ("HOLD", 100))

    def test_override_never_negative(self):
        a = self.one(HEDGED, {"SOLUSDT": -5})
        self.assertEqual((a.operation, a.required_delta, a.target_qty), ("REDUCE", 100, 0))

    def test_override_reopen_up_to_target(self):
        a = self.one([leg("SOLUSDT", "LONG", 100, -40)], {"SOLUSDT": 90})
        self.assertEqual((a.operation, a.required_delta, a.reason), ("OPEN", 90, "SHORT_RECOVERY_REOPEN"))

    def test_override_ignored_for_short_protected_pair(self):
        rows = [leg("SOLUSDT", "SHORT", 100, -40), leg("SOLUSDT", "LONG", 100, 40)]
        a = self.one(rows, {"SOLUSDT": 10}, protected={"SOLUSDT": "SHORT"})
        self.assertEqual((a.operation, a.target_qty), ("HOLD", 100))

    def test_override_only_for_its_symbol(self):
        rows = HEDGED + [leg("ETHUSDT", "LONG", 5, -1), leg("ETHUSDT", "SHORT", 3, 1)]
        acts = {a.symbol: a for a in evaluate_auto_hedge(
            rows, 0.25, open_orders=[], protected_sides={"SOLUSDT": "LONG", "ETHUSDT": "LONG"},
            target_overrides={"SOLUSDT": 50})}
        self.assertEqual(acts["ETHUSDT"].required_delta, 2)
        self.assertEqual(acts["ETHUSDT"].operation, "OPEN")


class Reconcile(unittest.TestCase):
    def test_step_goes_through_canonical_close_path(self):
        client = Client(list(HEDGED))
        report = reconcile_auto_hedge(
            client=client, uid="u1", threshold_usd=0.25, execute=True,
            protected_sides={"SOLUSDT": "LONG"},
            intent_context={"SOLUSDT": {"generationId": "g3", "revision": 0}},
            target_overrides={"SOLUSDT": 75},
        )
        self.assertEqual(report["ordersSent"], 1)
        intent = client.intents[0]
        self.assertEqual((intent.action, str(intent.position_side.value), float(intent.quantity)), ("CLOSE", "SHORT", 25.0))
        self.assertTrue(intent.intent_id.startswith("plah2-"))

    def test_shadow_sends_nothing(self):
        client = Client(list(HEDGED))
        report = reconcile_auto_hedge(
            client=client, uid="u1", threshold_usd=0.25, execute=False,
            protected_sides={"SOLUSDT": "LONG"}, target_overrides={"SOLUSDT": 75},
        )
        self.assertEqual((report["ordersSent"], client.intents), (0, []))

    def test_without_override_reduced_pair_is_refilled_legacy(self):
        client = Client([leg("SOLUSDT", "LONG", 100, -40), leg("SOLUSDT", "SHORT", 75, 30)])
        reconcile_auto_hedge(client=client, uid="u1", threshold_usd=0.25, execute=True,
                             protected_sides={"SOLUSDT": "LONG"})
        self.assertEqual((client.intents[0].action, float(client.intents[0].quantity)), ("OPEN", 25.0))


if __name__ == "__main__":
    unittest.main()
