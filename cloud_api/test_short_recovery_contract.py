import unittest
from short_recovery_contract import Plan, D, decision, rollback_risk, cycle_net_pnl

class ContractTests(unittest.TestCase):
    def test_absolute_four_steps(self):
        p=Plan(D(2),D(100),D(5),4)
        self.assertEqual([p.trigger(i) for i in range(1,5)],[D("1.9"),D("1.8"),D("1.7"),D("1.6")])
    def test_twenty_steps(self):
        p=Plan(D(10),D(100),D(2),20)
        self.assertEqual(p.trigger(20),D(6))
        self.assertEqual(p.cumulative_target_closed(1),D(5))
    def test_bad_settings(self):
        with self.assertRaises(ValueError): Plan(D(10),D(100),D(5),20)
    def test_bounce_never_rehedges(self):
        p=Plan(D(2),D(100),D(5),4)
        self.assertEqual(decision(p,mark=D("2.2"),completed_steps=2,short_qty=D(50),long_qty=D(100),enabled=True),"HOLD_PARTIAL")
    def test_wait_for_final_fill(self):
        p=Plan(D(2),D(100),D(5),4)
        self.assertEqual(decision(p,mark=D("1.6"),completed_steps=4,short_qty=D(25),long_qty=D(100),enabled=True),"WAIT_FINAL_FILL")
    def test_rehedge_only_after_all_fills(self):
        p=Plan(D(2),D(100),D(5),4)
        self.assertEqual(decision(p,mark=D("1.6"),completed_steps=4,short_qty=D(0),long_qty=D(100),enabled=True),"REHEDGE_READY")
    def test_pending_order(self):
        p=Plan(D(2),D(100),D(5),4)
        self.assertEqual(decision(p,mark=D("1.7"),completed_steps=2,short_qty=D(50),long_qty=D(100),enabled=True,pending=True),"WAIT_PENDING")
    def test_early_zero_is_blocked(self):
        p=Plan(D(2),D(100),D(5),4)
        self.assertEqual(decision(p,mark=D("1.6"),completed_steps=3,short_qty=D(0),long_qty=D(100),enabled=True),"BLOCKED_EARLY_ZERO")
    def test_old_reconciler_risk(self):
        self.assertEqual(rollback_risk(enabled=True,completed_steps=1,total_steps=4,long_qty=D(100),short_qty=D(75)),"OLD_RECONCILER_WILL_TOP_UP_PARTIAL_HEDGE")
    def test_net_pnl_and_disabled(self):
        p=Plan(D(2),D(100),D(5),4)
        self.assertEqual(cycle_net_pnl("-.5","-.1",".7",".05","-.01"),D(".04"))
        self.assertEqual(decision(p,mark=D("1.6"),completed_steps=0,short_qty=D(100),long_qty=D(100),enabled=False),"DISABLED")

if __name__=="__main__": unittest.main()
