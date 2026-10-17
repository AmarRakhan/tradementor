"""Offline Firestore SDK contract boundary and serializable mock conflict tests."""
import unittest
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_firestore_mock import Conflict
from test_short_recovery_build47_order_claim import Tests as ClaimFixture
from short_recovery_order_claim_shadow import reserve

class Semantics(unittest.TestCase):
 def test_read_after_write_fails(self):
  db=MultiDocDB();a=Ref(db,('a',));b=Ref(db,('b',));tx=db.transaction()
  a.get(transaction=tx);tx.set(a,{'x':1})
  with self.assertRaisesRegex(ValueError,'reads before writes'):b.get(transaction=tx)
 def test_conflict_retries_with_fresh_read(self):
  db=MultiDocDB();r=Ref(db,('owner',));db.commit(r.key,0,{'v':1});attempts=[]
  @transactional
  def work(tx):
   value=r.get(transaction=tx).to_dict()['v'];attempts.append(value)
   if len(attempts)==1:db.commit(r.key,1,{'v':2})
   tx.set(r,{'v':value+1});return 'OK'
  self.assertEqual(work(db.transaction()),'OK')
  self.assertEqual(attempts,[1,2]);self.assertEqual(db.snapshot(r.key)[1],{'v':3})
 def test_control_change_during_reservation_retries_and_blocks(self):
  h=ClaimFixture('test_same_intent_idempotent');h.setUp()
  class RacingRef:
   def __init__(self,ref):self.ref=ref;self.once=True
   def get(self,transaction):
    snapshot=self.ref.get(transaction=transaction)
    if self.once:
     self.once=False;k=h.keys['control'];v,row=h.db.snapshot(k)
     h.db.commit(k,v,{**row,'emergencyStop':True})
    return snapshot
  result=reserve(db=h.db,transactional=transactional,marker_ref=h.refs['marker'],owner_ref=h.refs['owner'],ledger_ref=h.refs['ledger'],claim_ref=h.refs['claim'],control_ref=RacingRef(h.refs['control']),account='u',symbol='XRPUSDT',cycle='c',intent_id='race',now=1)
  self.assertEqual(result,'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
  self.assertIsNone(h.db.snapshot(h.keys['claim'])[1])
