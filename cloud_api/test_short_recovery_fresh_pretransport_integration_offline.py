"""End-to-end mock inventory/filter gate via existing canonical submit CAS."""
from decimal import Decimal as D
from test_short_recovery_pre_transport_guard_offline import PreTransportGuard
from short_recovery_pre_transport_offline import fresh_mock_pre_transport_check
from test_short_recovery_mock_aster_inventory import Client


class FreshGateIntegration(PreTransportGuard):
    def setUp(self):
        super().setUp()
        self.client=Client()
        self.client.qty='1'
        self.client.minimum='0.01'
        self.client.step='0.01'
        self.client.notional='30'
        self.client.price='100'
        self.client.exchange_filters=lambda symbol: {
            'symbol':symbol,'minimumQty':self.client.minimum,
            'quantityStep':self.client.step,'minimumNotional':self.client.notional}
        self.client.executable_price=lambda symbol:self.client.price
        self.clock=10000

    def run_gate(self):
        return self._attempt(fresh_mock_pre_transport_check(client=self.client,
            account='u',symbol='XRPUSDT',now_ms=lambda:self.clock))

    def test_fresh_valid_inventory_and_filters_posts_once(self):
        self.assertEqual(self.reserve(),'MINIMUM_CARRY_RESERVED_OFFLINE')
        status,posts=self.run_gate()
        self.assertEqual(status,'SUBMITTED_RECONCILE_ONLY')
        self.assertEqual(len(posts),1)
        self.assertEqual(self.run_gate()[0],'BLOCKED_CLAIM_NOT_RESERVED')

    def test_changed_exchange_inventory_no_post(self):
        self.assertEqual(self.reserve(),'MINIMUM_CARRY_RESERVED_OFFLINE')
        self.client.qty='0.1'
        self.assertEqual(self.run_gate()[0],'BLOCKED_BEFORE_TRANSPORT_RECONCILE_ONLY')

    def test_minimum_quantity_step_notional_price_fail_closed(self):
        for field,value in [('minimum','0.6'),('step','0.3'),('notional','60'),
                            ('price','0'),('minimum','NaN'),('step','0')]:
            with self.subTest(field=field,value=value):
                self.setUp()
                self.assertEqual(self.reserve(),'MINIMUM_CARRY_RESERVED_OFFLINE')
                setattr(self.client,field,value)
                status,posts=self.run_gate()
                self.assertEqual(status,'BLOCKED_BEFORE_TRANSPORT_RECONCILE_ONLY')
                self.assertFalse(posts)
                self.assertEqual(self.run_gate()[0],'BLOCKED_CLAIM_NOT_RESERVED')

    def test_open_orders_and_api_failure_block(self):
        for failure in ('open','exception'):
            with self.subTest(failure=failure):
                self.setUp()
                self.assertEqual(self.reserve(),'MINIMUM_CARRY_RESERVED_OFFLINE')
                if failure=='open':self.client.orders=[{'orderId':'pending'}]
                else:self.client.exchange_filters=lambda symbol: (_ for _ in ()).throw(TimeoutError())
                self.assertEqual(self.run_gate()[0],'BLOCKED_BEFORE_TRANSPORT_RECONCILE_ONLY')

    def test_missing_pretransport_callback_blocks_carry_order(self):
        self.assertEqual(self.reserve(),'MINIMUM_CARRY_RESERVED_OFFLINE')
        self.assertEqual(self._attempt(None)[0], 'BLOCKED_BEFORE_TRANSPORT_RECONCILE_ONLY')
        self.assertEqual(self.run_gate()[0], 'BLOCKED_CLAIM_NOT_RESERVED')
