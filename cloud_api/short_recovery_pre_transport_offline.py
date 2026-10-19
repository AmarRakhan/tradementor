"""Fresh offline exchange pre-transport gate; injected mocks only, never network."""
from decimal import Decimal, InvalidOperation
from short_recovery_inventory_preflight import refresh_mock_aster_inventory, check_inventory


def fresh_mock_pre_transport_check(*, client, account, symbol, now_ms, expected_cycle=None):
    """Return a callback to be executed AFTER transactional order reservation.

    The mock supplies current instrument filters, a fresh executable price and
    fresh account/position/open-order readbacks. No cached preview is trusted.
    """
    def check(intent):
        if getattr(client, 'offline_mock_only', False) is not True:
            return False
        try:
            inventory = refresh_mock_aster_inventory(client=client, account=account,
                                                       symbol=symbol, now_ms=now_ms())
            if check_inventory(intents=[intent], symbol=symbol, readback=inventory,
                               account=account, now_ms=now_ms()) != 'INVENTORY_VERIFIED':
                return False
            f = client.exchange_filters(symbol)
            price = Decimal(str(client.executable_price(symbol)))
            if not isinstance(f, dict) or f.get('symbol') != symbol:
                return False
            qty = Decimal(str(intent.quantity))
            min_qty = Decimal(str(f['minimumQty']))
            step = Decimal(str(f['quantityStep']))
            min_notional = Decimal(str(f['minimumNotional']))
            if not all(x.is_finite() for x in (qty, min_qty, step, min_notional, price)):
                return False
            if qty <= 0 or min_qty <= 0 or step <= 0 or min_notional <= 0 or price <= 0:
                return False
            if qty < min_qty or qty % step != 0 or qty * price < min_notional:
                return False
            return True
        except (Exception,):
            return False
    return check
