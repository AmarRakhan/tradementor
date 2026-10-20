import unittest
from unittest.mock import patch
from short_recovery_canonical_order_authorization import authorize_offline_order

class CanonicalOrderAuthorization(unittest.TestCase):
    def test_live_and_unknown_never_dispatch(self):
        self.assertEqual(authorize_offline_order(order_type='AUTO_HEDGE_OPEN',mock_only=False),
                         'BLOCKED_OFFLINE_SCOPE')
        self.assertEqual(authorize_offline_order(order_type='OTHER',mock_only=True),
                         'BLOCKED_ORDER_TYPE')

    def test_recovery_scope_denied(self):
        self.assertEqual(authorize_offline_order(order_type='RECOVERY_SHORT_CLOSE',
            mock_only=True,side='LONG',action='CLOSE'),'BLOCKED_INTENT_SCOPE')

    def test_all_three_types_use_existing_transactional_claims(self):
        with patch('short_recovery_canonical_order_authorization.reserve_normal_hedge_mock_only',
                   return_value='RESERVED_NORMAL_HEDGE_MOCK_ONLY') as normal, patch(
             'short_recovery_canonical_order_authorization.reserve_recovery_claim',
                   return_value='RESERVED_SHADOW') as recovery, patch(
             'short_recovery_canonical_order_authorization.reserve_verified_rehedge_mock_only',
                   return_value='RESERVED_REHEDGE_MOCK_ONLY') as rehedge:
            self.assertEqual(authorize_offline_order(order_type='AUTO_HEDGE_OPEN',
                mock_only=True),'RESERVED_NORMAL_HEDGE_MOCK_ONLY')
            self.assertEqual(authorize_offline_order(order_type='RECOVERY_SHORT_CLOSE',
                mock_only=True,side='SHORT',action='CLOSE'),'RESERVED_SHADOW')
            self.assertEqual(authorize_offline_order(order_type='REHEDGE_SHORT_OPEN',
                mock_only=True),'RESERVED_REHEDGE_MOCK_ONLY')
            normal.assert_called_once_with(mock_only=True)
            recovery.assert_called_once_with(side='SHORT',action='CLOSE')
            rehedge.assert_called_once_with(mock_only=True)

    def test_recovery_mock_submit_requires_shared_coordination(self):
        from short_recovery_canonical_order_authorization import submit_recovery_offline
        self.assertEqual(submit_recovery_offline(mock_only=False, coordination_ref=None),
                         'BLOCKED_OFFLINE_SCOPE')
        self.assertEqual(submit_recovery_offline(mock_only=True, coordination_ref=None),
                         'BLOCKED_SHARED_FENCE_REQUIRED')

    def test_recovery_submit_uses_single_strict_claim_gate(self):
        from short_recovery_canonical_order_authorization import submit_recovery_offline
        with patch('short_recovery_canonical_order_authorization.submit_once_offline',
                   return_value='BLOCKED_COORDINATION_CLAIM_MISMATCH') as submit:
            result=submit_recovery_offline(mock_only=True,coordination_ref='coord',
                                          require_shared_fence=False)
            self.assertEqual(result,'BLOCKED_COORDINATION_CLAIM_MISMATCH')
            submit.assert_called_once_with(coordination_ref='coord',
                                          require_shared_fence=True)

    def test_step_handoff_requires_terminal_claim_and_stops(self):
        from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
        from short_recovery_order_claim_shadow import canonical_intent_id
        from short_recovery_canonical_order_authorization import transfer_confirmed_recovery_step_offline as transfer
        db=MultiDocDB()
        coord=Ref(db,'coord');claim=Ref(db,'claim');following=Ref(db,'following');control=Ref(db,'control')
        id1=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',
            side='SHORT',action='CLOSE',step=1)
        id2=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',
            side='SHORT',action='CLOSE',step=2)
        db.commit('coord',0,{'recoveryFenceReservation':{
            'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':id1,
            'state':'RECOVERY_SUBMITTING_RECONCILE_ONLY'}})
        db.commit('claim',0,{'account':'u','symbol':'XRPUSDT','cycle':'c',
            'intentId':id1,'side':'SHORT','action':'CLOSE','step':1,
            'state':'SUBMITTING'})
        db.commit('control',0,{'account':'u','enabled':True,
            'emergencyStop':False,'closeAllActive':False})
        kw=dict(mock_only=True,db=db,transactional=transactional,
            coordination_ref=coord,previous_claim_ref=claim,next_claim_ref=following,control_ref=control,
            account='u',symbol='XRPUSDT',cycle='c',previous_intent_id=id1,
            next_intent_id=id2,next_step=2,verified_financial_readback=True)
        self.assertEqual(transfer(**kw),'BLOCKED_PRIOR_CLAIM_UNRESOLVED')
        ver,old=db.snapshot('claim')
        db.commit('claim',ver,{**old,'state':'CLOSED','orderId':'order-1',
            'fillsComplete':True,'incomeHistoryComplete':True,'financialVerified':True,
            'terminalVerified':True,'executedQty':'25',
            'executionFinancials':{'fill-1':['25','1','.1','-.05']}})
        self.assertEqual(transfer(**kw),'HANDOFF_VERIFIED_OFFLINE')
        self.assertEqual(transfer(**kw),'BLOCKED_EVIDENCE_UNAVAILABLE')
        self.assertEqual(db.snapshot('coord')[1]['recoveryFenceReservation']['intentId'],id2)
        self.assertEqual(db.snapshot('following')[1]['state'],'RESERVED')

    def test_four_verified_step_handoffs_preserve_history(self):
        from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
        from short_recovery_order_claim_shadow import canonical_intent_id
        from short_recovery_canonical_order_authorization import transfer_confirmed_recovery_step_offline
        db=MultiDocDB()
        ids={step:canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',
            side='SHORT',action='CLOSE',step=step) for step in range(1,5)}
        refs={step:Ref(db,'step-'+str(step)) for step in range(1,5)}
        coord=Ref(db,'coord'); control=Ref(db,'control')
        db.commit('control',0,{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
        db.commit('coord',0,{'recoveryFenceReservation':{'account':'u','symbol':'XRPUSDT',
            'cycle':'c','intentId':ids[1],'state':'RECOVERY_SUBMITTING_RECONCILE_ONLY'}})
        db.commit(refs[1].key,0,{'account':'u','symbol':'XRPUSDT','cycle':'c',
            'intentId':ids[1],'side':'SHORT','action':'CLOSE','step':1,'state':'RESERVED'})
        for step in range(2,5):
            prior=refs[step-1]
            version,row=db.snapshot(prior.key)
            db.commit(prior.key,version,{**row,'state':'CLOSED','orderId':'order-'+str(step-1),
                'executedQty':'25','terminalVerified':True,'fillsComplete':True,
                'incomeHistoryComplete':True,'financialVerified':True,
                'executionFinancials':{'fill-'+str(step-1):['25','1','.1','-.05']}})
            kwargs=dict(mock_only=True,db=db,transactional=transactional,
                coordination_ref=coord,previous_claim_ref=prior,next_claim_ref=refs[step],
                control_ref=control,account='u',symbol='XRPUSDT',cycle='c',
                previous_intent_id=ids[step-1],next_intent_id=ids[step],
                next_step=step,verified_financial_readback=True)
            self.assertEqual(transfer_confirmed_recovery_step_offline(**kwargs),
                'HANDOFF_VERIFIED_OFFLINE')
            self.assertEqual(db.snapshot(refs[step-1].key)[1]['state'],'CLOSED')
            self.assertEqual(db.snapshot(refs[step].key)[1]['state'],'RESERVED')
            self.assertNotEqual(transfer_confirmed_recovery_step_offline(**kwargs),
                'HANDOFF_VERIFIED_OFFLINE')
        self.assertEqual(db.snapshot(coord.key)[1]['recoveryFenceReservation']['intentId'],ids[4])

    def test_new_cycle_rehedge_preflight_and_submit_one_right(self):
        from datetime import datetime,timezone,timedelta
        from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
        from short_recovery_order_claim_shadow import pre_submit_check,submit_once_offline,canonical_intent_id
        from aster_gateway import AsterOrderIntent,PositionSide
        from decimal import Decimal
        db=MultiDocDB()
        coord=Ref(db,'coord');claim=Ref(db,'new-open');control=Ref(db,'control')
        cid=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c2',
            side='SHORT',action='OPEN',step=0)
        now=datetime.now(timezone.utc)
        db.commit('coord',0,{'lease':{'token':'lease-2','until':now+timedelta(seconds=60)},
            'recoveryFenceReservation':{'account':'u','symbol':'XRPUSDT',
            'cycle':'c2','previousCycle':'c','intentId':cid,
            'leaseToken':'lease-2','state':'REHEDGE_MOCK_SUBMITTING'}})
        db.commit('new-open',0,{'account':'u','symbol':'XRPUSDT','cycle':'c2',
            'intentId':cid,'side':'SHORT','action':'OPEN','step':0,'state':'RESERVED'})
        db.commit('control',0,{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
        kw=dict(db=db,transactional=transactional,claim_ref=claim,
            control_ref=control,coordination_ref=coord,account='u',symbol='XRPUSDT',
            cycle='c2',intent_id=cid,account_close_guard=lambda:None)
        self.assertEqual(pre_submit_check(**kw),'PREFLIGHT_SHADOW_ONLY')
        intent=AsterOrderIntent(cid,'XRPUSDT',PositionSide.SHORT,Decimal('100'),'OPEN')
        sent=[]
        def mock_submit(i):sent.append(i.intent_id)
        args={k:v for k,v in kw.items() if k!='intent_id'}
        self.assertEqual(submit_once_offline(**args,intent=intent,submit_mock=mock_submit,
            require_shared_fence=True),'SUBMITTED_RECONCILE_ONLY')
        self.assertEqual(sent,[cid])
        self.assertEqual(submit_once_offline(**args,intent=intent,submit_mock=mock_submit,
            require_shared_fence=True),'BLOCKED_CLAIM_NOT_RESERVED')
        self.assertEqual(sent,[cid])
        self.assertEqual(db.snapshot('new-open')[1]['state'],'SUBMITTING')
        self.assertEqual(db.snapshot('coord')[1]['recoveryFenceReservation']['state'],
            'REHEDGE_SUBMITTING_RECONCILE_ONLY')

    def test_expired_rehedge_lease_denies_before_mock_transport(self):
        from datetime import datetime,timezone,timedelta
        from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
        from short_recovery_order_claim_shadow import pre_submit_check,submit_once_offline,canonical_intent_id
        from aster_gateway import AsterOrderIntent,PositionSide
        from decimal import Decimal
        db=MultiDocDB();coord=Ref(db,'coord');claim=Ref(db,'open');control=Ref(db,'control')
        cid=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c2',side='SHORT',action='OPEN',step=0)
        db.commit('coord',0,{'lease':{'token':'lease','until':datetime.now(timezone.utc)-timedelta(seconds=1)},
            'recoveryFenceReservation':{'account':'u','symbol':'XRPUSDT','cycle':'c2',
            'previousCycle':'c','intentId':cid,'leaseToken':'lease','state':'REHEDGE_MOCK_SUBMITTING'}})
        db.commit('open',0,{'account':'u','symbol':'XRPUSDT','cycle':'c2','intentId':cid,
            'side':'SHORT','action':'OPEN','step':0,'state':'RESERVED'})
        db.commit('control',0,{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
        args=dict(db=db,transactional=transactional,claim_ref=claim,coordination_ref=coord,
            control_ref=control,account='u',symbol='XRPUSDT',cycle='c2',account_close_guard=lambda:None)
        self.assertEqual(pre_submit_check(**args,intent_id=cid),'BLOCKED_COORDINATION_LEASE_EXPIRED')
        calls=[]
        intent=AsterOrderIntent(cid,'XRPUSDT',PositionSide.SHORT,Decimal('100'),'OPEN')
        self.assertEqual(submit_once_offline(**args,intent=intent,
            submit_mock=lambda i:calls.append(i.intent_id),require_shared_fence=True),
            'BLOCKED_COORDINATION_LEASE_EXPIRED')
        self.assertEqual(calls,[])
        self.assertEqual(db.snapshot('open')[1]['state'],'RESERVED')

    def test_run_uid_new_cycle_rehedge_end_to_end_mock(self):
        from test_short_recovery_pair_aster_bridge import VerifiedAsterBridge
        from test_short_recovery_run_uid_integration import RunUidIntegration
        from short_recovery_multidoc_mock import Ref
        from short_recovery_order_claim_shadow import canonical_intent_id
        from datetime import datetime,timedelta,timezone
        from unittest.mock import Mock
        h=VerifiedAsterBridge('test_complete_independent_evidence_reaches_atomic_settlement')
        h.setUp()
        old=h.fixture.refs['SHORTclaim']
        previous=h.fixture.snapshot('SHORTclaim')
        close_cid=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',
            side='SHORT',action='CLOSE',step=4)
        h.fixture.put('SHORTclaim',{**previous,'state':'CLOSED','intentId':close_cid,
            'side':'SHORT','action':'CLOSE','step':4,'executedQty':'25'})
        opened=Ref(h.fixture.db,'new-cycle-short-open')
        h.fixture.refs['SHORTclaim']=opened
        coord=Ref(h.fixture.db,'new-cycle-coordination')
        owner=Ref(h.fixture.db,'old-cycle-owner')
        now=datetime.now(timezone.utc)
        h.fixture.db.commit(coord.key,0,{'lease':{'token':'lease-c2',
            'until':now+timedelta(seconds=60)}})
        h.fixture.db.commit(owner.key,0,{'account':'u','symbol':'XRPUSDT',
            'cycleId':'c','ownerSide':'SHORT','ownershipVerified':True,
            'cycleConfirmed':True,'state':'FINAL_PENDING'})
        class OfflineClient:
            offline_mock_only=True
            def account_information(self):return {'account':'u','hedgeMode':True}
            def position_risk(self,symbol):
                return [{'symbol':symbol,'positionSide':'LONG','positionAmt':'100'},
                    {'symbol':symbol,'positionSide':'SHORT','positionAmt':'0'}]
            def open_orders(self,symbol):return []
            def query_order(self,symbol,cid):
                return {'symbol':symbol,'clientOrderId':cid,'orderId':'SHORT-order',
                    'status':'FILLED','executedQty':'25'}
            def user_trades(self,symbol,**kwargs):
                return [{'symbol':symbol,'orderId':'SHORT-order','id':12,'qty':'25',
                    'realizedPnl':'1','commission':'.1'}]
        sent=Mock(return_value={'orderId':'mock-open'})
        scope={'new_cycle':'c2','lease_token':'lease-c2','coordination_ref':coord,
            'owner_ref':owner,'new_short_open_claim_ref':opened}
        report,_,_=RunUidIntegration().run_case(action_mode='REHEDGE',
            existing_harness=h,final_short_close_claim_ref=old,
            inventory_mock_client=OfflineClient(),mock_transport=sent,
            initialize_action_claim=False,rehedge_scope=scope)
        self.assertEqual(report['shortRecoveryAction']['status'],
            'BLOCKED_FINANCIAL_FINALITY_UNVERIFIED',report)
        self.assertIsNone(report.get('shortRecoverySubmit'))
        sent.assert_not_called()
        self.assertIsNone(h.fixture.db.snapshot(opened.key)[1])
        self.assertEqual(h.fixture.db.snapshot(old.key)[1]['state'],'CLOSED')
        self.assertIsNone(h.fixture.db.snapshot(coord.key)[1].get('recoveryFenceReservation'))
