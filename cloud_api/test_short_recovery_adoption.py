import unittest
from decimal import Decimal as D
from dataclasses import replace
from short_recovery_adoption import ExistingHedge,adoption_preview

class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.h=ExistingHedge("u","XRPUSDT","z1","c1",D(10),D(10),D(10),D(10),D(2),ownership_verified=True)
    def preview(self,h=None,**kwargs):
        return adoption_preview(h or self.h,user_enabled=True,steps=4,step_pct=5,**kwargs)
    def test_existing_hedge_can_join(self):
        p=self.preview();self.assertEqual(p["status"],"ELIGIBLE_PREVIEW_ONLY")
        self.assertEqual(p["next_trigger"],D("1.9"))
        self.assertEqual(p["completed_steps"],0)
    def test_explicit_optin(self):
        self.assertEqual(adoption_preview(self.h,user_enabled=False,steps=4,step_pct=5)["status"],"OFF")
    def test_no_ownership(self):
        self.assertEqual(self.preview(replace(self.h,ownership_verified=False))["status"],"BLOCKED_OWNERSHIP")
    def test_pending(self):
        self.assertEqual(self.preview(replace(self.h,pending_orders=True))["status"],"BLOCKED_PENDING")
    def test_overhedge(self):
        self.assertEqual(self.preview(replace(self.h,short_qty=D(12),exchange_short_qty=D(12)))["status"],"BLOCKED_NOT_EXACT_1_TO_1")
    def test_exchange_disagreement(self):
        self.assertEqual(self.preview(replace(self.h,exchange_short_qty=D(9)))["status"],"BLOCKED_EXCHANGE_MISMATCH")
    def test_no_identifier(self):
        self.assertEqual(self.preview(replace(self.h,long_position_id=""))["status"],"BLOCKED_IDENTITY")
    def test_twenty_steps(self):
        p=adoption_preview(self.h,user_enabled=True,steps=20,step_pct=2)
        self.assertEqual(p["next_trigger"],D("1.96"))
    def test_invalid_settings(self):
        self.assertEqual(adoption_preview(self.h,user_enabled=True,steps=20,step_pct=5)["status"],"BLOCKED_SETTINGS")
    def test_no_short(self):
        self.assertEqual(self.preview(replace(self.h,short_qty=D(0)))["status"],"BLOCKED_QUANTITY_OR_PRICE")
