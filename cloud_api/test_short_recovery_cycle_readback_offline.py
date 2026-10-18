import unittest
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_cycle_readback_offline import advance_verified
class CycleExchangeBridge(unittest.TestCase):
 def test_unproven_open_anchor_and_partial_claims_block_new_cycle(self):
  db=MultiDocDB();root=('u','XRPUSDT');ck=root+('cycle','c');nk=root+('cycle','c2')
  db.commit(ck,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','anchor':'2','initialQty':'100','confirmedSteps':0,'state':'ACTIVE'})
  keys=[root+('claim',i) for i in range(1,6)]
  for i,k in enumerate(keys,1):db.commit(k,0,{'account':'u','symbol':'XRPUSDT','cycle':'c','side':'SHORT','action':'OPEN' if i==5 else 'CLOSE','step':i,'state':'CLOSED','intentId':f'canonical-{i}','orderId':f'order-{i}','executedQty':'100' if i==5 else '25'})
  class Exchange:
   offline_mock_only=True
   partial=False
   def account_information(self):return {'account':'u','hedgeMode':True}
   def position_risk(self,s):return [{'symbol':s,'positionSide':'LONG','positionAmt':'100'},{'symbol':s,'positionSide':'SHORT','positionAmt':'100'}]
   def open_orders(self,s):return []
   def query_order(self,s,c):
    i=int(c.rsplit('-',1)[1]);return {'symbol':s,'clientOrderId':c,'orderId':f'order-{i}','status':'PARTIALLY_FILLED' if self.partial else 'FILLED','executedQty':'100' if i==5 else '25'}
   def user_trades(self,s,**kw):return [{'symbol':s,'orderId':f'order-{i}','id':i,'qty':'100' if i==5 else '25','realizedPnl':'0','commission':'0'} for i in range(1,6)]
  ex=Exchange()
  def call(event,step=0):return advance_verified(db=db,transactional=transactional,cycle_ref=Ref(db,ck),claim_refs=[Ref(db,k) for k in keys],next_ref=Ref(db,nk),client=ex,next_cycle='c2',event=event,step=step)
  ex.partial=True;self.assertEqual(call('CONFIRM_REDUCTION',1),'BLOCKED_UNVERIFIED_EXECUTIONS')
  ex.partial=False
  original=ex.query_order
  ex.query_order=lambda symbol,cid:{k:v for k,v in original(symbol,cid).items() if k!='executedQty'}
  self.assertEqual(call('CONFIRM_REDUCTION',1),'BLOCKED_MISSING_EXECUTED_QTY')
  ex.query_order=original
  for i in range(1,5):
   self.assertEqual(call('CONFIRM_REDUCTION',i),'REDUCTION_CONFIRMED');db=db.restart()
  self.assertEqual(call('CONFIRM_REHEDGE'),'BLOCKED_NEW_ANCHOR_EXECUTION_PROVENANCE')
  self.assertIsNone(db.snapshot(nk)[1]);self.assertEqual(db.snapshot(ck)[1]['anchor'],'2')
  original_trades=ex.user_trades
  def priced(symbol,**kw):
   return [{**r,'price':('1.60' if r['id']!=5 else '1.62')} for r in original_trades(symbol,**kw)]
  ex.user_trades=priced
  ex.open_orders=lambda symbol:[{'orderId':'pending'}]
  self.assertEqual(call('CONFIRM_REHEDGE'),'BLOCKED_REHEDGE_INVENTORY_UNVERIFIED')
  self.assertIsNone(db.snapshot(nk)[1])
  ex.open_orders=lambda symbol:[]
  original_position=ex.position_risk
  ex.position_risk=lambda symbol:[{'symbol':symbol,'positionSide':'LONG','positionAmt':'100'},{'symbol':symbol,'positionSide':'SHORT','positionAmt':'99'}]
  self.assertEqual(call('CONFIRM_REHEDGE'),'BLOCKED_REHEDGE_INVENTORY_MISMATCH')
  self.assertIsNone(db.snapshot(nk)[1])
  ex.position_risk=original_position
  self.assertEqual(call('CONFIRM_REHEDGE'),'NEW_CYCLE_ATOMICALLY_CREATED')
  self.assertEqual(db.snapshot(nk)[1]['anchor'],'1.62')
  self.assertEqual(call('CONFIRM_REHEDGE'),'BLOCKED_REHEDGE_NOT_FINAL')
