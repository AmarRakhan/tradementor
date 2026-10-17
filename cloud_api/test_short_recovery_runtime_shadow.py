import unittest
from short_recovery_runtime_shadow import normalize_plan,preview_existing_pairs
class ShadowRuntimeTests(unittest.TestCase):
    def test_disabled(self):self.assertEqual(normalize_plan(None)["status"],"OFF")
    def test_invalid_steps(self):self.assertEqual(normalize_plan({"enabled":True,"steps":20,"stepPct":5})["status"],"INVALID_SETTINGS")
    def test_four_steps(self):self.assertEqual(normalize_plan({"enabled":True,"steps":4,"stepPct":3})["status"],"SHADOW_ONLY")
    def test_missing_owner(self):
        v=preview_existing_pairs(settings={"shortRecoveryPlan":{"enabled":True,"steps":4,"stepPct":3}},pair_states={"XRPUSDT":{"protectedSide":"LONG","hedgeSide":"SHORT","hedgeLeg":{"entryPrice":2}}},positions=[{"symbol":"XRPUSDT","markPrice":1.8}],open_orders=[])
        self.assertEqual(v["pairs"][0]["status"],"BLOCKED_OWNERSHIP_OR_ANCHOR")
    def test_historical_catchup(self):
        v=preview_existing_pairs(settings={"shortRecoveryPlan":{"enabled":True,"steps":4,"stepPct":3}},pair_states={"XRPUSDT":{"protectedSide":"LONG","hedgeSide":"SHORT","recoveryOwnershipVerified":True,"hedgeLeg":{"entryPrice":2}}},positions=[{"symbol":"XRPUSDT","markPrice":1.8}],open_orders=[])
        self.assertEqual(v["pairs"][0]["reachedSteps"],3)
        self.assertEqual(v["ordersSent"],0)
    def test_pending_orders_fail_closed(self):
        v=preview_existing_pairs(settings={"shortRecoveryPlan":{"enabled":True,"steps":4,"stepPct":3}},pair_states={},positions=[],open_orders=[{"symbol":"XRPUSDT"}])
        self.assertEqual(v["status"],"BLOCKED_PENDING_ORDERS")
if __name__=="__main__":unittest.main()
