import unittest
from decimal import Decimal
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_quantity_handoff_authorization_offline import handoff_verified_quantity_offline
from short_recovery_multidoc_mock import MultiDocDB, Ref, transactional
from short_recovery_standalone_offline import RECOVERY


class Client:
    offline_mock_only=True
    def __init__(self):self.short='75';self.orders=[];self.drift=False;self.calls=0
    def account_information(self):return {'account':'u','hedgeMode':True}
    def position_risk(self,s):
        self.calls+=1
        q='74' if self.drift and self.calls>1 else self.short
        return [{'symbol':s,'positionSide':'SHORT','positionAmt':q}]
    def open_orders(self,s):return self.orders
    def query_order(self,s,c):return {'symbol':s,'clientOrderId':c,'orderId':'order-1','status':'FILLED','executedQty':'25'}
    def user_trades(self,s,**kw):return [{'id':1,'symbol':s,'orderId':'order-1','qty':'25','realizedPnl':'1','commission':'.1'}]


class QuantityHandoffReadback(unittest.TestCase):
    def setUp(self):
        self.db=MultiDocDB()
        self.refs={n:Ref(self.db,n) for n in ('selector','position','prior','next','coord','control')}
        self.cid=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1)
        self.put('selector',{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
        self.put('position',{'account':'u','symbol':'XRPUSDT','cycle':'c','state':'ADOPTED_OFFLINE','offlineOnly':True,'pending':True,'originalShortQty':'100','confirmedClosed':'25','steps':4})
        self.put('prior',{'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':self.cid,'side':'SHORT','action':'CLOSE','step':1,'state':'PARTIAL','orderId':'order-1','offlineOrderTerminalVerified':True,'offlineTerminalQty':'25','offlineFundingStatus':'UNRECONCILED','offlineNextClaimAuthorized':False,'offlineTerminalExecutions':[['1','25','1','0.1']]})
        self.put('coord',{'recoveryFenceReservation':{'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':self.cid,'state':'RECOVERY_SUBMITTING_RECONCILE_ONLY'}})
        self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
        self.client=Client()
    def put(self,name,value):
        version,_=self.db.snapshot(name);self.db.commit(name,version,value)
    def handoff(self,**changes):
        opts=dict(mock_only=True,db=self.db,transactional=transactional,client=self.client,
          selector_ref=self.refs['selector'],position_ref=self.refs['position'],
          previous_claim_ref=self.refs['prior'],next_claim_ref=self.refs['next'],
          coordination_ref=self.refs['coord'],control_ref=self.refs['control'],
          account='u',symbol='XRPUSDT',cycle='c',next_step=2,exchange_short_quantity='75')
        opts.update(changes)
        return handoff_verified_quantity_offline(**opts)
    def test_two_stable_readbacks_and_cas(self):
        self.assertEqual(self.handoff(),'QUANTITY_HANDOFF_RESERVED_OFFLINE')
        self.assertEqual(self.db.snapshot('next')[1]['state'],'RESERVED')
        self.assertEqual(self.db.snapshot('next')[1]['financialSettlement'],'UNRECONCILED')
        self.assertGreaterEqual(self.client.calls,2)
        self.assertEqual(self.handoff(),'BLOCKED_POSITION_STATE')
    def test_stale_exchange_snapshot_rejected(self):
        self.client.short='100'
        self.assertEqual(self.handoff(),'BLOCKED_INDEPENDENT_INVENTORY_READBACK')
        self.assertIsNone(self.db.snapshot('next')[1])
    def test_drift_rejected(self):
        self.client.drift=True
        self.assertEqual(self.handoff(),'BLOCKED_INDEPENDENT_INVENTORY_READBACK')
    def test_inventory_change_during_execution_readback_blocks_handoff(self):
        original=self.client.query_order
        def change_after_order_lookup(symbol,client_id):
            self.client.short='74'
            return original(symbol,client_id)
        self.client.query_order=change_after_order_lookup
        self.assertEqual(self.handoff(),'BLOCKED_INVENTORY_CHANGED_DURING_READBACK')
        self.assertIsNone(self.db.snapshot('next')[1])

    def test_pending_open_orders_rejected(self):
        self.client.orders=[{'orderId':'open'}]
        self.assertEqual(self.handoff(),'BLOCKED_INDEPENDENT_INVENTORY_READBACK')
    def test_stop_and_stale_lease(self):
        self.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
        self.assertEqual(self.handoff(),'BLOCKED_STOP')
        self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
        self.put('coord',{**self.db.snapshot('coord')[1],'lease':{'token':'stale'}})
        self.assertEqual(self.handoff(),'BLOCKED_LEASE')
    def test_restart_and_concurrency(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.handoff(),range(2)))
        self.assertEqual(results.count('QUANTITY_HANDOFF_RESERVED_OFFLINE'),1)
        self.assertEqual(results.count('BLOCKED_POSITION_STATE'),1)
        self.db=self.db.restart();self.refs={k:Ref(self.db,k) for k in self.refs}
        self.assertEqual(self.handoff(),'BLOCKED_POSITION_STATE')

if __name__=='__main__':unittest.main()
