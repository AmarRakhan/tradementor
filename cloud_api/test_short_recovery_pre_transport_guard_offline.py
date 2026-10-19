"""Offline-only pre-transport revalidation contract for canonical Recovery submit."""
import unittest
from decimal import Decimal
from test_short_recovery_minimum_carry_claim_offline import CarryClaim
from short_recovery_order_claim_shadow import submit_once_offline
from aster_gateway import AsterOrderIntent, PositionSide


class PreTransportGuard(CarryClaim):
    def _attempt(self, guard):
        claim = self.db.snapshot('claim')[1]
        posted = []
        outcome = submit_once_offline(
            db=self.db, transactional=__import__('short_recovery_multidoc_mock').transactional,
            claim_ref=self.refs['claim'], control_ref=self.refs['control'],
            coordination_ref=self.refs['coord'], require_shared_fence=True,
            standalone_selector_ref=self.refs['selector'],
            account='u', symbol='XRPUSDT', cycle='c',
            intent=AsterOrderIntent(claim['intentId'], 'XRPUSDT', PositionSide.SHORT, Decimal('.5'), 'CLOSE'),
            account_close_guard=lambda: None,
            pre_transport_check=guard,
            submit_mock=lambda intent: posted.append(intent),
        )
        return outcome, posted

    def test_stale_inventory_fails_closed_without_post_or_retry(self):
        self.assertEqual(self.reserve(), 'MINIMUM_CARRY_RESERVED_OFFLINE')
        outcome, posted = self._attempt(lambda _: False)
        self.assertEqual(outcome, 'BLOCKED_BEFORE_TRANSPORT_RECONCILE_ONLY')
        self.assertFalse(posted)
        self.assertEqual(self.db.snapshot('claim')[1]['state'], 'SUBMITTING')
        self.assertEqual(self.db.snapshot('claim')[1]['offlineTransportOrigin'], 'BEFORE_TRANSPORT_BLOCKED')
        self.assertEqual(self._attempt(lambda _: True)[0], 'BLOCKED_CLAIM_NOT_RESERVED')

    def test_filter_failure_and_exception_fail_closed(self):
        for check in (lambda _: None, lambda _: (_ for _ in ()).throw(TimeoutError())):
            with self.subTest(check=check):
                self.setUp()
                self.assertEqual(self.reserve(), 'MINIMUM_CARRY_RESERVED_OFFLINE')
                outcome, posted = self._attempt(check)
                self.assertEqual(outcome, 'BLOCKED_BEFORE_TRANSPORT_RECONCILE_ONLY')
                self.assertFalse(posted)

    def test_fresh_pretransport_passes_once(self):
        self.assertEqual(self.reserve(), 'MINIMUM_CARRY_RESERVED_OFFLINE')
        outcome, posted = self._attempt(lambda intent: intent.quantity == Decimal('.5'))
        self.assertEqual(outcome, 'SUBMITTED_RECONCILE_ONLY')
        self.assertEqual(len(posted), 1)
        self.assertEqual(self._attempt(lambda _: True)[0], 'BLOCKED_CLAIM_NOT_RESERVED')


if __name__ == '__main__':
    unittest.main()
