"""No-live-order tests for a canonical proof read."""
import unittest
from short_recovery_multidoc_mock import MultiDocDB, Ref, transactional
from short_recovery_firestore_mock import encode
from short_recovery_ledger import Ledger, Allocation
from decimal import Decimal as D
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_reconciler_proof import confirmed_reduction_proof

class ProofContract(unittest.TestCase):
    def setUp(self):
        self.db=MultiDocDB()
        self.refs={x:Ref(self.db,x) for x in ('owner','claim','ledger','control')}
        self.rows={
          'owner':{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'},
          'claim':{'account':'u','symbol':'XRPUSDT','cycle':'c','side':'SHORT','action':'CLOSE','step':1,'intentId':canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1),'state':'PARTIAL','executedQty':'25'},
          'ledger':encode(Ledger('u','XRPUSDT',(Allocation('zone','c',D(75)),))),
          'control':{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False}}
        for key,val in self.rows.items(): self.db.commit(key,0,val)
    def proof(self):
        return confirmed_reduction_proof(db=self.db,transactional=transactional,account='u',symbol='XRPUSDT',cycle='c',**{k+'_ref':v for k,v in self.refs.items()})
    def change(self,key,**values):
        v,row=self.db.snapshot(key);self.db.commit(key,v,{**row,**values})
    def test_confirmed(self):self.assertTrue(self.proof())
    def test_unsettled_claim(self):self.change('claim',state='SUBMITTING');self.assertFalse(self.proof())
    def test_wrong_cycle(self):self.change('owner',cycleId='old');self.assertFalse(self.proof())
    def test_false_ownership(self):self.change('owner',ownershipVerified=False);self.assertFalse(self.proof())
    def test_wrong_intent(self):self.change('claim',intentId='wrong');self.assertFalse(self.proof())
    def test_no_confirmed_quantity(self):self.change('claim',executedQty='0');self.assertFalse(self.proof())
    def test_emergency_stop(self):self.change('control',emergencyStop=True);self.assertFalse(self.proof())
    def test_missing_ledger(self):self.change('ledger',allocations=[]);self.assertFalse(self.proof())
    def test_restart(self):
        self.db=self.db.restart();self.refs={x:Ref(self.db,x) for x in self.refs};self.assertTrue(self.proof())
    def test_nonfinite(self):self.change('claim',executedQty='NaN');self.assertFalse(self.proof())
    def test_unreliable_readback(self):
        self.change('claim', executedQty='unknown')
        self.assertFalse(self.proof())
    def test_conflicting_claim_scope(self):
        self.change('claim', cycle='different')
        self.assertFalse(self.proof())
    def test_rehedge_open_claim_not_suppressed(self):
        self.change('claim', action='OPEN')
        self.assertFalse(self.proof())
    def test_claim_pending_partial_fill(self):
        self.change('claim', state='ACKED')
        self.assertFalse(self.proof())
    def test_close_all_blocks(self):
        self.change('control', closeAllActive=True)
        self.assertFalse(self.proof())
    def test_four_canonical_steps(self):
        for step in range(1, 5):
            self.change('claim', step=step, intentId=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=step), executedQty=str(25*step))
            self.assertTrue(self.proof())
    def test_concurrent_read_only_proof(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as executor:
            self.assertEqual(list(executor.map(lambda _: self.proof(), range(24))), [True]*24)
