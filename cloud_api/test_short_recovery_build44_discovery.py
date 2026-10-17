"""Offline persisted Recovery discovery and actual order-free reconciler tests."""
import unittest
import threading
from short_recovery_suspect_discovery import preview
from test_short_recovery_real_reconciler_shadow import TestShadowReconciler
class Tests(unittest.TestCase):
 def setUp(self):
  self.saved={('u','XRPUSDT','ledger'):{'account':'u','symbol':'XRPUSDT','allocations':[('z','c','75')]},
    ('u','XRPUSDT','owner'):{'account':'u','symbol':'XRPUSDT','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'}}
  self.case=TestShadowReconciler();self.case.setUp()
 def lookup(self,kind):return lambda u,s:self.saved.get((u,s,kind))
 def result(self):
  return preview(account_id='u',symbols={'XRPUSDT','BTCUSDT'},read_ledger=self.lookup('ledger'),read_owner=self.lookup('owner'),settings={'enabled':True,'steps':4,'stepPct':'3'},protected_sides={'XRPUSDT':'LONG','BTCUSDT':'LONG'},existing_skip_symbols=set())
 def assert_safe(self):
  r=self.result();self.assertEqual(r['routing']['shadow_skip'],{'XRPUSDT'})
  self.assertEqual([a['symbol'] for a in self.case.run_shadow(r['routing']['shadow_skip'])['actions']],['BTCUSDT'])
 def test_restart_saved_ledger_and_owner(self):self.saved=dict(self.saved);self.assert_safe()
 def test_missing_owner_but_ledger_present(self):self.saved.pop(('u','XRPUSDT','owner'));self.assert_safe()
 def test_owner_only_missing_ledger(self):self.saved.pop(('u','XRPUSDT','ledger'));self.assert_safe()
 def test_failed_read_fails_closed(self):
  def bad(u,s):
   if s=='XRPUSDT':raise OSError('storage unavailable')
   return None
  r=preview(account_id='u',symbols={'XRPUSDT','BTCUSDT'},read_ledger=bad,read_owner=self.lookup('owner'),settings={'enabled':True,'steps':4,'stepPct':'3'},protected_sides={'XRPUSDT':'LONG','BTCUSDT':'LONG'},existing_skip_symbols=set())
  self.assertEqual(r['errors']['XRPUSDT'],'UNAVAILABLE')
  self.assertEqual(r['routing']['shadow_skip'],{'XRPUSDT'})
 def test_revoked_and_cross_account_blocked(self):
  self.saved[('u','XRPUSDT','owner')]['ownershipVerified']=False;self.assert_safe()
  self.saved[('u','XRPUSDT','owner')]['account']='other';self.assert_safe()
 def test_concurrent_discovery_read_only(self):
  gate=threading.Barrier(6);output=[];guard=threading.Lock()
  def worker():
   gate.wait();r=self.result()
   with guard:output.append(r['routing']['shadow_skip'])
  ts=[threading.Thread(target=worker) for _ in range(6)]
  for t in ts:t.start()
  for t in ts:t.join(5);self.assertFalse(t.is_alive())
  self.assertEqual(output,[{'XRPUSDT'}]*6)
 def test_total_absence_cannot_prove_historical_recovery(self):
  self.saved.clear()
  self.assertEqual(self.result()['suspects'],set())
 def test_normal_nonrecovery_untouched(self):self.assert_safe()
if __name__=='__main__':unittest.main()
