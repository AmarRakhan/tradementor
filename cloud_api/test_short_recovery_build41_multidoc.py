"""Deterministic race between ownership revocation and fill booking, offline only."""
import unittest
import threading
from decimal import Decimal as D
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_firestore_mock import Conflict,encode,decode
from short_recovery_ledger import Ledger,Allocation,Fill
from short_recovery_transaction_adapter import record_confirmed_fill_owned
from short_recovery_gate import partition_reconciliation

class Tests(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.lk=('u','XRPUSDT','ledger');self.ok=('u','XRPUSDT','owner')
  self.lr=Ref(self.db,self.lk);self.oref=Ref(self.db,self.ok)
  self.db.commit(self.lk,0,encode(Ledger('u','XRPUSDT',(Allocation('z','c',D(100)),))))
  self.owner={'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','cycleConfirmed':True,'ownershipVerified':True,'state':'PARTIAL'}
  self.db.commit(self.ok,0,self.owner)
 def book(self,execution='e1',qty=25):
  return record_confirmed_fill_owned(db=self.db,transactional=transactional,ledger_ref=self.lr,ownership_ref=self.oref,fill=Fill('u','XRPUSDT',execution,'order-'+execution,D(qty),D(0),D(0)),splits=(('z','c',D(qty)),),account='u',symbol='XRPUSDT',cycle_id='c')
 def revoke(self):
  v,data=self.db.snapshot(self.ok);data['ownershipVerified']=False;self.db.commit(self.ok,v,data)
 def test_revocation_conflicts_with_stale_fill(self):
  txn=self.db.transaction()
  self.oref.get(transaction=txn);self.lr.get(transaction=txn)
  ledger=decode(self.db.snapshot(self.lk)[1])
  changed=ledger.apply(Fill('u','XRPUSDT','x','order-x',D(25),D(0),D(0)),(('z','c',D(25)),))
  txn.set(self.lr,encode(changed))
  self.revoke()
  with self.assertRaises(Conflict):txn.commit()
  self.assertEqual(decode(self.db.snapshot(self.lk)[1]).allocations[0].remaining,D(100))
  self.assertEqual(self.book(),'BLOCKED_OWNERSHIP')
 def test_fill_before_revoke_serializes(self):
  self.assertEqual(self.book(),'APPLIED');self.revoke()
  self.assertEqual(self.book('e2'),'BLOCKED_OWNERSHIP')
  self.assertEqual(decode(self.db.snapshot(self.lk)[1]).allocations[0].remaining,D(75))
 def test_restart_duplicate(self):
  self.assertEqual(self.book(),'APPLIED')
  restarted=self.db.restart();self.db=restarted;self.lr=Ref(restarted,self.lk);self.oref=Ref(restarted,self.ok)
  self.assertEqual(self.book(),'ALREADY_APPLIED')
 def test_workers_once(self):
  barrier=threading.Barrier(8);out=[];guard=threading.Lock()
  def worker():
   barrier.wait();value=self.book()
   with guard:out.append(value)
  threads=[threading.Thread(target=worker) for _ in range(8)]
  for t in threads:t.start()
  for t in threads:t.join(5);self.assertFalse(t.is_alive())
  self.assertCountEqual(out,['APPLIED']+['ALREADY_APPLIED']*7)
  self.assertEqual(decode(self.db.snapshot(self.lk)[1]).allocations[0].remaining,D(75))
 def test_shadow_only_prevents_legacy_topup_preview(self):
  self.book()
  r=partition_reconciliation(settings={'enabled':True,'steps':4,'stepPct':'3'},protected_sides={'XRPUSDT':'LONG'},existing_skip_symbols=set(),recovery_cycles={'XRPUSDT':{'ownerSide':'SHORT','cycleConfirmed':True,'ownershipVerified':True,'state':'PARTIAL'}})
  self.assertIn('XRPUSDT',r['shadow_skip']);self.assertNotIn('XRPUSDT',r['legacy_skip']);self.assertEqual(r['orders'],0)
if __name__=='__main__':unittest.main()
