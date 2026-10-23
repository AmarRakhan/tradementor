"""Build 616 — Auto Hedge for every user: Hedge Mode guard (same version for everyone).

Real: aster_position_loss_auto_hedge_extension, the engine, the ladder, the account lease.
Mocked: Firestore (in-memory model), Aster (ledger). No network, no credentials, no real orders.
"""
from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException, Response

from test_rehedge_all_1_0 import HAVE, Base, HedgeClient


def one_way(client):
    return False


def mode_down(client):
    raise RuntimeError("aster down")


@unittest.skipUnless(HAVE, "needs fastapi + aster_gateway deps")
class HedgeModeGuard(Base):
    def setUp(self):
        super().setUp()
        self.ext._hedge_mode_ok_at.clear()

    def losing_long(self, symbol="SOLUSDT"):
        self.L.add(symbol, "LONG", 10.0, mark=100.0, entry=105.0)          # -$50 open PnL, threshold $10

    def settings_request(self, enabled=True):
        return self.ext.AutoHedgeSettingsRequest(enabled=enabled, thresholdUsd=10.0)

    def test_control_hedge_mode_hedges_the_losing_long(self):
        self.losing_long()
        self.worker_tick()
        self.assertEqual([(o["symbol"], o["positionSide"]) for o in self.L.hedge_orders], [("SOLUSDT", "SHORT")])

    def test_worker_never_orders_on_a_one_way_account(self):
        self.losing_long()
        with mock.patch.object(HedgeClient, "position_mode", one_way):
            report = self.worker_tick()
        self.assertEqual(self.L.hedge_orders, [])
        self.assertEqual((report["status"], report["reason"]), ("BLOCKED", "HEDGE_MODE_REQUIRED"))
        doc = self.get("asterPositionLossAutoHedge", self.uid)
        self.assertIn("Hedge Mode", doc["lastError"])
        self.assertEqual(self.pair("SOLUSDT"), {})                          # no lifecycle state created
        self.assertTrue(self.lease_free())

    def test_worker_fails_closed_when_mode_unreadable(self):
        self.losing_long()
        with mock.patch.object(HedgeClient, "position_mode", mode_down):
            report = self.worker_tick()
        self.assertEqual(self.L.hedge_orders, [])
        self.assertEqual(report["status"], "FAILED")
        self.assertTrue(self.lease_free())

    def test_switching_on_with_one_way_gives_clean_error_and_changes_nothing(self):
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": False, "thresholdUsd": 10.0})
        for route in (self.ext.put_position_loss_auto_hedge, self.ext.apply_position_loss_auto_hedge):
            with mock.patch.object(HedgeClient, "position_mode", one_way):
                with self.assertRaises(HTTPException) as caught:
                    route(self.settings_request(), Response(), {"uid": self.uid})
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(caught.exception.detail, self.ext.HEDGE_MODE_REQUIRED_MESSAGE)
            self.assertIs(self.get("asterPositionLossAutoHedge", self.uid)["enabled"], False)
        self.assertEqual(self.L.hedge_orders, [])

    def test_switching_on_with_unreadable_mode_is_503_and_changes_nothing(self):
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": False, "thresholdUsd": 10.0})
        with mock.patch.object(HedgeClient, "position_mode", mode_down):
            with self.assertRaises(HTTPException) as caught:
                self.ext.put_position_loss_auto_hedge(self.settings_request(), Response(), {"uid": self.uid})
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIs(self.get("asterPositionLossAutoHedge", self.uid)["enabled"], False)

    def test_switching_on_with_hedge_mode_works(self):
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": False, "thresholdUsd": 10.0})
        out = self.ext.put_position_loss_auto_hedge(self.settings_request(), Response(), {"uid": self.uid})
        self.assertIs(out["enabled"], True)

    def test_threshold_change_while_on_does_not_need_a_mode_read(self):
        with mock.patch.object(HedgeClient, "position_mode", mode_down):
            # Already ON: only the worker re-checks; a hiccup must not block a threshold change.
            self.ext.put_position_loss_auto_hedge(self.settings_request(), Response(), {"uid": self.uid})
        self.assertIs(self.get("asterPositionLossAutoHedge", self.uid)["enabled"], True)

    def test_rehedge_all_and_pair_rehedge_refuse_one_way(self):
        self.seed("ICPUSDT", 10.0)
        with mock.patch.object(HedgeClient, "position_mode", one_way):
            with self.assertRaises(HTTPException) as all_caught:
                self.press()
            with self.assertRaises(HTTPException) as pair_caught:
                self.ext.put_position_loss_auto_hedge_rehedge(
                    "ICPUSDT", self.ext.RehedgeRequest(enabled=True), Response(), {"uid": self.uid})
        self.assertEqual((all_caught.exception.status_code, pair_caught.exception.status_code), (409, 409))
        self.assertEqual(self.pair("ICPUSDT")["status"], "RECOVERY")
        self.assertEqual(self.L.hedge_orders, [])

    def test_short_recovery_switch_on_refuses_one_way(self):
        body = self.ext.ShortRecoverySettingsRequest(enabled=True, steps=3, totalPct="6")
        with mock.patch.object(HedgeClient, "position_mode", one_way):
            with self.assertRaises(HTTPException) as caught:
                self.ext.put_position_loss_auto_hedge_short_recovery(body, Response(), {"uid": self.uid})
        self.assertEqual(caught.exception.status_code, 409)
        self.assertNotIn("shortRecoveryPlan", self.get("asterPositionLossAutoHedge", self.uid))

    def test_confirmed_hedge_mode_is_cached_one_way_is_not(self):
        calls = []
        def counting(client):
            calls.append(1)
            return True
        with mock.patch.object(HedgeClient, "position_mode", counting):
            self.assertTrue(self.ext._hedge_mode_ok(self.uid))
            self.assertTrue(self.ext._hedge_mode_ok(self.uid))
        self.assertEqual(len(calls), 1)
        self.ext._hedge_mode_ok_at.clear()
        with mock.patch.object(HedgeClient, "position_mode", one_way):
            self.assertFalse(self.ext._hedge_mode_ok(self.uid))
        self.assertNotIn(self.uid, self.ext._hedge_mode_ok_at)


class RealOrdersDefault(unittest.TestCase):
    def test_short_recovery_executes_by_default_and_env_false_is_the_emergency_stop(self):
        from pathlib import Path
        src = (Path(__file__).parent / "aster_position_loss_auto_hedge_extension.py").read_text()
        self.assertIn('os.getenv("ASTER_SHORT_RECOVERY_EXECUTION_ENABLED", "true").lower() == "true"', src)


if __name__ == "__main__":
    unittest.main()
