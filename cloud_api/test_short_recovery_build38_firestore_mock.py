"""Offline Firestore document CAS and restart tests, zero order or network clients."""
import threading
import unittest
from decimal import Decimal as D
from short_recovery_ledger import Ledger,Allocation,Fill
from short_recovery_firestore_mock import MockFirestore,Conflict,encode,decode,record_fill
from short_recovery_gate import partition_reconciliation

class Tests(unittest.TestCase):
    def setUp(self):
        self.db=MockFirestore();self.key=('u','XRPUSDT')
        self.db.commit(self.key,0,encode(Ledger('u','XRPUSDT',(Allocation('z1','c1',D(100)),Allocation('z2','c2',D(50))))))
    def fill(self,execution,qty,zone='z1',cycle='c1'):
        return Fill('u','XRPUSDT',execution,'order'+execution,D(qty),D('1'),D('.1')),((zone,cycle,D(qty)),)
    def record(self,db,execution,qty,zone='z1',cycle='c1'):
        return record_fill(db,self.key,*self.fill(execution,qty,zone,cycle))
    def test_restart_durable_and_idempotent(self):
        self.assertEqual(self.record(self.db,'e1',25),'APPLIED')
        recovered=self.db.restart()
        self.assertEqual(self.record(recovered,'e1',25),'ALREADY_APPLIED')
        self.assertEqual(self.record(recovered,'e2',25),'APPLIED')
        self.assertEqual(decode(recovered.snapshot(self.key)[1]).allocations[0].remaining,D(50))
    def test_stale_version_fails_atomically(self):
        v,doc=self.db.snapshot(self.key)
        self.record(self.db,'e1',25)
        with self.assertRaises(Conflict):self.db.commit(self.key,v,doc)
        self.assertEqual(decode(self.db.snapshot(self.key)[1]).allocations[0].remaining,D(75))
    def test_competing_workers_same_fill(self):
        barrier=threading.Barrier(8);out=[];lock=threading.Lock()
        def worker():
            barrier.wait();r=self.record(self.db,'dup',20)
            with lock:out.append(r)
        ts=[threading.Thread(target=worker) for _ in range(8)]
        for t in ts:t.start()
        for t in ts:t.join(5);self.assertFalse(t.is_alive())
        self.assertCountEqual(out,['APPLIED']+['ALREADY_APPLIED']*7)
        self.assertEqual(decode(self.db.snapshot(self.key)[1]).allocations[0].remaining,D(80))
    def test_zone_isolation_and_wrong_account(self):
        with self.assertRaises(ValueError):self.record(self.db,'e1',5,'wrong','c1')
        with self.assertRaises(ValueError):record_fill(self.db,self.key,Fill('other','XRPUSDT','x','o',D(5),D(0),D(0)),(('z1','c1',D(5)),))
        self.assertEqual(decode(self.db.snapshot(self.key)[1]).allocations[0].remaining,D(100))
    def test_partial_fill_ownership_shadow_only(self):
        self.record(self.db,'e1',25)
        ledger=decode(self.db.restart().snapshot(self.key)[1])
        self.assertEqual(ledger.allocations[0].remaining,D(75))
        routing=partition_reconciliation(settings={'enabled':True,'steps':4,'stepPct':'3'},protected_sides={'XRPUSDT':'LONG'},existing_skip_symbols=set(),recovery_cycles={'XRPUSDT':{'ownerSide':'SHORT','cycleConfirmed':True,'ownershipVerified':True,'state':'PARTIAL'}})
        self.assertIn('XRPUSDT',routing['shadow_skip'])
        self.assertNotIn('XRPUSDT',routing['legacy_skip'])
        self.assertEqual(routing['orders'],0)
if __name__=='__main__':unittest.main()
