"""Actual AsterV3Client pre-submit callback with fully mocked HTTP transport."""
import unittest
import httpx
from decimal import Decimal
from aster_gateway import AsterV3Client, AsterOrderIntent, AsterAutomationConfig, PositionSide
from short_recovery_order_claim_shadow import pre_submit_check
from short_recovery_multidoc_mock import transactional
from short_recovery_order_resolution_shadow import resolve
from test_short_recovery_build48_settlement import Tests as Fixture

class GatewayFinalGuard(unittest.TestCase):
    def setUp(self):
        self.h=Fixture('test_no_order_reconciled_terminal');self.h.setUp();self.posts=[]
    def control(self,**kwargs):
        k=self.h.keys['control'];v,x=self.h.db.snapshot(k);self.h.db.commit(k,v,{**x,**kwargs})
    def run_gateway(self,account_guard=lambda:None):
        h=self.h
        def final_guard(intent):
            self.assertEqual(intent.intent_id,'intent')
            result=pre_submit_check(db=h.db,transactional=transactional,claim_ref=h.refs['claim'],control_ref=h.refs['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',account_close_guard=account_guard)
            if result!='PREFLIGHT_SHADOW_ONLY':raise RuntimeError(result)
        def transport(request):
            self.posts.append(request.url.path)
            return httpx.Response(200,json={'orderId':'o'})
        client=AsterV3Client(signer_address='0xagent',sign_message=lambda _: 'sig',transport=httpx.MockTransport(transport),live_authorized=True,before_order_submit=final_guard)
        try:
            return client.submit_order_once(AsterOrderIntent('intent','XRPUSDT',PositionSide.SHORT,Decimal('25'),'CLOSE'),config=AsterAutomationConfig(enabled=True,mode='live'),confirm=True,hedge_mode_confirmed=True,risk_approved=False)
        finally:client._http.close()
    def test_disable_between_claim_and_gateway_pre_submit(self):
        self.control(enabled=False)
        with self.assertRaisesRegex(RuntimeError,'BLOCKED_RECOVERY_DISABLED_OR_STOPPED'):self.run_gateway()
        self.assertEqual(self.posts,[])
    def test_emergency_between_claim_and_gateway_pre_submit(self):
        self.control(emergencyStop=True)
        with self.assertRaisesRegex(RuntimeError,'BLOCKED_RECOVERY_DISABLED_OR_STOPPED'):self.run_gateway()
        self.assertEqual(self.posts,[])
    def test_close_all_between_claim_and_gateway_pre_submit(self):
        self.control(closeAllActive=True)
        with self.assertRaisesRegex(RuntimeError,'BLOCKED_RECOVERY_DISABLED_OR_STOPPED'):self.run_gateway()
        self.assertEqual(self.posts,[])
    def test_account_guard_final_veto(self):
        def guard():raise RuntimeError('existing account close lock')
        with self.assertRaisesRegex(RuntimeError,'BLOCKED_ACCOUNT_PRE_SUBMIT_GUARD'):self.run_gateway(guard)
        self.assertEqual(self.posts,[])
    def test_unknown_reconcile_after_gateway_rejection(self):
        self.control(emergencyStop=True)
        with self.assertRaises(RuntimeError):self.run_gateway()
        h=self.h
        result=resolve(db=h.db,transactional=transactional,claim_ref=h.refs['claim'],ledger_ref=h.refs['ledger'],marker_ref=h.refs['marker'],owner_ref=h.refs['owner'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event='UNKNOWN')
        self.assertEqual(result,'BLOCKED_UNKNOWN')
        self.assertEqual(self.posts,[])
