"""Strict ownership/ledger transactions with injected in-memory mocks only."""
import unittest
import threading
from decimal import Decimal as D
from short_recovery_ledger import Ledger,Allocation,Fill
from short_recovery_firestore_mock import encode,decode,Conflict
from short_recovery_transaction_adapter import record_confirmed_fill_owned
from test_short_recovery_build39_transaction_adapter import DB,Ref,transactional

class OwnedTests(unittest.TestCase):
 def setUp(self):
  self.db=DB();self.lk=('u','XRPUSDT');self.ok=('u','XRPUSDT','owner')
  self.lr=Ref(self.db,self.lk);self.oref=Ref(self.db,self.ok)
  self.db.commit(self.lk,0,encode(Ledger('u','XRPUSDT',(Allocation('z','cycle1',D(100)),))))
  self.owner={'account':'u','symbol':'XRPUSDT','cycleId':'cycle1','ownerSide':'SHORT','cycleConfirmed':True,'ownershipVerified':True,'state':'PARTIAL'}
  self.db.commit(self.ok,0,self.owner)
 def call(self,execution='e1',quantity='25',cycle='cycle1'):
  fill=Fill('u','XRPUSDT',execution,'order-'+execution,D(quantity),D(0),D(0))
  return record_confirmed_fill_owned(db=self.db,transactional=transactional,ledger_ref=self.lr,ownership_ref=self.oref,fill=fill,splits=(('z',cycle,D(quantity)),),account='u',symbol='XRPUSDT',cycle_id='cycle1')
 def test_confirmed_and_restart_duplicate(self):
  self.assertEqual(self.call(),'APPLIED')
  self.db._docs=self.db.restart()._docs
  self.assertEqual(self.call(),'ALREADY_APPLIED')
  self.assertEqual(decode(self.db.snapshot(self.lk)[1]).allocations[0].remaining,D(75))
 def test_owner_revoked_fails_closed(self):
  version,row=self.db.snapshot(self.ok);row['ownershipVerified']=False;self.db.commit(self.ok,version,row)
  self.assertEqual(self.call(),'BLOCKED_OWNERSHIP')
  self.assertEqual(decode(self.db.snapshot(self.lk)[1]).allocations[0].remaining,D(100))
 def test_wrong_cycle_fails_closed(self):
  self.assertEqual(self.call(cycle='wrong'),'BLOCKED_CYCLE_MISMATCH')
  self.assertEqual(decode(self.db.snapshot(self.lk)[1]).allocations[0].remaining,D(100))
 def test_concurrent_duplicate(self):
  gate=threading.Barrier(4);out=[];lock=threading.Lock()
  def run():
   gate.wait();result=self.call()
   with lock:out.append(result)
  ts=[threading.Thread(target=run) for _ in range(4)]
  for t in ts:t.start()
  for t in ts:t.join(5);self.assertFalse(t.is_alive())
  self.assertCountEqual(out,['APPLIED']+['ALREADY_APPLIED']*3)
 def test_stale_write_conflict(self):
  version,original=self.db.snapshot(self.lk)
  self.assertEqual(self.call(),'APPLIED')
  with self.assertRaises(Conflict):self.db.commit(self.lk,version,original)
if __name__=='__main__':unittest.main()
