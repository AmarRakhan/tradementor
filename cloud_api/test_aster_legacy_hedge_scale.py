from __future__ import annotations

import unittest
from decimal import Decimal

from aster_gateway import ContractRules
from aster_legacy_hedge_scale import (
    break_even_distance,
    break_even_distance_change,
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

    def test_long_relative_distance_9_1_to_6_is_34_percent_closer(self):
        change = break_even_distance_change(9.1, 6.0)
        self.assertEqual(change["kind"], "CLOSER")
        self.assertAlmostEqual(change["relativePct"], 34.065934, places=5)
        self.assertEqual(round(change["relativePct"]), 34)

    def test_short_relative_distance_44_1_to_30_5_is_31_percent_closer(self):
        change = break_even_distance_change(44.1, 30.5)
        self.assertEqual(change["kind"], "CLOSER")
        self.assertAlmostEqual(change["relativePct"], 30.839002, places=5)
        self.assertEqual(round(change["relativePct"]), 31)

    def test_farther_away_never_reports_closer(self):
        change = break_even_distance_change(5.0, 6.0)
        self.assertEqual(change["kind"], "FARTHER")
        self.assertAlmostEqual(change["relativePct"], 20.0)

    def test_already_break_even_has_no_relative_percentage_or_division_by_zero(self):
        change = break_even_distance_change(0.0, 0.0, old_reached=True)
        self.assertEqual(change, {"kind": "ALREADY_REACHED", "relativePct": None})

    def test_full_recovery_is_exactly_100_percent_closer(self):
        change = break_even_distance_change(10.0, 0.0)
        self.assertEqual(change["kind"], "CLOSER")
        self.assertEqual(change["relativePct"], 100.0)

    def test_break_even_distance_uses_current_price_and_direction_per_side(self):
        long = break_even_distance("LONG", 100, 109.1)
        short = break_even_distance("SHORT", 100, 55.9)
        self.assertAlmostEqual(long["distancePct"], 9.1, places=8)
        self.assertEqual(long["direction"], "UP")
        self.assertAlmostEqual(short["distancePct"], 44.1, places=8)
        self.assertEqual(short["direction"], "DOWN")
        self.assertEqual(break_even_distance("LONG", 110, 109.1)["direction"], "REACHED")
        self.assertEqual(break_even_distance("SHORT", 55, 55.9)["direction"], "REACHED")

    def test_plan_publishes_break_even_before_after_and_relative_change(self):
        plan = self.base(current_price=0.004421)
        for side in ("long", "short"):
            leg = plan[side]
            self.assertGreaterEqual(leg["breakEvenDistanceBeforePct"], 0)
            self.assertGreaterEqual(leg["breakEvenDistanceAfterPct"], 0)
            self.assertIn(leg["breakEvenDirectionBefore"], {"UP", "DOWN", "REACHED"})
            self.assertIn(leg["breakEvenDirectionAfter"], {"UP", "DOWN", "REACHED"})
            self.assertIn(leg["distanceChangeKind"], {"CLOSER", "FARTHER", "UNCHANGED", "ALREADY_REACHED"})
        self.assertEqual(plan["long"]["currentPrice"], plan["short"]["currentPrice"])

    def test_remaining_openable_notional_caps_the_two_leg_quantity(self):
        plan = self.base(remaining_openable_notional_usd=50)
        self.assertTrue(plan["capacityLimited"])
        self.assertLessEqual(plan["plannedOpenNotionalUsd"], 50.0 + 1e-9)
        self.assertEqual(plan["long"]["addedQuantity"], plan["short"]["addedQuantity"])
        self.assertLess(plan["estimatedLongMarginUsd"], 2.0)
        self.assertLess(plan["estimatedShortMarginUsd"], 2.0)

    def test_zero_remaining_openable_notional_blocks_before_execution(self):
        with self.assertRaisesRegex(ValueError, "geen extra opening-notional"):
            self.base(remaining_openable_notional_usd=0)

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
