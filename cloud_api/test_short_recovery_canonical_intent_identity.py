import unittest
from short_recovery_order_claim_shadow import canonical_intent_id, reserve, pre_submit_check
from test_short_recovery_build47_order_claim import Tests as ClaimTest
from short_recovery_multidoc_mock import transactional

class CanonicalIntentIdentity(unittest.TestCase):
 def setUp(self):
  self.h=ClaimTest('test_same_intent_idempotent');self.h.setUp()
  self.kw=dict(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1)
  self.i=canonical_intent_id(**self.kw)
 def test_unique_across_scope_and_stable_restart(self):
  self.assertEqual(self.i,canonical_intent_id(**self.kw))
  self.assertNotEqual(self.i,canonical_intent_id(**(self.kw|{'step':2})))
  self.assertNotEqual(self.i,canonical_intent_id(**(self.kw|{'side':'LONG'})))
  self.assertNotEqual(self.i,canonical_intent_id(**(self.kw|{'action':'OPEN'})))
  self.assertNotEqual(self.i,canonical_intent_id(**(self.kw|{'account':'other'})))
 def test_persisted_claim_and_stale_no_retry(self):
  h=self.h;r=h.refs
  def claim(i,step):return reserve(db=h.db,transactional=transactional,marker_ref=r['marker'],owner_ref=r['owner'],ledger_ref=r['ledger'],claim_ref=r['claim'],control_ref=r['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id=i,side='SHORT',action='CLOSE',step=step,now=2)
  self.assertEqual(claim(self.i,1),'RESERVED_SHADOW')
  self.assertEqual(h.db.snapshot(h.keys['claim'])[1]['intentId'],self.i)
  self.assertEqual(claim(self.i,1),'ALREADY_RESERVED')
  self.assertEqual(claim(canonical_intent_id(**(self.kw|{'step':2})),2),'BLOCKED_UNRESOLVED_CLAIM')
  self.assertEqual(claim('forged',1),'BLOCKED_INTENT_ID')
 def test_wrong_side_cannot_claim(self):
  h=self.h;r=h.refs
  self.assertEqual(reserve(db=h.db,transactional=transactional,marker_ref=r['marker'],owner_ref=r['owner'],ledger_ref=r['ledger'],claim_ref=r['claim'],control_ref=r['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id=self.i,side='LONG',action='CLOSE',step=1,now=2),'BLOCKED_INTENT_ID')
