"""Guard unknown Recovery ownership, without touching unrelated pairs."""
import threading
import unittest
from short_recovery_failclosed_shadow import classify
from test_short_recovery_real_reconciler_shadow import TestShadowReconciler
class Tests(unittest.TestCase):
 def setUp(self):
  self.case=TestShadowReconciler();self.case.setUp()
  self.kw=dict(settings={'enabled':True,'steps':4,'stepPct':'3'},protected_sides={'XRPUSDT':'LONG','BTCUSDT':'LONG'},existing_skip_symbols=set(),suspect_symbols={'XRPUSDT'},account_id='u')
 def test_missing_owner_blocks_legacy_topup(self):
  r=classify(**self.kw,ownership_rows={})
  self.assertEqual(r['pairs']['XRPUSDT'],'BLOCKED_MISSING_OWNERSHIP')
  actual=self.case.run_shadow(r['shadow_skip'])
  self.assertEqual([x['symbol'] for x in actual['actions']],['BTCUSDT'])
 def test_revoked_owner_blocked(self):
  r=classify(**self.kw,ownership_rows={'XRPUSDT':{'account':'u','symbol':'XRPUSDT','ownerSide':'SHORT','cycleConfirmed':True,'ownershipVerified':False,'state':'PARTIAL'}})
  self.assertEqual(r['pairs']['XRPUSDT'],'BLOCKED_UNCERTAIN_OWNERSHIP')
  self.assertNotIn('XRPUSDT',[x['symbol'] for x in self.case.run_shadow(r['shadow_skip'])['actions']])
 def test_valid_owner_and_other_pair_untouched(self):
  r=classify(**self.kw,ownership_rows={'XRPUSDT':{'account':'u','symbol':'XRPUSDT','ownerSide':'SHORT','cycleConfirmed':True,'ownershipVerified':True,'state':'PARTIAL'}})
  self.assertEqual(r['pairs']['XRPUSDT'],'SHADOW_VERIFIED_PARTIAL')
  self.assertEqual([x['symbol'] for x in self.case.run_shadow(r['shadow_skip'])['actions']],['BTCUSDT'])
 def test_concurrent_read_only_calls(self):
  out=[];lock=threading.Lock();barrier=threading.Barrier(8)
  def run():
   barrier.wait();r=classify(**self.kw,ownership_rows={})
   with lock:out.append(r['shadow_skip'])
  workers=[threading.Thread(target=run) for _ in range(8)]
  for w in workers:w.start()
  for w in workers:w.join(5);self.assertFalse(w.is_alive())
  self.assertTrue(all(x=={'XRPUSDT'} for x in out))
 def test_cross_account_blocked(self):
  r=classify(**self.kw,ownership_rows={'XRPUSDT':{'account':'other','symbol':'XRPUSDT','ownerSide':'SHORT','cycleConfirmed':True,'ownershipVerified':True,'state':'PARTIAL'}})
  self.assertEqual(r['pairs']['XRPUSDT'],'BLOCKED_SCOPE_MISMATCH')
  self.assertNotIn('XRPUSDT',[a['symbol'] for a in self.case.run_shadow(r['shadow_skip'])['actions']])
 def test_account_scope_must_be_supplied_externally(self):
  r=classify(**self.kw,ownership_rows={'XRPUSDT':{'account':'u','symbol':'XRPUSDT','ownerSide':'SHORT','cycleConfirmed':False,'ownershipVerified':True,'state':'PARTIAL'}})
  self.assertEqual(r['pairs']['XRPUSDT'],'BLOCKED_UNCERTAIN_OWNERSHIP')
if __name__=='__main__':unittest.main()
