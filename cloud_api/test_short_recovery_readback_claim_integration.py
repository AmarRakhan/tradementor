"""Existing Aster GET adapter -> canonical claim/resolver, in offline mocks only.

READBACK_PREVIEW cannot be promoted into execution-level funding ownership proof.
"""
import threading
import unittest
from decimal import Decimal
from short_recovery_aster_readback_mock_adapter import inspect
from short_recovery_order_resolution_shadow import resolve
from short_recovery_firestore_mock import decode
from short_recovery_multidoc_mock import transactional
from test_short_recovery_build48_settlement import Tests as Fixture

class MockAster:
    def __init__(self):
        self.order={'symbol':'XRPUSDT','clientOrderId':'intent','orderId':'o','status':'FILLED'}
        self.rows=[{'id':11,'orderId':'o','symbol':'XRPUSDT','qty':'25','realizedPnl':'2.5','commission':'.1','funding':'-.05'}]
        self.calls=[]
    def query_order(self,symbol,client_order_id):
        self.calls.append('query_order');return dict(self.order)
    def user_trades(self,symbol,limit=500):
        self.calls.append('user_trades');return list(self.rows)
    def submit_order(self,*args,**kwargs):raise AssertionError('no orders')

class Integration(unittest.TestCase):
    def setUp(self):
        self.h=Fixture('test_no_order_reconciled_terminal');self.h.setUp()
        self.c=MockAster()
    def run_event(self,event,evidence=None,execution_id=None,quantity=None):
        h=self.h
        return resolve(db=h.db,transactional=transactional,claim_ref=h.refs['claim'],ledger_ref=h.refs['ledger'],marker_ref=h.refs['marker'],owner_ref=h.refs['owner'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event=event,evidence=evidence,execution_id=execution_id,quantity=quantity)
    def ledger(self):return decode(self.h.db.snapshot(self.h.keys['ledger'])[1])
    def test_aster_preview_never_implicitly_certifies_financial_evidence(self):
        preview=inspect(self.c,symbol='XRPUSDT',client_order_id='intent')
        self.assertEqual(preview['status'],'READBACK_PREVIEW')
        self.assertFalse(preview['terminalVerified'])
        self.assertEqual(self.run_event('ACK',{'confirmed':True,'orderId':'o'}),'ACKED')
        raw=preview['fills'][0]
        # Actual adapter preview cannot be marked 'readbackVerified' because
        # completeness, income pagination and cycle attribution remain unproven.
        e={'confirmed':True,'orderId':raw['orderId'],'executionId':raw['executionId'],
           'quantity':str(raw['quantity']),'realizedPnl':str(raw['realizedPnl']),
           'commission':str(raw['fee']),'funding':str(raw['funding'])}
        self.assertEqual(self.run_event('FILL',e,raw['executionId'],raw['quantity']),'BLOCKED_FINANCIAL_EVIDENCE')
        self.assertEqual(self.ledger().allocations[0].remaining,Decimal(100))
        self.assertEqual(self.ledger().cycle_realized('c'),Decimal(0))
        self.assertEqual(self.c.calls,['query_order','user_trades'])
    def test_missing_aster_funding_does_not_create_trusted_zero(self):
        self.c.rows[0].pop('funding')
        raw=inspect(self.c,symbol='XRPUSDT',client_order_id='intent')['fills'][0]
        self.assertIsNone(raw['funding'])  # never invent a zero funding amount
        self.run_event('ACK',{'confirmed':True,'orderId':'o'})
        self.assertEqual(self.run_event('FILL',{'confirmed':True,'orderId':'o',
            'executionId':raw['executionId'],'quantity':str(raw['quantity']),
            'realizedPnl':str(raw['realizedPnl']),'commission':str(raw['fee']),
            'funding':str(raw['funding'])},raw['executionId'],raw['quantity']),'BLOCKED_FINANCIAL_EVIDENCE')
    def test_claim_cycle_scope_rejects_wrong_ownership(self):
        self.h.db.commit(self.h.keys['owner'],1,{'account':'u','symbol':'XRPUSDT','cycleId':'other','ownershipVerified':True,'ownerSide':'SHORT','cycleConfirmed':True,'state':'PARTIAL'})
        self.assertEqual(self.run_event('ACK',{'confirmed':True,'orderId':'o'}),'BLOCKED_OWNER')
    def test_restart_replay_without_verified_financial_evidence_never_books(self):
        self.run_event('ACK',{'confirmed':True,'orderId':'o'})
        self.h.db=self.h.db.restart();self.h.bind()
        gate=threading.Barrier(4);results=[];lock=threading.Lock()
        def work():
            gate.wait()
            r=self.run_event('FILL',{'confirmed':True,'orderId':'o'},'11',25)
            with lock:results.append(r)
        ts=[threading.Thread(target=work) for _ in range(4)]
        for t in ts:t.start()
        for t in ts:
            t.join(5)
            self.assertFalse(t.is_alive())
        self.assertEqual(results,['BLOCKED_FINANCIAL_EVIDENCE']*4)
        self.assertEqual(self.ledger().allocations[0].remaining,Decimal(100))

class ReadbackFinancialCompleteness(unittest.TestCase):
    def test_missing_pnl_and_commission_fail_closed(self):
        for field in ('realizedPnl', 'commission'):
            client=MockAster()
            client.rows[0].pop(field)
            self.assertEqual(inspect(client,symbol='XRPUSDT',client_order_id='intent')['status'],'BLOCKED_MISSING_FINANCIAL_EVIDENCE')
    def test_explicit_zero_is_not_missing(self):
        client=MockAster()
        client.rows[0]['realizedPnl']='0'
        client.rows[0]['commission']='0'
        self.assertEqual(inspect(client,symbol='XRPUSDT',client_order_id='intent')['status'],'READBACK_PREVIEW')
    def test_missing_funding_is_unknown_not_zero(self):
        client=MockAster();client.rows[0].pop('funding')
        preview=inspect(client,symbol='XRPUSDT',client_order_id='intent')
        self.assertIsNone(preview['fills'][0]['funding'])
        self.assertFalse(preview['terminalVerified'])

class PaginationAndFundingProof(unittest.TestCase):
    def test_full_fill_page_never_claims_complete(self):
        client=MockAster()
        client.rows=client.rows*500
        result=inspect(client,symbol='XRPUSDT',client_order_id='intent')
        self.assertEqual(result['status'],'BLOCKED_INCOMPLETE_FILL_PAGE')
        self.assertFalse(result['terminalVerified'])
    def test_conflicting_duplicate_execution_fails_closed(self):
        client=MockAster()
        duplicate={**client.rows[0],'realizedPnl':'999'}
        client.rows.append(duplicate)
        result=inspect(client,symbol='XRPUSDT',client_order_id='intent')
        self.assertEqual(result['status'],'BLOCKED_DUPLICATE_EXECUTION')
    def test_readback_preview_cannot_establish_funding_cycle(self):
        client=MockAster()
        result=inspect(client,symbol='XRPUSDT',client_order_id='intent')
        self.assertEqual(result['status'],'READBACK_PREVIEW')
        self.assertFalse(result['terminalVerified'])
        self.assertEqual(result['ordersSent'],0)
