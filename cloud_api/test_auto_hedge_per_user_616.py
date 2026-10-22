"""Build 616 — Auto Hedge for every user: Hedge Mode guard + per-user SHORT Recovery execution.

Real: aster_position_loss_auto_hedge_extension, the engine, the ladder, the account lease.
Mocked: Firestore (in-memory model), Aster (ledger). No network, no credentials, no real orders.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException, Response

from test_rehedge_all_1_0 import HAVE, Base, HedgeClient, recovery_pair
from test_short_recovery_2_0_worker import PLAN, hedged_pair


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


@unittest.skipUnless(HAVE, "needs fastapi + aster_gateway deps")
class PerUserRecoveryExecution(Base):
    def setUp(self):
        super().setUp()
        self.ext.SHORT_RECOVERY_EXECUTION_ENABLED = True                      # global master switch ON

    def ladder(self, user_flag):
        doc = {"enabled": True, "thresholdUsd": 0.25, "shortRecoveryPlan": dict(PLAN)}
        if user_flag is not None:
            doc["shortRecoveryExecutionEnabled"] = user_flag
        self.put("asterPositionLossAutoHedge", self.uid, doc)
        self.L.add("SOLUSDT", "LONG", 10.0, mark=100.0, entry=101.0)
        self.L.pos[("SOLUSDT", "SHORT")] = 10.0
        self.L.entry[("SOLUSDT", "SHORT")] = 100.0
        self.put("asterPositionLossAutoHedge", self.uid, "pairs", "SOLUSDT", hedged_pair("SOLUSDT"))
        for mark in (100, 98, 98):
            self.L.mark["SOLUSDT"] = float(mark)
            self.worker_tick()

    def closes(self):
        return [o for o in self.L.hedge_orders if o["action"] == "CLOSE"]

    def test_other_users_stay_in_test_mode_even_with_global_switch_on(self):
        for flag in (None, False):
            with self.subTest(flag=flag):
                self.setUp()
                self.ladder(flag)
                self.assertEqual(self.closes(), [])
                self.assertEqual(self.short("SOLUSDT"), 10.0)
                self.assertTrue(self.pair("SOLUSDT").get("shortRecoveryShadow"))
                self.assertFalse(self.pair("SOLUSDT").get("shortRecovery"))
                self.assertIs(self.ext._public(self.uid)["shortRecoveryExecutionEnabled"], False)

    def test_flagged_user_gets_real_steps(self):
        self.ladder(True)
        self.assertEqual([(o["action"], o["qty"]) for o in self.closes()], [("CLOSE", 2.5)])
        self.assertIs(self.ext._public(self.uid)["shortRecoveryExecutionEnabled"], True)

    def test_global_switch_off_overrides_the_user_flag(self):
        self.ext.SHORT_RECOVERY_EXECUTION_ENABLED = False
        self.ladder(True)
        self.assertEqual(self.closes(), [])

    def test_user_routes_cannot_set_the_execution_flag(self):
        self.put("asterPositionLossAutoHedge", self.uid, {"enabled": True, "thresholdUsd": 10.0})
        self.ext.put_position_loss_auto_hedge(
            self.ext.AutoHedgeSettingsRequest(enabled=True, thresholdUsd=5.0), Response(), {"uid": self.uid})
        self.ext.put_position_loss_auto_hedge_short_recovery(
            self.ext.ShortRecoverySettingsRequest(enabled=True, steps=3, totalPct="6"), Response(), {"uid": self.uid})
        self.assertNotIn("shortRecoveryExecutionEnabled", self.get("asterPositionLossAutoHedge", self.uid))


@unittest.skipUnless(HAVE, "needs fastapi + aster_gateway deps")
class AdminExecutionRoute(Base):
    def setUp(self):
        super().setUp()
        admin_uid = "admin"
        def require_admin(user):
            if user["uid"] != admin_uid:
                raise HTTPException(403, "Alleen geautoriseerd TradeMentor-beheer heeft toegang")
        def get_user_by_email(email, app=None):
            if email != "klant@example.com":
                raise ValueError("not found")
            return SimpleNamespace(uid=self.uid)
        self.ext.main.require_admin = require_admin
        self.ext.main.auth = SimpleNamespace(get_user_by_email=get_user_by_email)
        self.ext.main.auth_app = None
        self.admin = {"uid": admin_uid}

    def call(self, user, **body):
        body = {"email": "klant@example.com", "enabled": True, "confirm": True, **body}
        return self.ext.put_admin_short_recovery_execution(
            self.ext.ShortRecoveryExecutionRequest(**body), Response(), user)

    def test_admin_sets_flag_for_one_user_without_orders(self):
        self.ext.SHORT_RECOVERY_EXECUTION_ENABLED = False
        out = self.call(self.admin)
        self.assertEqual((out["uid"], out["userFlag"], out["realOrders"]), (self.uid, True, False))
        self.assertIs(self.get("asterPositionLossAutoHedge", self.uid)["shortRecoveryExecutionEnabled"], True)
        self.assertEqual(self.L.hedge_orders, [])
        out = self.call(self.admin, enabled=False)
        self.assertIs(self.get("asterPositionLossAutoHedge", self.uid)["shortRecoveryExecutionEnabled"], False)

    def test_non_admin_unknown_email_and_missing_confirm_are_refused(self):
        for user, body, code in (({"uid": self.uid}, {}, 403),
                                 (self.admin, {"email": "onbekend@example.com"}, 404),
                                 (self.admin, {"confirm": False}, 422)):
            with self.subTest(code=code):
                with self.assertRaises(HTTPException) as caught:
                    self.call(user, **body)
                self.assertEqual(caught.exception.status_code, code)
        self.assertNotIn("shortRecoveryExecutionEnabled", self.get("asterPositionLossAutoHedge", self.uid))


if __name__ == "__main__":
    unittest.main()
