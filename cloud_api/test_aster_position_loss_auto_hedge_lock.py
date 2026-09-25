from __future__ import annotations

import pytest

from aster_position_loss_auto_hedge_lock import (
    AutoHedgeCloseBlocked,
    configure_auto_hedge_lock_reader,
    require_auto_hedge_close_allowed,
)


@pytest.fixture(autouse=True)
def reset_reader():
    configure_auto_hedge_lock_reader(None)
    yield
    configure_auto_hedge_lock_reader(None)


def locked(**changes):
    value = {
        "status": "HEDGED",
        "hedgeSide": "LONG",
        "generationId": "g7",
        "reservedHedgeQty": 627.0,
        "currentHedgeQty": 921.0,
        "normalFreeQty": 294.0,
    }
    value.update(changes)
    return value


def test_normal_free_quantity_can_close_without_consuming_lock():
    configure_auto_hedge_lock_reader(lambda uid, symbol: locked())
    require_auto_hedge_close_allowed(
        account_uid="u1", symbol="DOGEUSDT", side="LONG",
        quantity=294, caller="profit-sweep",
    )


def test_close_that_would_consume_reserved_hedge_is_blocked():
    configure_auto_hedge_lock_reader(lambda uid, symbol: locked())
    events = []
    with pytest.raises(AutoHedgeCloseBlocked):
        require_auto_hedge_close_allowed(
            account_uid="u1", symbol="DOGEUSDT", side="LONG",
            quantity=300, caller="profit-sweep", audit=events.append,
        )
    assert events[0]["reservedHedgeQty"] == pytest.approx(627)
    assert events[0]["normalFreeQty"] == pytest.approx(294)
    assert events[0]["pairCycleId"] == "g7"


def test_protected_side_is_not_the_reserved_hedge_side():
    configure_auto_hedge_lock_reader(lambda uid, symbol: locked())
    require_auto_hedge_close_allowed(
        account_uid="u1", symbol="DOGEUSDT", side="SHORT",
        quantity=921, caller="protected-tp",
    )


def test_recovery_has_no_hedge_lock():
    configure_auto_hedge_lock_reader(
        lambda uid, symbol: locked(status="RECOVERY", reservedHedgeQty=0, normalFreeQty=921)
    )
    require_auto_hedge_close_allowed(
        account_uid="u1", symbol="DOGEUSDT", side="LONG",
        quantity=921, caller="recovery-tp",
    )


def test_adjusting_pair_remains_locked():
    configure_auto_hedge_lock_reader(lambda uid, symbol: locked(status="ADJUSTING"))
    with pytest.raises(AutoHedgeCloseBlocked):
        require_auto_hedge_close_allowed(
            account_uid="u1", symbol="DOGEUSDT", side="LONG",
            quantity=921, caller="strategy-tp",
        )


def test_configured_reader_failure_fails_closed():
    def broken(uid, symbol):
        raise RuntimeError("firestore unavailable")

    configure_auto_hedge_lock_reader(broken)
    with pytest.raises(AutoHedgeCloseBlocked, match="niet betrouwbaar"):
        require_auto_hedge_close_allowed(
            account_uid="u1", symbol="DOGEUSDT", side="LONG",
            quantity=1, caller="strategy-tp",
        )
