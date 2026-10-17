"""Buildstop 36: pure in-memory safety regressions; never invokes exchange or persistence."""
import unittest
from decimal import Decimal as D
from short_recovery_mock import Cycle, confirmed_fill
from short_recovery_executor_adapter import preview_mock_executor
from short_recovery_ledger import Ledger, Allocation, Fill
import test_short_recovery_real_reconciler_shadow as real_shadow

class Build36Safety(unittest.TestCase):
    def setUp(self):
        self.ledger=Ledger('account','XRPUSDT',(Allocation('zoneA','cycle1',D(100)),))
        self.cycle=Cycle(D(2),D(100))
        self.settings={'enabled':True,'steps':4,'stepPct':'3'}
    def fill(self,ledger,execution,qty):
        return ledger.apply(Fill('account','XRPUSDT',execution,'order-'+execution,D(qty),D(0),D(0)),(('zoneA','cycle1',D(qty)),))
    def test_restart_rehydrated_inventory_and_cycle(self):
        saved=self.fill(self.ledger,'e1',D(25))
        restored=Ledger(saved.account,saved.symbol,tuple(saved.allocations),frozenset(saved.seen),tuple(saved.booked))
        restored_cycle=Cycle(D(2),D(100),D(25))
        proposal=preview_mock_executor(restored_cycle,D('1.8'),self.settings,exchange_short=restored.allocations[0].remaining,long_qty=D(100))
        self.assertEqual(proposal['quantity'],'50')
        self.assertEqual(proposal['ordersSent'],0)
        with self.assertRaises(ValueError): self.fill(restored,'e1',D(25))
    def test_two_stale_concurrent_copies_require_cas(self):
        a=self.fill(self.ledger,'e1',D(75))
        b=self.fill(self.ledger,'e2',D(75))
        self.assertEqual(a.allocations[0].remaining,D(25))
        self.assertEqual(b.allocations[0].remaining,D(25))
        self.assertNotEqual(a.seen,b.seen)
        # An external atomic compare-and-swap is mandatory; the pure ledger does not persist either snapshot.
    def test_owner_allocation_isolation(self):
        with self.assertRaises(ValueError):
            self.ledger.apply(Fill('account','XRPUSDT','e1','o',D(5),D(0),D(0)),(('zoneB','cycle1',D(5)),))
    def test_pending_claim_and_mismatch_block(self):
        busy=preview_mock_executor(self.cycle,D('1.8'),self.settings,exchange_short=D(100),long_qty=D(100),claims_busy=True)
        self.assertEqual((busy['status'],busy['ordersSent']),('BLOCKED_CLAIM_BUSY',0))
        mismatch=preview_mock_executor(self.cycle,D('1.8'),self.settings,exchange_short=D(75),long_qty=D(100))
        self.assertEqual(mismatch['status'],'BLOCKED_EXCHANGE_MISMATCH')
    def test_legacy_reconciler_would_topup_without_skip(self):
        case=real_shadow.TestShadowReconciler();case.setUp()
        unguarded=case.run_shadow(None)
        guarded=case.run_shadow({'XRPUSDT'})
        self.assertIn('XRPUSDT',[x['symbol'] for x in unguarded['actions']])
        self.assertNotIn('XRPUSDT',[x['symbol'] for x in guarded['actions']])
        self.assertEqual(guarded['ordersSent'],0)
if __name__=='__main__':unittest.main()
