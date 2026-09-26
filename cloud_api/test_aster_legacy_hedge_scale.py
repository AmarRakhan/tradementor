from __future__ import annotations

import unittest
from decimal import Decimal

from aster_gateway import ContractRules
from aster_legacy_hedge_scale import (
    entry_effect,
    excess_rollback_action,
    parity_repair_action,
    plan_legacy_hedge_scale,
    stable_scale_intent_id,
    weighted_entry,
)


def rules(step: str = "1", min_qty: str = "1", min_notional: str = "0.001") -> ContractRules:
    return ContractRules(
        symbol="1000PEPEUSDT",
        min_price=Decimal("0"),
        max_price=Decimal("0"),
        tick_size=Decimal("0.000001"),
        min_quantity=Decimal(min_qty),
        max_quantity=Decimal("1000000000"),
        quantity_step=Decimal(step),
        market_min_quantity=Decimal(min_qty),
        market_max_quantity=Decimal("1000000000"),
        market_quantity_step=Decimal(step),
        min_notional=Decimal(min_notional),
    )


class LegacyHedgeScalePlanTests(unittest.TestCase):
    def base(self, **overrides):
        values = {
            "symbol": "1000PEPEUSDT",
            "margin_per_side_usd": 2,
            "available_balance": 27,
            "current_long_qty": 18271,
            "current_short_qty": 18271,
            "long_entry": 0.004610,
            "short_entry": 0.003697,
            "long_execution_price": 0.004421,
            "short_execution_price": 0.004421,
            "long_leverage": 20,
            "short_leverage": 20,
            "rules": rules(),
            "taker_fee_rate": 0.0005,
        }
        values.update(overrides)
        return plan_legacy_hedge_scale(**values)

    def test_1000pepe_market_between_entries_improves_both(self):
        plan = self.base()
        self.assertEqual(plan["long"]["entryEffect"], "GUNSTIGER")
        self.assertEqual(plan["short"]["entryEffect"], "GUNSTIGER")
        self.assertEqual(plan["long"]["addedQuantity"], plan["short"]["addedQuantity"])
        self.assertEqual(plan["long"]["quantityAfter"], plan["short"]["quantityAfter"])
        self.assertEqual(plan["hedgeRatioAfter"], 100.0)
        self.assertLessEqual(plan["estimatedLongMarginUsd"], 2.0 + 1e-9)
        self.assertLessEqual(plan["estimatedShortMarginUsd"], 2.0 + 1e-9)

    def test_above_both_entries_only_short_improves(self):
        plan = self.base(
            long_entry=0.0040,
            short_entry=0.0035,
            long_execution_price=0.0050,
            short_execution_price=0.0050,
        )
        self.assertEqual(plan["long"]["entryEffect"], "ONGUNSTIGER")
        self.assertEqual(plan["short"]["entryEffect"], "GUNSTIGER")

    def test_below_both_entries_only_long_improves(self):
        plan = self.base(
            long_entry=0.0050,
            short_entry=0.0045,
            long_execution_price=0.0035,
            short_execution_price=0.0035,
        )
        self.assertEqual(plan["long"]["entryEffect"], "GUNSTIGER")
        self.assertEqual(plan["short"]["entryEffect"], "ONGUNSTIGER")

    def test_ena_style_profitable_long_is_not_falsely_called_improved(self):
        plan = self.base(
            current_long_qty=192,
            current_short_qty=192,
            long_entry=0.26222,
            short_entry=0.207317,
            long_execution_price=0.269906,
            short_execution_price=0.269906,
            long_leverage=20,
            short_leverage=20,
        )
        self.assertEqual(plan["long"]["entryEffect"], "ONGUNSTIGER")
        self.assertEqual(plan["short"]["entryEffect"], "GUNSTIGER")

    def test_exchange_rounding_uses_one_common_floor_quantity(self):
        plan = self.base(rules=rules(step="10", min_qty="10"))
        self.assertEqual(plan["extraQuantity"] % 10, 0)
        self.assertEqual(plan["long"]["addedQuantity"], plan["short"]["addedQuantity"])

    def test_insufficient_available_blocks_before_any_execution_layer(self):
        with self.assertRaisesRegex(ValueError, "Onvoldoende Available"):
            self.base(available_balance=0.01)

    def test_unequal_pair_is_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "niet exact 1:1"):
            self.base(current_short_qty=18270)

    def test_entry_math_and_direction_are_deterministic(self):
        value = weighted_entry(100, 10, 100, 8)
        self.assertEqual(value, 9)
        self.assertEqual(entry_effect("LONG", 10, 9), "GUNSTIGER")
        self.assertEqual(entry_effect("SHORT", 10, 9), "ONGUNSTIGER")

    def test_partial_fill_repair_targets_missing_side(self):
        repair = parity_repair_action(
            pre_long_qty=100,
            pre_short_qty=100,
            current_long_qty=120,
            current_short_qty=112,
            step=1,
        )
        self.assertEqual(repair, {"side": "SHORT", "action": "OPEN", "quantity": 8.0})
        rollback = excess_rollback_action(
            pre_long_qty=100,
            pre_short_qty=100,
            current_long_qty=120,
            current_short_qty=112,
            step=1,
        )
        self.assertEqual(rollback, {"side": "LONG", "action": "CLOSE", "quantity": 8.0})

    def test_operation_intent_is_idempotent(self):
        first = stable_scale_intent_id("owner", "BTCUSDT", "op-12345678", "LONG", "initial", 0.01)
        second = stable_scale_intent_id("owner", "BTCUSDT", "op-12345678", "LONG", "initial", 0.01)
        other = stable_scale_intent_id("owner", "BTCUSDT", "op-12345678", "SHORT", "initial", 0.01)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertLessEqual(len(first), 36)


if __name__ == "__main__":
    unittest.main()
