"""Actual offline _run_uid submit claim cannot mint cycle without terminal GETs."""
import unittest
from short_recovery_multidoc_mock import Ref,transactional
from short_recovery_cycle_readback_offline import advance_verified
from test_short_recovery_run_uid_integration import RunUidIntegration
from test_short_recovery_pair_aster_bridge import VerifiedAsterBridge

class RunUidCycleBoundary(unittest.TestCase):
 def test_submitting_rehedge_cannot_mint_next_cycle_after_restart(self):
  h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement');h.setUp()
  sent=[]
  def submit(intent):sent.append(intent.intent_id);return {'orderId':'mock-new-hedge'}
  result,_,h=RunUidIntegration().run_case(action_mode='REHEDGE',existing_harness=h,mock_transport=submit)
  self.assertNotIn('shortRecoverySubmit',result)
  self.assertEqual(len(sent),0)
  root=('u','XRPUSDT');ck=root+('cycle','c');nk=root+('cycle','c2');ctrl=root+('cycle-control',)
  h.fixture.db.commit(ck,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','anchor':'2','initialQty':'100','confirmedSteps':4,'state':'ACTIVE'})
  h.fixture.db.commit(ctrl,0,{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  keys=[root+('cycle-claim',i) for i in range(1,5)]+[h.fixture.refs['SHORTclaim'].key]
  for i,k in enumerate(keys[:4],1):h.fixture.db.commit(k,0,{'account':'u','symbol':'XRPUSDT','cycle':'c','side':'SHORT','action':'CLOSE','step':i,'state':'CLOSED','intentId':f'close-{i}','orderId':f'order-{i}','executedQty':'25'})
  h.fixture.db=h.fixture.db.restart();h.fixture.bind();db=h.fixture.db
  class Client:offline_mock_only=True
  answer=advance_verified(db=db,transactional=transactional,cycle_ref=Ref(db,ck),claim_refs=[Ref(db,k) for k in keys],next_ref=Ref(db,nk),control_ref=Ref(db,ctrl),client=Client(),next_cycle='c2',event='CONFIRM_REHEDGE')
  self.assertEqual(answer,'BLOCKED_UNVERIFIED_EXECUTIONS')
  self.assertIsNone(db.snapshot(nk)[1]);self.assertEqual(db.snapshot(ck)[1]['anchor'],'2')
  self.assertEqual(len(sent),0)
