"""Offline canonical claim handling never treats duplicate reservations as stop bypass."""
import unittest
from short_recovery_order_claim_shadow import reserve
from short_recovery_multidoc_mock import transactional
from test_short_recovery_build48_settlement import Tests as Fixture
class ClaimStopReuse(unittest.TestCase):
 def test_same_intent_after_stop_does_not_get_already_reserved(self):
  h=Fixture('test_no_order_reconciled_terminal');h.setUp()
  def reserve_again():
   r=h.refs
   return reserve(db=h.db,transactional=transactional,marker_ref=r['marker'],owner_ref=r['owner'],ledger_ref=r['ledger'],claim_ref=r['claim'],control_ref=r['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id='intent',now=3)
  self.assertEqual(reserve_again(),'ALREADY_RESERVED')
  for changes in ({'enabled':False},{'emergencyStop':True},{'closeAllActive':True}):
   v,record=h.db.snapshot(h.keys['control'])
   h.db.commit(h.keys['control'],v,{**record,**changes})
   self.assertEqual(reserve_again(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
   v,record=h.db.snapshot(h.keys['control'])
   h.db.commit(h.keys['control'],v,{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
 def test_other_intent_still_unresolved(self):
  h=Fixture('test_no_order_reconciled_terminal');h.setUp();r=h.refs
  self.assertEqual(reserve(db=h.db,transactional=transactional,marker_ref=r['marker'],owner_ref=r['owner'],ledger_ref=r['ledger'],claim_ref=r['claim'],control_ref=r['control'],account='u',symbol='XRPUSDT',cycle='c',intent_id='another',now=2),'BLOCKED_UNRESOLVED_CLAIM')
