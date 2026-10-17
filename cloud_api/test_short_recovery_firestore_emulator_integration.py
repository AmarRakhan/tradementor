"""Opt-in official Firestore emulator integration; never accesses production."""
import os
import unittest
import uuid
from decimal import Decimal as D
from short_recovery_firestore_mock import encode, decode
from short_recovery_ledger import Ledger, Allocation
from short_recovery_order_claim_shadow import reserve
from short_recovery_order_resolution_shadow import resolve

@unittest.skipUnless(os.getenv('FIRESTORE_EMULATOR_HOST')=='127.0.0.1:18783' and os.getenv('GOOGLE_CLOUD_PROJECT')=='amar-short-recovery-offline-test', 'isolated emulator not explicitly configured')
class EmulatorIntegration(unittest.TestCase):
 def setUp(self):
  from google.cloud import firestore
  self.firestore=firestore;self.client=firestore.Client(project='amar-short-recovery-offline-test')
  base=self.client.collection('offline_recovery').document(uuid.uuid4().hex)
  self.refs={k:base.collection('docs').document(k) for k in ('marker','owner','ledger','claim','control')}
  self.refs['marker'].set({'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  self.refs['owner'].set({'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'})
  self.refs['ledger'].set(encode(Ledger('u','XRPUSDT',(Allocation('z','c',D(100)),))))
  self.refs['control'].set({'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
 def claim(self,intent='intent'):
  r=self.refs
  return reserve(db=self.client,transactional=self.firestore.transactional,marker_ref=r['marker'],owner_ref=r['owner'],ledger_ref=r['ledger'],claim_ref=r['claim'],control_ref=r['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id=intent,now=1)
 def resolve(self,event,**kw):
  r=self.refs
  return resolve(db=self.client,transactional=self.firestore.transactional,claim_ref=r['claim'],ledger_ref=r['ledger'],marker_ref=r['marker'],owner_ref=r['owner'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event=event,**kw)
 def test_claim_and_duplicate_with_real_sdk(self):
  self.assertEqual(self.claim(),'RESERVED_SHADOW');self.assertEqual(self.claim(),'ALREADY_RESERVED')
  self.assertEqual(self.refs['claim'].get().to_dict()['state'],'RESERVED')
 def test_emergency_stop_blocks_real_transaction(self):
  self.refs['control'].update({'emergencyStop':True})
  self.assertEqual(self.claim(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
  self.assertFalse(self.refs['claim'].get().exists)
 def test_restart_client_unknown_reconcile(self):
  self.assertEqual(self.claim(),'RESERVED_SHADOW')
  self.client=self.firestore.Client(project='amar-short-recovery-offline-test')
  self.assertEqual(self.resolve('UNKNOWN'),'BLOCKED_UNKNOWN')
  self.refs['control'].update({'enabled':False})
  self.assertEqual(self.claim('new'),'BLOCKED_UNRESOLVED_CLAIM')
  self.assertEqual(self.resolve('LATE_ACK',evidence={'confirmed':True,'orderId':'o'}),'ACKED_RECOVERED')
 def test_confirmed_financial_settlement(self):
  self.assertEqual(self.claim(),'RESERVED_SHADOW')
  self.assertEqual(self.resolve('ACK',evidence={'confirmed':True,'orderId':'o'}),'ACKED')
  evidence={'confirmed':True,'orderId':'o','readbackVerified':True,'executionId':'ex1','quantity':'25','realizedPnl':'2','commission':'0.1','funding':'-0.05'}
  self.assertEqual(self.resolve('FILL',evidence=evidence,execution_id='ex1',quantity=25),'FILL_APPLIED')
  self.assertEqual(self.resolve('FILL',evidence=evidence,execution_id='ex1',quantity=25),'ALREADY_APPLIED')
  ledger=decode(self.refs['ledger'].get().to_dict())
  self.assertEqual(ledger.allocations[0].remaining,D(75))
  self.assertEqual(ledger.cycle_realized('c'),D('1.85'))
 def test_concurrent_claims_single_winner(self):
  import concurrent.futures
  import threading
  barrier=threading.Barrier(4)
  def work(i):
   barrier.wait()
   return self.claim('concurrent-'+str(i))
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
   futures=[executor.submit(work,i) for i in range(4)]
   results=[f.result(timeout=15) for f in futures]
  self.assertEqual(results.count('RESERVED_SHADOW'),1)
  self.assertEqual(results.count('BLOCKED_UNRESOLVED_CLAIM'),3)
