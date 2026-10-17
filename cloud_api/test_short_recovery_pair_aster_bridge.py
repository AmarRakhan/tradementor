import unittest
from test_short_recovery_pair_atomic_settlement import PairAtomic
from short_recovery_order_resolution_shadow import reconcile_pair_from_aster_mock
class AsterBridge(unittest.TestCase):
 def test_two_aster_readbacks_do_not_forge_funding_proof(self):
  fixture=PairAtomic('test_complete_two_sided_atomic_settlement');fixture.setUp()
  class Mock:
   def __init__(self):self.calls=[]
   def query_order(self,symbol,cid):
    self.calls.append(('query',cid));return {'symbol':symbol,'clientOrderId':cid,'orderId':cid.replace('-intent','-order'),'status':'FILLED','executedQty':'100' if cid.startswith('LONG') else '75'}
   def user_trades(self,symbol,limit=500,from_id=None):
    self.calls.append(('fills',from_id));return [{'symbol':symbol,'orderId':'LONG-order','id':11,'qty':'100','realizedPnl':'1','commission':'.1'},{'symbol':symbol,'orderId':'SHORT-order','id':12,'qty':'75','realizedPnl':'1','commission':'.1'}]
   def submit_order(self,*args,**kwargs):raise AssertionError('live forbidden')
  client=Mock();refs=fixture.refs
  result=reconcile_pair_from_aster_mock(client=client,claim_refs={s:refs[s+'claim'] for s in ('LONG','SHORT')},ledger_refs={s:refs[s+'ledger'] for s in ('LONG','SHORT')},control_ref=refs['control'],pair_ref=refs['pair'],db=fixture.db,transactional=__import__('short_recovery_multidoc_mock').transactional,account='u',symbol='XRPUSDT',cycle='c')
  self.assertEqual(result,'BLOCKED_FUNDING_CYCLE_PROOF')
  self.assertEqual(fixture.snapshot('pair')['state'],'OPEN')
  self.assertEqual(len(client.calls),0)

class VerifiedAsterBridge(unittest.TestCase):
 def setUp(self):
  self.fixture=PairAtomic('test_complete_two_sided_atomic_settlement');self.fixture.setUp()
  class Mock:
   def query_order(self,symbol,cid):
    side=cid.split('-')[0];return {'symbol':symbol,'clientOrderId':cid,'orderId':side+'-order','status':'FILLED','executedQty':'100' if side=='LONG' else '75'}
   def user_trades(self,symbol,limit=500,from_id=None):
    return [{'symbol':symbol,'orderId':s+'-order','id':i,'qty':qty,'realizedPnl':'1','commission':'.1'} for s,i,qty in (('LONG',11,'100'),('SHORT',12,'75'))]
   def submit_order(self,*a,**kw):raise AssertionError('no orders')
  self.client=Mock()
  self.proof={s:{'cycleId':'c','orderId':s+'-order','orderStatus':'FILLED','executedQty':qty,'terminalVerified':True,'incomeHistoryComplete':True,'ownershipVerified':True,'executions':{eid:{'funding':'-.05','fundingOwnershipVerified':True,'financialVerified':True}}} for s,qty,eid in (('LONG','100','11'),('SHORT','75','12'))}
 def run_bridge(self):
  from short_recovery_order_resolution_shadow import reconcile_pair_from_aster_mock
  h=self.fixture;r=h.refs
  return reconcile_pair_from_aster_mock(client=self.client,claim_refs={s:r[s+'claim'] for s in ('LONG','SHORT')},ledger_refs={s:r[s+'ledger'] for s in ('LONG','SHORT')},control_ref=r['control'],pair_ref=r['pair'],db=h.db,transactional=__import__('short_recovery_multidoc_mock').transactional,account='u',symbol='XRPUSDT',cycle='c',financial_proof=self.proof)
 def test_complete_independent_evidence_reaches_atomic_settlement(self):
  self.assertEqual(self.run_bridge(),'PAIR_CLOSED_VERIFIED')
  self.assertEqual(self.fixture.snapshot('pair')['state'],'CLOSED')
 def test_missing_income_proof_never_mutates(self):
  self.proof['SHORT']['incomeHistoryComplete']=False
  self.assertEqual(self.run_bridge(),'BLOCKED_FUNDING_CYCLE_PROOF')
  self.assertEqual(self.fixture.snapshot('pair')['state'],'OPEN')
 def test_wrong_cycle_never_mutates(self):
  self.proof['SHORT']['cycleId']='other'
  self.assertEqual(self.run_bridge(),'BLOCKED_FUNDING_CYCLE_PROOF')
 def test_unowned_fill_blocks(self):
  self.proof['SHORT']['executions']={}
  self.assertEqual(self.run_bridge(),'BLOCKED_FUNDING_CYCLE_PROOF')
