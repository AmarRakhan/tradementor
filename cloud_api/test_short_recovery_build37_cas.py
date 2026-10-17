"""Buildstop 37: in-memory transactional mock, no real database or exchange."""
import threading
import unittest
from decimal import Decimal as D
from short_recovery_ledger import Ledger, Allocation, Fill
from short_recovery_gate import partition_reconciliation
from aster_position_loss_auto_hedge import reconcile_auto_hedge

class MockCASStore:
    def __init__(self,ledger):
        self.lock=threading.Lock(); self.version=0; self.ledger=ledger
    def read(self):
        with self.lock:return self.version,self.ledger
    def compare_and_swap(self,version,ledger):
        with self.lock:
            if version!=self.version:return False
            self.ledger=ledger;self.version+=1;return True

class NoExchange:
    def submit_order(self,*args,**kwargs):raise AssertionError('LIVE ORDER FORBIDDEN')
    def position_risk(self):raise AssertionError('EXCHANGE READ FORBIDDEN')
    def open_orders(self):raise AssertionError('EXCHANGE READ FORBIDDEN')

class Build37(unittest.TestCase):
    def setUp(self):
        self.store=MockCASStore(Ledger('u','XRPUSDT',(Allocation('z','cycle',D(100)),)))
    def apply(self,store,execution,qty,worker='u'):
        for _ in range(8):
            version,ledger=store.read()
            if execution in ledger.seen:return 'ALREADY_APPLIED'
            proposed=ledger.apply(Fill(worker,'XRPUSDT',execution,'order-'+execution,D(qty),D(0),D(0)),(('z','cycle',D(qty)),))
            if store.compare_and_swap(version,proposed):return 'APPLIED'
        return 'RETRY_EXHAUSTED'
    def test_restart_duplicate_idempotent(self):
        self.assertEqual(self.apply(self.store,'fill1',25),'APPLIED')
        restart=MockCASStore(self.store.read()[1]);restart.version=self.store.version
        self.assertEqual(self.apply(restart,'fill1',25),'ALREADY_APPLIED')
        self.assertEqual(restart.read()[1].allocations[0].remaining,D(75))
    def test_stale_compare_and_swap_rejected(self):
        version,old=self.store.read()
        a=old.apply(Fill('u','XRPUSDT','a','oa',D(75),D(0),D(0)),(('z','cycle',D(75)),))
        b=old.apply(Fill('u','XRPUSDT','b','ob',D(75),D(0),D(0)),(('z','cycle',D(75)),))
        self.assertTrue(self.store.compare_and_swap(version,a))
        self.assertFalse(self.store.compare_and_swap(version,b))
    def test_two_workers_one_fill_exactly_once(self):
        barrier=threading.Barrier(2);out=[];guard=threading.Lock()
        def run():
            barrier.wait()
            result=self.apply(self.store,'same',25)
            with guard:out.append(result)
        threads=[threading.Thread(target=run) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(5);self.assertFalse(t.is_alive())
        self.assertCountEqual(out,['APPLIED','ALREADY_APPLIED'])
        self.assertEqual(self.store.read()[1].allocations[0].remaining,D(75))
    def test_cross_zone_and_account_rejected(self):
        with self.assertRaises(ValueError):self.apply(self.store,'cross',10,worker='other')
        self.assertEqual(self.store.version,0)
    def test_shadow_ownership_not_executable(self):
        plan=partition_reconciliation(settings={'enabled':True,'steps':4,'stepPct':'3'},
            protected_sides={'XRPUSDT':'LONG'},existing_skip_symbols=set(),
            recovery_cycles={'XRPUSDT':{'ownerSide':'SHORT','cycleConfirmed':True,'ownershipVerified':True,'state':'PARTIAL'}})
        self.assertIn('XRPUSDT',plan['shadow_skip'])
        self.assertNotIn('XRPUSDT',plan['legacy_skip'])
        positions=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-10','markPrice':'1.8'},
                   {'symbol':'XRPUSDT','positionSide':'SHORT','positionAmt':'-75','unRealizedProfit':'10','markPrice':'1.8'}]
        kw=dict(client=NoExchange(),uid='mock',threshold_usd=1,execute=False,
                protected_sides={'XRPUSDT':'LONG'},positions=positions,open_orders=[])
        unsafe=reconcile_auto_hedge(**kw)
        protected=reconcile_auto_hedge(**kw,recovery_shadow_skip_symbols=plan['shadow_skip'])
        self.assertIn('XRPUSDT',[a['symbol'] for a in unsafe['actions']])
        self.assertNotIn('XRPUSDT',[a['symbol'] for a in protected['actions']])
        self.assertEqual(protected['ordersSent'],0)
if __name__=='__main__':unittest.main()
