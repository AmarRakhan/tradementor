import unittest
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_standalone_offline import RECOVERY,CLASSIC
from short_recovery_standalone_quantity_settlement_offline import (
    record_confirmed_short_close_offline as record)


class Exchange:
    offline_mock_only = True
    def __init__(self, cid, qty):
        self.cid=cid;self.qty=qty;self.status='FILLED';self.calls=0
    def query_order(self,s,c):
        self.calls+=1
        return {'symbol':s,'clientOrderId':c,'orderId':'o-1',
                'status':self.status,'executedQty':str(self.qty)}
    def user_trades(self,s,**kw):
        return [{'id':11,'symbol':s,'orderId':'o-1','qty':str(self.qty),
                 'realizedPnl':'.4','commission':'.02'}]


class QuantitySettlement(unittest.TestCase):
    def setUp(self):
        self.db=MultiDocDB()
        self.refs={k:Ref(self.db,k) for k in ('selector','position','claim','coord','control')}
        self.cid=canonical_intent_id(account='u',symbol='XRPUSDT',
                                      cycle='c',side='SHORT',action='CLOSE',step=1)
        self.put('selector',{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
        self.put('position',{'account':'u','symbol':'XRPUSDT','cycle':'c',
              'offlineOnly':True,'state':'ADOPTED_OFFLINE','confirmedClosed':'0',
              'originalShortQty':'100','steps':4})
        self.put('claim',{'account':'u','symbol':'XRPUSDT','cycle':'c',
              'intentId':self.cid,'side':'SHORT','action':'CLOSE','step':1,
              'orderId':'o-1','state':'PARTIAL'})
        self.put('coord',{'recoveryFenceReservation':{'account':'u',
              'symbol':'XRPUSDT','cycle':'c','intentId':self.cid,
              'state':'RECOVERY_SUBMITTING_RECONCILE_ONLY'}})
        self.put('control',{'account':'u','enabled':True,
              'emergencyStop':False,'closeAllActive':False})
        self.client=Exchange(self.cid,25)
    def put(self,key,value):
        version,_=self.db.snapshot(key);self.db.commit(key,version,value)
    def record_once(self,**changes):
        kw=dict(db=self.db,transactional=transactional,
            selector_ref=self.refs['selector'],position_ref=self.refs['position'],
            claim_ref=self.refs['claim'],coordination_ref=self.refs['coord'],
            control_ref=self.refs['control'],client=self.client,
            account='u',symbol='XRPUSDT',cycle='c',step=1,expected_quantity=25)
        kw.update(changes);return record(**kw)
    def test_atomic_qty_not_funding_or_handoff(self):
        self.assertEqual(self.record_once(),'QUANTITY_RECORDED_UNSETTLED_NO_HANDOFF')
        pos=self.db.snapshot('position')[1]
        claim=self.db.snapshot('claim')[1]
        self.assertEqual(pos['confirmedClosed'],'25')
        self.assertTrue(pos['pending'])
        self.assertEqual(claim['offlineFundingStatus'],'UNRECONCILED')
        self.assertFalse(claim['offlineNextClaimAuthorized'])
        self.assertEqual(claim['offlineFinancialSettlement'],'PENDING')
        self.assertEqual(claim['state'],'PARTIAL')
        self.assertEqual(self.db.snapshot('coord')[1]['recoveryFenceReservation']['intentId'],self.cid)
    def test_missing_complete_fill_does_not_persist(self):
        self.client.qty=10
        self.assertEqual(self.record_once(),'BLOCKED_EXECUTION_SCOPE_OR_QUANTITY')
        self.assertEqual(self.db.snapshot('position')[1]['confirmedClosed'],'0')
    def test_classic_stop_unknown_and_stale_fence(self):
        self.put('selector',{'account':'u','activeStrategy':CLASSIC,'offlineOnly':True})
        self.assertEqual(self.record_once(),'BLOCKED_STRATEGY_NOT_ACTIVE')
        self.put('selector',{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
        self.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
        self.assertEqual(self.record_once(),'BLOCKED_STOP')
        self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
        self.client.status='PARTIALLY_FILLED'
        self.assertEqual(self.record_once(),'BLOCKED_NOT_FULLY_FILLED')
        self.client.status='FILLED'
        self.put('coord',{'recoveryFenceReservation':{'intentId':'stale'}})
        self.assertEqual(self.record_once(),'BLOCKED_COORDINATION_FENCE')
    def test_replay_no_double_count(self):
        self.assertEqual(self.record_once(),'QUANTITY_RECORDED_UNSETTLED_NO_HANDOFF')
        self.assertEqual(self.record_once(),'ALREADY_RECORDED_UNSETTLED')
        self.assertEqual(self.db.snapshot('position')[1]['confirmedClosed'],'25')
    def test_ten_step_limit(self):
        self.put('position',{**self.db.snapshot('position')[1],'steps':10})
        self.assertEqual(self.record_once(),'BLOCKED_QUANTITY_LIMIT')
        self.assertEqual(self.db.snapshot('position')[1]['confirmedClosed'],'0')
    def test_restart_no_reexecution(self):
        self.assertEqual(self.record_once(),'QUANTITY_RECORDED_UNSETTLED_NO_HANDOFF')
        self.db=self.db.restart();self.refs={k:Ref(self.db,k) for k in self.refs}
        self.assertEqual(self.record_once(),'ALREADY_RECORDED_UNSETTLED')
    def test_concurrency_does_not_double_count(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.record_once(),range(2)))
        self.assertEqual(results.count('QUANTITY_RECORDED_UNSETTLED_NO_HANDOFF'),1)
        self.assertEqual(results.count('ALREADY_RECORDED_UNSETTLED'),1)
        self.assertEqual(self.db.snapshot('position')[1]['confirmedClosed'],'25')


if __name__=='__main__':unittest.main()
