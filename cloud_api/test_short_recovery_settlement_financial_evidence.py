"""Adversarial tests of canonical offline settlement financial proof."""
import unittest
from decimal import Decimal
from short_recovery_order_resolution_shadow import resolve
from short_recovery_firestore_mock import decode
from short_recovery_multidoc_mock import transactional
from test_short_recovery_build48_settlement import Tests as Fixture

class FinancialEvidence(unittest.TestCase):
    def setUp(self):
        self.h=Fixture('test_no_order_reconciled_terminal');self.h.setUp()
        self.h.event('ACK',order_id='o',evidence={'confirmed':True,'orderId':'o'})
    def event(self,evidence,execution='x',quantity=25):
        h=self.h
        return resolve(db=h.db,transactional=transactional,claim_ref=h.refs['claim'],ledger_ref=h.refs['ledger'],owner_ref=h.refs['owner'],marker_ref=h.refs['marker'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event='FILL',evidence=evidence,execution_id=execution,quantity=quantity)
    def proof(self,**changes):
        e={'confirmed':True,'readbackVerified':True,'orderId':'o','executionId':'x','quantity':'25','realizedPnl':'2.50','commission':'0.15','funding':'-0.05'}
        e.update(changes)
        return e
    def ledger(self):return decode(self.h.db.snapshot(self.h.keys['ledger'])[1])
    def test_nonzero_actual_net_booked_exactly_once(self):
        self.assertEqual(self.event(self.proof()),'FILL_APPLIED')
        self.assertEqual(self.ledger().cycle_realized('c'),Decimal('2.30'))
        self.assertEqual(self.event(self.proof()),'ALREADY_APPLIED')
        self.assertEqual(self.ledger().cycle_realized('c'),Decimal('2.30'))
    def test_missing_financial_values_block_and_do_not_mutate(self):
        for key in ('realizedPnl','commission','funding','readbackVerified','executionId','quantity'):
            with self.subTest(key=key):
                e=self.proof();e.pop(key)
                self.assertEqual(self.event(e),'BLOCKED_FINANCIAL_EVIDENCE')
                self.assertEqual(self.ledger().allocations[0].remaining,Decimal(100))
    def test_invalid_and_untrusted_values_block(self):
        for e in (self.proof(commission='NaN'),self.proof(realizedPnl='Infinity'),self.proof(commission='-1'),self.proof(readbackVerified=False),self.proof(executionId='wrong'),self.proof(quantity='40')):
            self.assertEqual(self.event(e),'BLOCKED_FINANCIAL_EVIDENCE')
        self.assertEqual(self.ledger().cycle_realized('c'),Decimal(0))
    def test_restart_preserves_net_and_dedup(self):
        self.assertEqual(self.event(self.proof()),'FILL_APPLIED')
        self.h.db=self.h.db.restart();self.h.bind()
        self.assertEqual(self.event(self.proof()),'ALREADY_APPLIED')
        self.assertEqual(self.ledger().cycle_realized('c'),Decimal('2.30'))
