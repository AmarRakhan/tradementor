"""Offline individual SHORT close must not inherit whole-cycle terminality."""
import unittest
from decimal import Decimal
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_ledger import Ledger,Allocation,Fill
from short_recovery_firestore_mock import encode
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_order_resolution_shadow import finalize_individual_short_order_offline


class IndividualShortFinality(unittest.TestCase):
    def test_filled_25_percent_order_cannot_claim_unproven_funding(self):
        db=MultiDocDB()
        claim=Ref(db,'claim');ledger_ref=Ref(db,'ledger');control=Ref(db,'control')
        cid=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',
            side='SHORT',action='CLOSE',step=1)
        qty=Decimal('25')
        ledger=Ledger('u','XRPUSDT',(Allocation('SHORT','c',Decimal('100')),))
        ledger=ledger.apply(Fill('u','XRPUSDT','7','order-7',qty,
            Decimal('1'),Decimal('.1'),Decimal('-.05')),(('SHORT','c',qty),))
        db.commit('ledger',0,encode(ledger))
        row={'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':cid,
            'side':'SHORT','action':'CLOSE','step':1,'state':'PARTIAL',
            'orderId':'order-7','executedQty':'25',
            'executionFinancials':{'7':['25','1','.1','-.05']}}
        db.commit('claim',0,row)
        db.commit('control',0,{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
        class Aster:
            offline_mock_only=True
            def query_order(self,symbol,intent):
                return {'symbol':symbol,'clientOrderId':intent,'orderId':'order-7',
                    'status':'FILLED','executedQty':'25'}
            def user_trades(self,symbol,**kwargs):
                return [{'symbol':symbol,'id':7,'orderId':'order-7','qty':'25',
                    'realizedPnl':'1','commission':'.1'}]
            def income_history(self,**kwargs):
                return []
        status=finalize_individual_short_order_offline(mock_only=True,db=db,
            transactional=transactional,claim_ref=claim,ledger_ref=ledger_ref,
            control_ref=control,client=Aster(),account='u',symbol='XRPUSDT',
            cycle='c',intent_id=cid,funding_start_ms=1000,funding_end_ms=2000)
        self.assertEqual(status,'BLOCKED_INDEPENDENT_FUNDING_PROVENANCE')
        terminal=db.snapshot('claim')[1]
        self.assertEqual(terminal['state'],'PARTIAL')
        self.assertIs(terminal['orderTerminalVerified'],True)
        self.assertEqual(terminal['orderTerminalStatus'],'FILLED')
        self.assertEqual(terminal['financialSettlementStatus'],'FUNDING_PROVENANCE_PENDING')
        self.assertNotIn('terminalVerified',terminal)
        self.assertNotIn('incomeHistoryComplete',terminal)
        self.assertEqual(db.snapshot('ledger')[1],encode(ledger))
        self.assertEqual(ledger.allocations[0].remaining,Decimal('75'))

    def test_absent_trusted_client_cannot_finalize(self):
        self.assertEqual(finalize_individual_short_order_offline(
            mock_only=True,db=MultiDocDB(),transactional=transactional,
            claim_ref=None,ledger_ref=None,control_ref=None,client=object(),
            account='u',symbol='XRPUSDT',cycle='c',intent_id='bad',
            funding_start_ms=1000,funding_end_ms=2000),'BLOCKED_OFFLINE_SCOPE')

    def test_emergency_stop_denies_before_any_exchange_readback(self):
        db=MultiDocDB()
        control=Ref(db,'control')
        db.commit('control',0,{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
        class Aster:
            offline_mock_only=True
            def query_order(self,*args):raise AssertionError('must not contact exchange')
        result=finalize_individual_short_order_offline(
            mock_only=True,db=db,transactional=transactional,
            claim_ref=Ref(db,'claim'),ledger_ref=Ref(db,'ledger'),control_ref=control,
            client=Aster(),account='u',symbol='XRPUSDT',cycle='c',intent_id='mock',
            funding_start_ms=1000,funding_end_ms=2000)
        self.assertEqual(result,'BLOCKED_STOP')

    def test_funding_rows_with_untrusted_order_or_cycle_tags_do_not_grant_finality(self):
        from short_recovery_funding_provenance_decision import decide,NO_GO
        rows=[{'symbol':'XRPUSDT','incomeType':'FUNDING_FEE',
            'tranId':'a1','time':1500,'income':'-0.05','orderId':'order-7',
            'positionSide':'SHORT','cycleId':'c'}]
        self.assertEqual(decide(account='u',symbol='XRPUSDT',cycle='c',
            income_rows=rows,financial_proof={'complete':True,
            'independentlyVerified':True,'fundingOwnershipVerified':True}),NO_GO)
        self.assertEqual(decide(account='u',symbol='XRPUSDT',cycle='c',
            income_rows=[],financial_proof={'funding':'0','complete':True}),NO_GO)

    def test_income_pagination_and_symbol_filter_cannot_attest_cycle(self):
        from short_recovery_independent_funding_gate import inspect_mock_coverage
        class Mock:
            offline_mock_only=True
            def income_history(self,**kw):
                return [{'symbol':'XRPUSDT','incomeType':'FUNDING_FEE',
                    'tranId':'a1','time':1500,'income':'-.05',
                    'positionSide':'SHORT','cycleId':'c'}]
        result=inspect_mock_coverage(client=Mock(),account='u',symbol='XRPUSDT',
            cycle='c',start_ms=1000,end_ms=2000)
        self.assertNotEqual(result,'INDEPENDENT_FUNDING_PROVENANCE_VERIFIED')

    def test_changing_fills_across_readbacks_never_finalize(self):
        db=MultiDocDB();control=Ref(db,'ctrl');claim=Ref(db,'claim');ledger_ref=Ref(db,'ledger')
        db.commit('ctrl',0,{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
        cid=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1)
        row={'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':cid,'side':'SHORT',
             'action':'CLOSE','step':1,'state':'PARTIAL','orderId':'oid','executedQty':'25'}
        db.commit('claim',0,row)
        db.commit('ledger',0,encode(Ledger('u','XRPUSDT',(Allocation('SHORT','c',Decimal('75')),))))
        class Drifting:
            offline_mock_only=True
            calls=0
            def query_order(self,s,c):return {'symbol':s,'clientOrderId':c,'orderId':'oid','status':'FILLED','executedQty':'25'}
            def user_trades(self,s,**kw):
                self.calls+=1
                return [{'symbol':s,'orderId':'oid','id':7,'qty':'25',
                         'realizedPnl':'1' if self.calls==1 else '2','commission':'.1'}]
            def income_history(self,**kw):raise AssertionError('must block before funding read')
        result=finalize_individual_short_order_offline(mock_only=True,db=db,transactional=transactional,
            claim_ref=claim,ledger_ref=ledger_ref,control_ref=control,client=Drifting(),account='u',
            symbol='XRPUSDT',cycle='c',intent_id=cid,funding_start_ms=1000,funding_end_ms=2000)
        self.assertEqual(result,'BLOCKED_ORDER_READBACK_DRIFT')
        self.assertEqual(db.snapshot('claim')[1],row)

    def test_concurrent_ledger_change_blocks_terminal_claim(self):
        db=MultiDocDB();claim=Ref(db,'claim');ledger_ref=Ref(db,'ledger');control=Ref(db,'control')
        cid=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1)
        original=Ledger('u','XRPUSDT',(Allocation('SHORT','c',Decimal('100')),))
        original=original.apply(Fill('u','XRPUSDT','7','oid',Decimal('25'),Decimal('1'),
            Decimal('.1'),Decimal('-.05')),(('SHORT','c',Decimal('25')),))
        db.commit('ledger',0,encode(original))
        row={'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':cid,'side':'SHORT',
            'action':'CLOSE','step':1,'state':'PARTIAL','orderId':'oid','executedQty':'25',
            'executionFinancials':{'7':['25','1','.1','-.05']}}
        db.commit('claim',0,row)
        db.commit('control',0,{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
        class Client:
            offline_mock_only=True
            def query_order(self,s,c):
                return {'symbol':s,'clientOrderId':c,'orderId':'oid','status':'FILLED','executedQty':'25'}
            def user_trades(self,s,**kw):
                return [{'symbol':s,'orderId':'oid','id':7,'qty':'25','realizedPnl':'1','commission':'.1'}]
            def income_history(self,**kw):return []
        # Force a change between first read and atomic terminal claim update.
        class LedgerRef:
            def __init__(self):self.calls=0
            def get(self,transaction):
                self.calls+=1
                if self.calls==2:
                    v,old=db.snapshot('ledger')
                    db.commit('ledger',v,{**old,'concurrentFillMarker':True})
                return ledger_ref.get(transaction=transaction)
        actual=finalize_individual_short_order_offline(mock_only=True,db=db,transactional=transactional,
            claim_ref=claim,ledger_ref=LedgerRef(),control_ref=control,client=Client(),
            account='u',symbol='XRPUSDT',cycle='c',intent_id=cid,
            funding_start_ms=1000,funding_end_ms=2000)
        self.assertEqual(actual,'BLOCKED_ORDER_TERMINAL_CONCURRENT_CHANGE')
        self.assertEqual(db.snapshot('claim')[1],row)
