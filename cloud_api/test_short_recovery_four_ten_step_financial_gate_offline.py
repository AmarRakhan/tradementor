"""Fail-closed regression for the real four-step run_uid blocker.

The historical four-step fixture books funding from a caller assertion, not
an independently complete Aster funding ledger. Absence of the readback must
never authorize the next canonical CLOSE order, irrespective of prior fills.
"""
import unittest
from decimal import Decimal
from short_recovery_standalone_handoff_checkpoint_offline import stage_next_short_step_offline
from short_recovery_multidoc_mock import MultiDocDB, Ref, transactional
from short_recovery_order_claim_shadow import canonical_intent_id,pre_submit_check
from short_recovery_standalone_offline import RECOVERY


class UnverifiedFundingNeverAuthorizesNextStep(unittest.TestCase):
    def test_each_four_step_handoff_remains_non_submit_authorized(self):
        for next_step in (2,3,4):
            with self.subTest(next_step=next_step):
                self.check_step(4,next_step)
    def test_each_ten_step_handoff_remains_non_submit_authorized(self):
        for next_step in range(2,11):
            with self.subTest(next_step=next_step):
                self.check_step(10,next_step)
    def check_step(self,steps,next_step):
        db=MultiDocDB()
        refs={name:Ref(db,name) for name in
              ('selector','position','prior','next','coord','control')}
        previous=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',
                  side='SHORT',action='CLOSE',step=next_step-1)
        following=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',
                  side='SHORT',action='CLOSE',step=next_step)
        qty=Decimal(100)/Decimal(steps)
        rows={
            'selector':{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True},
            'position':{'account':'u','symbol':'XRPUSDT','cycle':'c','offlineOnly':True,
              'steps':steps,'originalShortQty':'100',
              'confirmedClosed':str(qty*(next_step-1))},
            'prior':{'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':previous,
              'side':'SHORT','action':'CLOSE','step':next_step-1,
              'offlineOrderTerminalVerified':True,
              'offlineFundingStatus':'UNRECONCILED',
              'offlineFinancialSettlement':'PENDING',
              'offlineNextClaimAuthorized':False,
              'offlineTerminalQty':str(qty),
              'offlineTerminalExecutions':[['execution',str(qty),'1','.1']]},
            'coord':{'recoveryFenceReservation':{'account':'u','symbol':'XRPUSDT',
              'cycle':'c','intentId':previous,
              'state':'RECOVERY_SUBMITTING_RECONCILE_ONLY'}},
            'control':{'account':'u','enabled':True,'emergencyStop':False,
              'closeAllActive':False}}
        for key,data in rows.items():db.commit(key,0,data)
        result=stage_next_short_step_offline(db=db,transactional=transactional,
          selector_ref=refs['selector'],position_ref=refs['position'],
          prior_claim_ref=refs['prior'],next_claim_ref=refs['next'],
          coordination_ref=refs['coord'],control_ref=refs['control'],
          account='u',symbol='XRPUSDT',cycle='c',next_step=next_step)
        self.assertEqual(result,'STAGED_WAITING_NO_SUBMIT_RIGHT')
        following_row=db.snapshot('next')[1]
        self.assertEqual(following_row['intentId'],following)
        self.assertEqual(following_row['state'],'WAIT_FINANCIAL_AUTHORIZATION')
        self.assertFalse(following_row['nextClaimAuthorized'])
        self.assertEqual(db.snapshot('coord')[1]['recoveryFenceReservation']['intentId'],previous)
        self.assertEqual(pre_submit_check(db=db,transactional=transactional,
          claim_ref=refs['next'],control_ref=refs['control'],
          coordination_ref=refs['coord'],account='u',symbol='XRPUSDT',
          cycle='c',intent_id=following,account_close_guard=lambda:None),
          'BLOCKED_CLAIM_NOT_RESERVED')
        # No mock execution or network side-effect exists in this test.
if __name__=='__main__':unittest.main()
