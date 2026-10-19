"""Combined 4/10-step mock-only carry and pretransport failure matrix."""
import unittest
from test_short_recovery_fresh_pretransport_integration_offline import FreshGateIntegration
from test_short_recovery_continuous_cycle_offline import ContinuousRecoveryCycle


class CombinedFilterCycleSafety(FreshGateIntegration):
    def test_both_cycle_configs_carry_then_changed_filters_block_replay(self):
        for steps,mark,expected in ((4,'90','0.5'),(10,'85','0.3')):
            for change,value in (('notional','80'),('minimum','0.8'),('step','0.4'),('price','0')):
                with self.subTest(steps=steps,change=change):
                    self.setUp()
                    self.put('position',{**self.db.snapshot('position')[1],'steps':steps})
                    self.assertEqual(self.reserve(mark=mark),'MINIMUM_CARRY_RESERVED_OFFLINE')
                    qty=self.db.snapshot('claim')[1]['minimumCarryQuantity']
                    self.assertEqual(qty,expected)
                    setattr(self.client,change,value)
                    claim=self.db.snapshot('claim')[1]
                    from short_recovery_order_claim_shadow import submit_once_offline
                    from short_recovery_multidoc_mock import transactional
                    from short_recovery_pre_transport_offline import fresh_mock_pre_transport_check
                    from aster_gateway import AsterOrderIntent,PositionSide
                    from decimal import Decimal
                    posted=[]
                    intent=AsterOrderIntent(claim['intentId'],'XRPUSDT',PositionSide.SHORT,Decimal(qty),'CLOSE')
                    kw=dict(db=self.db,transactional=transactional,claim_ref=self.refs['claim'],
                        control_ref=self.refs['control'],coordination_ref=self.refs['coord'],
                        require_shared_fence=True,standalone_selector_ref=self.refs['selector'],
                        account='u',symbol='XRPUSDT',cycle='c',intent=intent,
                        account_close_guard=lambda:None,submit_mock=lambda i:posted.append(i),
                        pre_transport_check=fresh_mock_pre_transport_check(client=self.client,
                            account='u',symbol='XRPUSDT',now_ms=lambda:self.clock))
                    self.assertEqual(submit_once_offline(**kw),'BLOCKED_BEFORE_TRANSPORT_RECONCILE_ONLY')
                    self.assertFalse(posted)
                    self.assertEqual(submit_once_offline(**kw),'BLOCKED_CLAIM_NOT_RESERVED')

    def test_four_and_ten_cycle_rehedge_remains_separate_from_financial_finality(self):
        for steps in (4,10):
            with self.subTest(steps=steps):
                ContinuousRecoveryCycle().check_cycle(steps)
