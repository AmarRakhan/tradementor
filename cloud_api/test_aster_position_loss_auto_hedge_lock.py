from __future__ import annotations

import pytest
from pathlib import Path

from aster_position_loss_auto_hedge_lock import (
    AutoHedgeCloseBlocked,
    auto_hedge_symbol_managed,
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


def test_main_routes_all_ordinary_live_closes_through_auto_hedge_guard_but_close_all_bypasses():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    assert "configure_auto_hedge_lock_reader(" in source
    assert "before_order_submit=(None if emergency_close_all else _block_order_during_close_all(uid))" in source
    assert "_portfolio_growth_client(user,live=True,emergency_close_all=True)" in source
    assert "allow_auto_hedge_locked:bool=False" in source
    extension = Path(__file__).with_name("aster_position_loss_auto_hedge_extension.py").read_text(encoding="utf-8")
    assert "_block_order_during_close_all(uid, allow_auto_hedge_locked=True)" in extension


def test_bulk_profit_managed_symbol_guard_protects_entire_pair_lifecycle():
    for status in ("HEDGING", "HEDGED", "ADJUSTING", "RECOVERY", "REHEDGE_ARMED", "DISABLED", "ERROR"):
        configure_auto_hedge_lock_reader(lambda uid, symbol, status=status: locked(status=status))
        assert auto_hedge_symbol_managed(account_uid="u1", symbol="DOGEUSDT") is True

    configure_auto_hedge_lock_reader(lambda uid, symbol: locked(status="CLOSED"))
    assert auto_hedge_symbol_managed(account_uid="u1", symbol="DOGEUSDT") is False
    configure_auto_hedge_lock_reader(lambda uid, symbol: {})
    assert auto_hedge_symbol_managed(account_uid="u1", symbol="DOGEUSDT") is False


def test_bulk_profit_managed_symbol_guard_fails_closed_when_state_unavailable():
    def broken(uid, symbol):
        raise RuntimeError("firestore unavailable")

    configure_auto_hedge_lock_reader(broken)
    with pytest.raises(AutoHedgeCloseBlocked, match="niet betrouwbaar"):
        auto_hedge_symbol_managed(account_uid="u1", symbol="DOGEUSDT")
