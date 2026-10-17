import unittest, threading
from decimal import Decimal
from short_recovery_order_claim_shadow import canonical_intent_id, reserve, submit_once_offline
from test_short_recovery_build47_order_claim import Tests as Fixture
from short_recovery_multidoc_mock import transactional
from aster_gateway import AsterOrderIntent,PositionSide

class OfflineSubmit(unittest.TestCase):
 def setUp(self):
  self.f=Fixture('test_same_intent_idempotent');self.f.setUp()
  self.id=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1)
  r=self.f.refs
  self.assertEqual(reserve(db=self.f.db,transactional=transactional,marker_ref=r['marker'],owner_ref=r['owner'],ledger_ref=r['ledger'],claim_ref=r['claim'],control_ref=r['control'],account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1,intent_id=self.id,now=1),'RESERVED_SHADOW')
  self.intent=AsterOrderIntent(self.id,'XRPUSDT',PositionSide.SHORT,Decimal('25'),'CLOSE')
 def call(self,submit):
  return submit_once_offline(db=self.f.db,transactional=transactional,claim_ref=self.f.refs['claim'],control_ref=self.f.refs['control'],account='u',symbol='XRPUSDT',cycle='c',intent=self.intent,account_close_guard=lambda:None,submit_mock=submit)
 def test_exactly_one_submit_under_concurrency(self):
  calls=[];results=[];lock=threading.Lock()
  def submit(i):
   with lock:calls.append(i.intent_id)
  def worker():results.append(self.call(submit))
  ts=[threading.Thread(target=worker) for _ in range(8)]
  for t in ts:t.start()
  for t in ts:t.join()
  self.assertEqual(calls,[self.id]);self.assertEqual(results.count('SUBMITTED_RECONCILE_ONLY'),1)
 def test_timeout_and_restart_no_retry(self):
  calls=[]
  def timeout(i):calls.append(i);raise TimeoutError()
  self.assertEqual(self.call(timeout),'UNKNOWN_RECONCILE_ONLY')
  self.f.db=self.f.db.restart();self.f.bind()
  self.assertEqual(self.call(timeout),'BLOCKED_CLAIM_NOT_RESERVED');self.assertEqual(len(calls),1)
 def test_stop_before_lock_prevents_submit(self):
  self.f.db.commit(self.f.keys['control'],1,{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
  self.assertEqual(self.call(lambda i:self.fail('submit forbidden')),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
 def test_wrong_order_side_prevents_submit(self):
  self.intent=AsterOrderIntent(self.id,'XRPUSDT',PositionSide.LONG,Decimal('25'),'CLOSE')
  self.assertEqual(self.call(lambda i:self.fail('submit forbidden')),'BLOCKED_SIDE_ACTION')
