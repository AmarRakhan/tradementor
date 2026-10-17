"""Offline Aster evidence to canonical resolution and frontend execution-gate contracts."""
import pathlib
import threading
import unittest
from decimal import Decimal
from short_recovery_aster_evidence_shadow import validate, EvidenceError
from short_recovery_order_resolution_shadow import resolve
from short_recovery_multidoc_mock import transactional
from short_recovery_firestore_mock import decode
from test_short_recovery_build48_settlement import Tests as Fixture
from test_short_recovery_real_reconciler_shadow import TestShadowReconciler

ROOT = pathlib.Path(__file__).resolve().parent.parent

class OfflineIntegration(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture('test_no_order_reconciled_terminal')
        self.fixture.setUp()
        self.scope = {'account':'u','symbol':'XRPUSDT','intentId':'intent','orderId':'o',
                      'source':'ASTER_READBACK_VERIFIED_MOCK','confirmed':True}
    def resolve(self,event,**kwargs):
        f=self.fixture
        return resolve(db=f.db,transactional=transactional,claim_ref=f.refs['claim'],
                       ledger_ref=f.refs['ledger'],marker_ref=f.refs['marker'],owner_ref=f.refs['owner'],
                       account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',event=event,**kwargs)
    def test_verified_mock_ack_and_fill_through_transaction(self):
        ack=validate({**self.scope,'status':'NEW'},kind='ACK',account='u',symbol='XRPUSDT',intent_id='intent')
        self.assertEqual(self.resolve('ACK',evidence={'confirmed':True,'orderId':ack['orderId']}),'ACKED')
        fill=validate({**self.scope,'executionId':'ex1','quantity':'25'},kind='FILL',account='u',symbol='XRPUSDT',intent_id='intent',expected_order_id=ack['orderId'])
        self.assertEqual(self.resolve('FILL',evidence={'confirmed':True,'orderId':fill['orderId']},execution_id=fill['executionId'],quantity=fill['quantity']),'FILL_APPLIED')
        self.assertEqual(decode(self.fixture.db.snapshot(self.fixture.keys['ledger'])[1]).allocations[0].remaining,Decimal(75))
        self.assertEqual(self.resolve('FILL',evidence={'confirmed':True,'orderId':'o'},execution_id='ex1',quantity=25),'ALREADY_APPLIED')
    def test_wrong_account_mock_evidence_never_booked(self):
        with self.assertRaises(EvidenceError):
            validate({**self.scope,'account':'another','executionId':'ex','quantity':'25'},kind='FILL',account='u',symbol='XRPUSDT',intent_id='intent')
        self.assertEqual(decode(self.fixture.db.snapshot(self.fixture.keys['ledger'])[1]).allocations[0].remaining,Decimal(100))
    def test_terminal_readback_required_before_claim_end(self):
        self.assertEqual(self.resolve('UNKNOWN'),'BLOCKED_UNKNOWN')
        with self.assertRaises(EvidenceError):
            validate({**self.scope,'status':'CANCELED','noMoreFills':False,'terminalReadback':True},kind='CANCEL_TERMINAL',account='u',symbol='XRPUSDT',intent_id='intent')
        self.assertEqual(self.fixture.db.snapshot(self.fixture.keys['claim'])[1]['state'],'UNKNOWN')
    def test_concurrent_verified_fill_once_after_restart(self):
        self.fixture.db=self.fixture.db.restart();self.fixture.bind()
        self.resolve('ACK',evidence={'confirmed':True,'orderId':'o'})
        results=[];lock=threading.Lock();barrier=threading.Barrier(4)
        def worker():
            barrier.wait()
            result=self.resolve('FILL',evidence={'confirmed':True,'orderId':'o'},execution_id='ex',quantity=25)
            with lock:results.append(result)
        threads=[threading.Thread(target=worker) for _ in range(4)]
        for t in threads:t.start()
        for t in threads:
            t.join(5)
            self.assertFalse(t.is_alive())
        self.assertCountEqual(results,['FILL_APPLIED']+['ALREADY_APPLIED']*3)
    def test_toggle_default_off_and_unwritable(self):
        preview=(ROOT/'web/components/short-recovery-plan-preview.tsx').read_text()
        self.assertIn('checked={false} disabled',preview)
        self.assertNotIn('authenticatedRequest(',preview)
        main=(ROOT/'cloud_api/aster_position_loss_auto_hedge_extension.py').read_text()
        self.assertIn('if (not execute and',main)
        self.assertIn('shortRecoveryPlan: dict[str, Any] | None = None',main)
    def test_non_recovery_autohedge_unchanged(self):
        original=TestShadowReconciler();original.setUp()
        report=original.run_shadow({'XRPUSDT'})
        self.assertEqual(report['ordersSent'],0)
        self.assertEqual([a['symbol'] for a in report['actions']],['BTCUSDT'])

if __name__=='__main__': unittest.main()
