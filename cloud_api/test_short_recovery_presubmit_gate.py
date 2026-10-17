import unittest
from short_recovery_order_claim_shadow import pre_submit_check
from short_recovery_multidoc_mock import transactional
from short_recovery_order_resolution_shadow import resolve
from test_short_recovery_build48_settlement import Tests as Fixture

class PreSubmit(unittest.TestCase):
    def setUp(self):
        self.h=Fixture('test_no_order_reconciled_terminal');self.h.setUp()
    def control(self,**changes):
        k=self.h.keys['control'];v,r=self.h.db.snapshot(k);self.h.db.commit(k,v,{**r,**changes})
    def check(self,guard=lambda:None):
        h=self.h
        return pre_submit_check(db=h.db,transactional=transactional,claim_ref=h.refs['claim'],control_ref=h.refs['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',account_close_guard=guard)
    def test_reservation_then_disable(self):
        self.control(enabled=False);self.assertEqual(self.check(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
    def test_reservation_then_emergency(self):
        self.control(emergencyStop=True);self.assertEqual(self.check(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
    def test_reservation_then_close_all(self):
        self.control(closeAllActive=True);self.assertEqual(self.check(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
    def test_account_guard_is_final_veto(self):
        def guard():raise RuntimeError('close lock active')
        self.assertEqual(self.check(guard),'BLOCKED_ACCOUNT_PRE_SUBMIT_GUARD')
    def test_restart_then_disable_and_unknown_reconcile(self):
        h=self.h;h.db=h.db.restart();h.bind();self.control(enabled=False)
        self.assertEqual(self.check(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
        self.assertEqual(resolve(db=h.db,transactional=transactional,claim_ref=h.refs['claim'],ledger_ref=h.refs['ledger'],marker_ref=h.refs['marker'],owner_ref=h.refs['owner'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event='UNKNOWN'),'BLOCKED_UNKNOWN')
    def test_missing_guard_fails_closed(self):
        self.assertEqual(self.check(None),'BLOCKED_GUARD_UNAVAILABLE')
