import unittest
from decimal import Decimal as D
from short_recovery_multidoc_mock import MultiDocDB, Ref, transactional
from short_recovery_standalone_offline import (CLASSIC, RECOVERY, select_strategy_offline,
    adopt_existing_hedge_offline, preview_adopted_reduction)
from short_recovery_adoption import ExistingHedge

class StandaloneOffline(unittest.TestCase):
    def setUp(self):
        self.db = MultiDocDB()
        self.selector = Ref(self.db, ('u','strategy'))
        self.control = Ref(self.db, ('u','control'))
        self.coord = Ref(self.db, ('u','coord'))
        self.position = Ref(self.db, ('u','XRPUSDT','adopted'))
        self.db.commit(self.control.key,0,{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
        self.hedge = ExistingHedge('u','XRPUSDT','long-1','hedge-cycle-1',D(100),D(100),D(100),D(100),D(100),D(100),False,True)

    def choose(self, mode=RECOVERY):
        return select_strategy_offline(db=self.db,transactional=transactional,
            selector_ref=self.selector,control_ref=self.control,
            coordination_ref=self.coord,account='u',selected=mode)

    def adopt(self, hedge=None, steps=10, pct=2):
        return adopt_existing_hedge_offline(db=self.db,transactional=transactional,
            selector_ref=self.selector,position_ref=self.position,control_ref=self.control,
            coordination_ref=self.coord,account='u',hedge=hedge or self.hedge,
            steps=steps,step_pct=pct)

    def test_exclusive_choice_and_existing_adoption(self):
        self.assertEqual(self.adopt(),'BLOCKED_STRATEGY_NOT_SELECTED')
        self.assertEqual(self.choose(),'SELECTED_OFFLINE_PENDING_ADOPTION')
        self.assertEqual(self.choose(),'ALREADY_SELECTED_OFFLINE')
        self.assertEqual(self.adopt(),'ADOPTED_OFFLINE')
        self.assertEqual(self.adopt(),'BLOCKED_ALREADY_OWNED')
        self.assertEqual(self.db.snapshot(self.position.key)[1]['anchor'],'100')
        self.assertEqual(self.db.snapshot(self.position.key)[1]['originalShortQty'],'100')
        for step in range(1,11):
            # Independently simulate confirmed fills in the offline state fixture.
            p = self.db.snapshot(self.position.key)[1]
            self.db.commit(self.position.key,self.db.snapshot(self.position.key)[0],{**p,'confirmedClosed':str((step-1)*10)})
            result = preview_adopted_reduction(db=self.db,selector_ref=self.selector,
                position_ref=self.position,account='u',mark=100-step*2)
            self.assertEqual(result['due_qty'],D(10))

    def test_recovery_preview_rejects_nonoffline_selector_or_position(self):
        self.assertEqual(self.choose(), 'SELECTED_OFFLINE_PENDING_ADOPTION')
        self.assertEqual(self.adopt(), 'ADOPTED_OFFLINE')
        args=dict(db=self.db,selector_ref=self.selector,position_ref=self.position,
                  account='u',mark=98)
        self.assertEqual(preview_adopted_reduction(**args)['due_qty'],D(10))
        for key,ref in (('selector',self.selector),('position',self.position)):
            for invalid in (False,None,'true'):
                with self.subTest(key=key,invalid=invalid):
                    version,row=self.db.snapshot(ref.key)
                    self.db.commit(ref.key,version,{**row,'offlineOnly':invalid})
                    self.assertEqual(preview_adopted_reduction(**args)['status'],
                                     'BLOCKED_STRATEGY_OR_ADOPTION')
                    version,_=self.db.snapshot(ref.key)
                    self.db.commit(ref.key,version,row)

    def test_classic_is_unmodified_and_blocks_recovery(self):
        self.assertEqual(self.choose(CLASSIC),'SELECTED_CLASSIC_OFFLINE')
        self.assertEqual(self.adopt(),'BLOCKED_STRATEGY_NOT_SELECTED')
        self.assertEqual(preview_adopted_reduction(db=self.db,selector_ref=self.selector,
            position_ref=self.position,account='u',mark=98)['status'],'BLOCKED_STRATEGY_OR_ADOPTION')

    def test_pending_anchor_inventory_and_scope_fail_closed(self):
        self.assertEqual(self.choose(),'SELECTED_OFFLINE_PENDING_ADOPTION')
        from dataclasses import replace
        self.assertEqual(self.adopt(replace(self.hedge,confirmed_hedge_entry_price=D(0))),'BLOCKED_QUANTITY_OR_PRICE')
        self.assertEqual(self.adopt(replace(self.hedge,exchange_short_qty=D(75))),'BLOCKED_EXCHANGE_MISMATCH')
        self.assertEqual(self.adopt(replace(self.hedge,pending_orders=True)),'BLOCKED_PENDING')
        self.assertEqual(self.adopt(replace(self.hedge,account='other')),'BLOCKED_ACCOUNT_SCOPE')
        self.assertIsNone(self.db.snapshot(self.position.key)[1])

    def test_stop_and_fenced_switch_rejected(self):
        self.db.commit(self.coord.key,0,{'recoveryFenceReservation':{'intentId':'in-flight'}})
        self.assertEqual(self.choose(),'BLOCKED_INFLIGHT_COORDINATION')
        v,_=self.db.snapshot(self.coord.key)
        self.db.commit(self.coord.key,v,{})
        self.assertEqual(self.choose(),'SELECTED_OFFLINE_PENDING_ADOPTION')
        self.db.commit(self.coord.key,v+1,{'lease':{'token':'stale-or-active'}})
        self.assertEqual(self.adopt(),'BLOCKED_INFLIGHT_COORDINATION')
        self.db.commit(self.control.key,1,{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
        self.assertEqual(self.adopt(),'BLOCKED_CONTROL')

    def test_restart_replay_does_not_double_adopt(self):
        self.assertEqual(self.choose(),'SELECTED_OFFLINE_PENDING_ADOPTION')
        self.assertEqual(self.adopt(),'ADOPTED_OFFLINE')
        restored=self.db.restart()
        self.db=restored
        self.selector=Ref(restored,self.selector.key)
        self.position=Ref(restored,self.position.key)
        self.control=Ref(restored,self.control.key)
        self.coord=Ref(restored,self.coord.key)
        self.assertEqual(self.adopt(),'BLOCKED_ALREADY_OWNED')

if __name__=='__main__': unittest.main()
