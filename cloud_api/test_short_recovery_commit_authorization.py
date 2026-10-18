import unittest
from decimal import Decimal
from test_short_recovery_pair_atomic_settlement import PairAtomic
from short_recovery_order_resolution_shadow import reconcile_pair_close,resolve
from short_recovery_multidoc_mock import Ref,transactional
class CommitAuthorizationBoundary(unittest.TestCase):
 def test_authorized_pair_cannot_write_with_forged_independent_flags(self):
  h=PairAtomic('test_complete_two_sided_atomic_settlement');h.setUp()
  prior={s:h.snapshot(s) for s in ('pair','LONGclaim','SHORTclaim','LONGledger','SHORTledger')}
  rows={s:h.row(s) for s in ('LONG','SHORT')}
  result=reconcile_pair_close(db=h.db,transactional=transactional,claim_refs={s:h.refs[s+'claim'] for s in ('LONG','SHORT')},ledger_refs={s:h.refs[s+'ledger'] for s in ('LONG','SHORT')},control_ref=h.refs['control'],pair_ref=h.refs['pair'],account='u',symbol='XRPUSDT',cycle='c',readbacks=rows,authorization_mode='AUTHORIZED_EXECUTOR')
  self.assertEqual(result,'BLOCKED_INDEPENDENT_EXECUTION_AUTHORIZATION')
  self.assertEqual({s:h.snapshot(s) for s in prior},prior)
 def test_authorized_single_fill_cannot_write_even_with_forged_proof(self):
  h=PairAtomic('test_complete_two_sided_atomic_settlement');h.setUp()
  m=Ref(h.db,'authorization-marker');o=Ref(h.db,'authorization-owner')
  h.db.commit(m.key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','state':'SUSPECT'})
  h.db.commit(o.key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'})
  prior=h.snapshot('SHORTledger');claim=h.snapshot('SHORTclaim')
  evidence={'confirmed':True,'readbackVerified':True,'financialVerified':True,'fundingOwnershipVerified':True,'incomeHistoryComplete':True,'orderId':'SHORT-order','executionId':'ex','quantity':'25','realizedPnl':'1','commission':'.1','funding':'-.05'}
  result=resolve(db=h.db,transactional=transactional,claim_ref=h.refs['SHORTclaim'],ledger_ref=h.refs['SHORTledger'],marker_ref=m,owner_ref=o,account='u',symbol='XRPUSDT',cycle='c',intent_id=claim['intentId'],event='FILL',evidence=evidence,execution_id='ex',quantity=Decimal(25),authorization_mode='AUTHORIZED_EXECUTOR')
  self.assertEqual(result,'BLOCKED_INDEPENDENT_EXECUTION_AUTHORIZATION')
  self.assertEqual(h.snapshot('SHORTledger'),prior)
  self.assertEqual(h.snapshot('SHORTclaim'),claim)

class LegacyStorageIsolation(unittest.TestCase):
 def test_caller_selected_legacy_mode_rejects_unknown_storage_before_any_write(self):
  from short_recovery_mock_storage_boundary import isolated_storage_only
  from unittest.mock import MagicMock
  fake=MagicMock()
  self.assertFalse(isolated_storage_only(fake))
  result=reconcile_pair_close(db=fake,transactional=transactional,claim_refs={'LONG':fake,'SHORT':fake},ledger_refs={'LONG':fake,'SHORT':fake},control_ref=fake,pair_ref=fake,account='u',symbol='XRPUSDT',cycle='c',readbacks={'LONG':{},'SHORT':{}},authorization_mode='LEGACY_MOCK_TEST')
  self.assertEqual(result,'BLOCKED_INDEPENDENT_EXECUTION_AUTHORIZATION')
  fake.transaction.assert_not_called()
