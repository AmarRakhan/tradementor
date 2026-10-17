"""Offline transactional stop/disable contract, reusing canonical claim/resolve paths."""
import threading
import unittest
from short_recovery_order_claim_shadow import reserve
from short_recovery_order_resolution_shadow import resolve
from short_recovery_multidoc_mock import transactional
from test_short_recovery_build48_settlement import Tests as Fixture

class ClaimStop(unittest.TestCase):
    def setUp(self):
        self.h=Fixture('test_no_order_reconciled_terminal');self.h.setUp()
    def control(self, **changes):
        key=self.h.keys['control'];version,row=self.h.db.snapshot(key)
        self.h.db.commit(key,version,{**row,**changes})
    def new_claim(self, intent='next'):
        h=self.h
        return reserve(db=h.db,transactional=transactional,marker_ref=h.refs['marker'],owner_ref=h.refs['owner'],ledger_ref=h.refs['ledger'],claim_ref=h.refs['claim'],control_ref=h.refs['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id=intent,now=100)
    def test_disabled_blocks_new_claim(self):
        self.control(enabled=False)
        self.h.db.commit(self.h.keys['claim'],1,None)
        self.assertEqual(self.new_claim(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
        self.assertIsNone(self.h.db.snapshot(self.h.keys['claim'])[1])
    def test_emergency_and_closeall_block_new_claim(self):
        for changes in ({'emergencyStop':True},{'closeAllActive':True}):
            h=Fixture('test_no_order_reconciled_terminal');h.setUp();self.h=h
            self.control(**changes)
            self.h.db.commit(self.h.keys['claim'],1,None)
            self.assertEqual(self.new_claim(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
    def test_missing_control_fails_closed(self):
        self.h.db.docs.pop(self.h.keys['control'])
        self.h.db.commit(self.h.keys['claim'],1,None)
        self.assertEqual(self.new_claim(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
    def test_unknown_reconciles_after_stop_and_restart(self):
        h=self.h
        kwargs=dict(db=h.db,transactional=transactional,claim_ref=h.refs['claim'],ledger_ref=h.refs['ledger'],marker_ref=h.refs['marker'],owner_ref=h.refs['owner'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent')
        self.assertEqual(resolve(**kwargs,event='UNKNOWN'),'BLOCKED_UNKNOWN')
        self.control(enabled=False,emergencyStop=True)
        h.db=h.db.restart();h.bind();kwargs.update(db=h.db,claim_ref=h.refs['claim'],ledger_ref=h.refs['ledger'],marker_ref=h.refs['marker'],owner_ref=h.refs['owner'])
        self.assertEqual(self.new_claim('another'),'BLOCKED_UNRESOLVED_CLAIM')
        self.assertEqual(resolve(**kwargs,event='LATE_ACK',evidence={'confirmed':True,'orderId':'o'}),'ACKED_RECOVERED')
        self.assertEqual(h.db.snapshot(h.keys['claim'])[1]['state'],'ACKED')
    def test_concurrent_disabled_claims_never_reserve(self):
        self.control(enabled=False);self.h.db.commit(self.h.keys['claim'],1,None)
        barrier=threading.Barrier(6);out=[];lock=threading.Lock()
        def run(i):
            barrier.wait();r=self.new_claim(str(i))
            with lock:out.append(r)
        threads=[threading.Thread(target=run,args=(i,)) for i in range(6)]
        for t in threads:t.start()
        for t in threads:t.join(5);self.assertFalse(t.is_alive())
        self.assertEqual(out,['BLOCKED_RECOVERY_DISABLED_OR_STOPPED']*6)
