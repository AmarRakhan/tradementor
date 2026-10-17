import unittest
from short_recovery_gate import normalize_settings,partition_reconciliation
class Tests(unittest.TestCase):
    def test_default_off(self):self.assertFalse(normalize_settings(None)["enabled"])
    def test_four_steps(self):self.assertEqual(normalize_settings({"enabled":True,"steps":4,"stepPct":3})["lastLevelPct"],"12")
    def test_twenty_steps(self):self.assertEqual(normalize_settings({"enabled":True,"steps":20,"stepPct":2})["reducePct"],"5")
    def test_invalid_final(self):
        with self.assertRaises(ValueError): normalize_settings({"enabled":True,"steps":20,"stepPct":5})
    def test_invalid_boolean(self):
        with self.assertRaises(ValueError): normalize_settings({"enabled":True,"steps":True})
    def test_invalid_nan(self):
        with self.assertRaises(ValueError): normalize_settings({"enabled":True,"stepPct":"NaN"})
    def test_off_no_change(self):
        p=partition_reconciliation(settings=None,protected_sides={},existing_skip_symbols={"X"},recovery_cycles={})
        self.assertEqual(p["legacy_skip"],p["shadow_skip"])
    def test_partial_shadow_no_topup(self):
        p=partition_reconciliation(settings={"enabled":True},protected_sides={"X":"LONG","Y":"LONG"},existing_skip_symbols=set(),
          recovery_cycles={"X":{"ownerSide":"SHORT","cycleConfirmed":True,"ownershipVerified":True,"state":"PARTIAL"}})
        self.assertIn("X",p["shadow_skip"]);self.assertNotIn("X",p["legacy_skip"]);self.assertNotIn("Y",p["shadow_skip"])
    def test_unknown_not_suppressed(self):
        p=partition_reconciliation(settings={"enabled":True},protected_sides={"X":"LONG"},existing_skip_symbols=set(),
          recovery_cycles={"X":{"ownerSide":"SHORT","cycleConfirmed":False,"ownershipVerified":True,"state":"PARTIAL"}})
        self.assertNotIn("X",p["shadow_skip"])
    def test_final_pending_shadow(self):
        p=partition_reconciliation(settings={"enabled":True},protected_sides={"X":"LONG"},existing_skip_symbols=set(),
          recovery_cycles={"X":{"ownerSide":"SHORT","cycleConfirmed":True,"ownershipVerified":True,"state":"FINAL_PENDING"}})
        self.assertIn("X",p["shadow_skip"])

class UserSelectableRecoveryLadder(__import__('unittest').TestCase):
    def test_twenty_five_percent_steps_half_percent_spacing(self):
        p=normalize_settings({'enabled':True,'steps':20,'stepPct':'0.5'})
        self.assertEqual((p['steps'],p['reducePct'],p['lastLevelPct']),(20,'5','10.0'))
    def test_four_quarter_steps_remain_available(self):
        p=normalize_settings({'enabled':True,'steps':4,'stepPct':'5'})
        self.assertEqual((p['steps'],p['reducePct'],p['lastLevelPct']),(4,'25','20'))
