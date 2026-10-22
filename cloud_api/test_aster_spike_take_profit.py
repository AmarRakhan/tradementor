"""Spike 1.1: eigen TP en trailing per kant (besluiten Amar 22-10-2026)."""
import unittest
from unittest.mock import patch

from aster_spike_take_profit import evaluate_spike_take_profit
from aster_extreme_spike_filter import spike_settings_from_mapping, validate_side_settings


def ev(side="LONG", entry=100.0, mark=100.0, tp=1.0, trailing=False, trail=0.3, peak=None):
    return evaluate_spike_take_profit(side=side, entry=entry, mark=mark, tp_pct=tp,
                                      trailing_enabled=trailing, trailing_pct=trail,
                                      previous_peak_pct=peak)


class FixedTakeProfit(unittest.TestCase):
    def test_long_closes_at_tp(self):
        self.assertFalse(ev(mark=100.9).close)
        self.assertTrue(ev(mark=101.0).close)

    def test_short_is_price_move_down(self):
        # Amars voorbeeld: SHORT met TP 2% sluit 2% onder de instapprijs.
        self.assertFalse(ev(side="SHORT", mark=98.5, tp=2.0).close)
        self.assertTrue(ev(side="SHORT", mark=98.0, tp=2.0).close)
        self.assertFalse(ev(side="SHORT", mark=101.0, tp=2.0).close)

    def test_minimum_tp_point_one(self):
        self.assertTrue(ev(mark=100.1, tp=0.1).close)


class Trailing(unittest.TestCase):
    def run_path(self, marks, side="LONG", tp=1.0, trail=0.3):
        peak = None
        for mark in marks:
            out = ev(side=side, mark=mark, tp=tp, trailing=True, trail=trail, peak=peak)
            if out.close:
                return out
            peak = out.peak_pct
        return None

    def test_tp_is_activation_not_sale(self):
        self.assertFalse(ev(mark=101.0, trailing=True).close)
        self.assertTrue(ev(mark=101.0, trailing=True).trailing_active)

    def test_amar_example_drop_after_one_percent_sells_at_point_seven(self):
        out = self.run_path([100.5, 101.0, 100.8, 100.7])
        self.assertIsNotNone(out)
        self.assertAlmostEqual(out.profit_pct, 0.7, places=6)

    def test_peak_moves_up_and_small_dips_do_nothing(self):
        out = self.run_path([101.0, 101.5, 101.3, 102.0, 103.0, 102.8, 102.7])
        self.assertIsNotNone(out)
        self.assertAlmostEqual(out.peak_pct, 3.0, places=6)
        self.assertAlmostEqual(out.profit_pct, 2.7, places=6)

    def test_no_activation_below_tp(self):
        self.assertIsNone(self.run_path([100.5, 100.9, 100.2, 99.0]))

    def test_short_trailing(self):
        out = self.run_path([99.0, 98.0, 98.25, 98.3], side="SHORT")
        self.assertIsNotNone(out)
        self.assertAlmostEqual(out.peak_pct, 2.0, places=6)

    def test_trailing_exit_is_always_profitable(self):
        for tp, trail in ((0.5, 0.4), (1.0, 0.3), (0.2, 0.1)):
            out = self.run_path([100 + tp, 100 + tp - trail], tp=tp, trail=trail)
            self.assertGreater(out.profit_pct, 0)

    def test_trailing_not_smaller_than_tp_rejected(self):
        with self.assertRaises(ValueError):
            ev(mark=101, trailing=True, tp=0.5, trail=0.6)


class SideSettings(unittest.TestCase):
    def test_defaults(self):
        s = spike_settings_from_mapping({})
        self.assertEqual((s["level"], s["longTimeframe"], s["shortTimeframe"]), ("5", "15m", "15m"))
        self.assertTrue(s["longEnabled"])
        self.assertFalse(s["shortEnabled"])
        self.assertEqual((s["longTakeProfitPct"], s["shortTakeProfitPct"]), (1.0, 1.0))
        self.assertFalse(s["longTrailingEnabled"] or s["shortTrailingEnabled"])

    def test_each_side_has_own_tp_and_trailing(self):
        s = spike_settings_from_mapping({"extremeSpikeLongTakeProfitPct": 0.5, "extremeSpikeShortTakeProfitPct": 2,
                                         "extremeSpikeShortTrailingEnabled": True, "extremeSpikeShortTrailingPct": 0.4})
        self.assertEqual((s["longTakeProfitPct"], s["shortTakeProfitPct"]), (0.5, 2.0))
        self.assertFalse(s["longTrailingEnabled"])
        self.assertTrue(s["shortTrailingEnabled"])
        validate_side_settings(s)

    def test_validation(self):
        for bad in ({"extremeSpikeLongTakeProfitPct": 0.05},
                    {"extremeSpikeShortTrailingEnabled": True, "extremeSpikeShortTakeProfitPct": 0.5,
                     "extremeSpikeShortTrailingPct": 0.5}):
            with self.assertRaises(ValueError):
                validate_side_settings(spike_settings_from_mapping(bad))


if __name__ == "__main__":
    unittest.main()


class ScannerSpikeTakeProfit(unittest.TestCase):
    """Echte run_multi_bb_step (dry-run): Spike-positie gebruikt eigen TP tot een hedge."""

    def run_tick(self, *, mark, state_row, hedged=False, extra=None):
        from types import SimpleNamespace
        from aster_multi_bb_core import MultiBbConfig, run_multi_bb_step

        class Ref:
            def set(self, *a, **k): raise AssertionError("dry-run must never write")
            def collection(self, *a, **k): raise AssertionError("dry-run must never write")

        class Client:
            def public_exchange_info(self): return {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT"}]}
            def ticker_prices(self): return [{"symbol": "BTCUSDT", "price": str(mark)}]
            def ticker_24h(self): return [{"symbol": "BTCUSDT", "quoteVolume": "1000000"}]
            def leverage_brackets(self, symbol): return []
            def klines(self, **k): return []

        raw = {"universeTopN": 1, "maximumPositions": 1, "longSlots": 1, "shortSlots": 0,
               "minimumLeverage": 20, "maximumLeverage": 20, "takeProfit": 0.2, "takeProfitEnabled": True,
               "entryFilterMode": "EXTREME_SPIKE", "extremeSpikeSettingsVersion": 2,
               "extremeSpikeLongTakeProfitPct": 1.0}
        raw.update(extra or {})
        settings = MultiBbConfig.from_mapping(raw)
        position = {"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "1", "entryPrice": "100",
                    "markPrice": str(mark), "leverage": "20"}
        with patch("aster_multi_bb_core.auto_hedge_symbol_managed", return_value=hedged), \
             patch("aster_multi_bb_core.rank_top_volume", return_value=[]), \
             patch("aster_multi_bb_core.max_contract_leverage", return_value=20):
            return run_multi_bb_step(client=Client(), ref=Ref(), raw_state={"multiBbPositions": {"BTCUSDT|LONG": state_row}},
                                     settings=settings, uid="test-only",
                                     account={"availableBalance": 100, "totalMarginBalance": 100},
                                     positions=[position], open_orders=[], timestamp_ms=10_000_000,
                                     dry_run=True, order_budget=1)

    @staticmethod
    def row(**extra):
        base = {"cycleId": "c1", "dcaCount": 0, "lastBotFillPrice": 100, "lastKnownQty": 1, "lastKnownEntry": 100,
                "leverage": 20, "cycleStartedAtMs": 1, "updatedAtMs": 1, "botManaged": True,
                "spikeEntry": {"eventId": "e" * 32, "openedAtMs": 1, "timeframe": "15m", "level": "5"}}
        base.update(extra)
        return base

    def kinds(self, result):
        return [a.get("kind") for a in result["actions"]]

    def test_spike_position_closes_at_spike_tp_not_normal_tp(self):
        result = self.run_tick(mark=101.0, state_row=self.row())
        tp = [a for a in result["actions"] if a.get("kind") == "TP"]
        self.assertTrue(tp, result["actions"])
        self.assertTrue(tp[0]["spikeTakeProfit"])

    def test_below_spike_tp_waits(self):
        result = self.run_tick(mark=100.5, state_row=self.row())
        self.assertNotIn("TP", self.kinds(result))
        self.assertIn("SPIKE_TP_CHECK", self.kinds(result))

    def test_hedged_spike_position_falls_back_to_normal_tp(self):
        result = self.run_tick(mark=101.0, state_row=self.row(), hedged=True)
        self.assertIn("SPIKE_TP_HANDOVER", self.kinds(result))
        self.assertNotIn("TP", self.kinds(result))  # normale TP (20%) nog niet bereikt

    def test_once_hedged_stays_normal_even_without_lock(self):
        result = self.run_tick(mark=101.0, state_row=self.row(spikeHedgedAtMs=5), hedged=False)
        self.assertNotIn("TP", self.kinds(result))
        self.assertNotIn("SPIKE_TP_CHECK", self.kinds(result))

    def test_normal_position_unchanged(self):
        row = self.row(); row.pop("spikeEntry")
        result = self.run_tick(mark=101.0, state_row=row)
        self.assertNotIn("TP", self.kinds(result))
        self.assertNotIn("SPIKE_TP_CHECK", self.kinds(result))

    def test_trailing_activates_then_waits(self):
        result = self.run_tick(mark=101.0, state_row=self.row(),
                               extra={"extremeSpikeLongTrailingEnabled": True, "extremeSpikeLongTrailingPct": 0.3})
        self.assertNotIn("TP", self.kinds(result))
        check = [a for a in result["actions"] if a.get("kind") == "SPIKE_TP_CHECK"][0]
        self.assertTrue(check["trailingActive"])

    def test_trailing_exits_after_pullback_from_stored_peak(self):
        result = self.run_tick(mark=101.65, state_row=self.row(spikePeakPct=2.0),
                               extra={"extremeSpikeLongTrailingEnabled": True, "extremeSpikeLongTrailingPct": 0.3})
        self.assertIn("TP", self.kinds(result))
