from pathlib import Path

from aster_strategy2_runtime import isolate_unproven_ownership
from aster_strategy2_state import OwnedLeg


ROOT = Path(__file__).resolve().parent
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def _leg(symbol: str, side: str) -> OwnedLeg:
    return OwnedLeg("aster-strategy-2", "strategy2", symbol, side, f"{symbol}-{side}", 1, 1, 10)


def _position(symbol: str, side: str) -> dict:
    return {"symbol": symbol, "positionSide": side, "positionAmt": "1", "entryPrice": "10", "markPrice": "11"}


def test_exchange_only_position_is_never_claimed_and_stored_only_leg_is_quarantined():
    btc = _leg("BTCUSDT", "LONG")
    stored_only = _leg("OLDUSDT", "SHORT")
    proven, exchange_only, stored_only_keys = isolate_unproven_ownership(
        persisted=[btc, stored_only],
        positions=[_position("BTCUSDT", "LONG"), _position("MANUALUSDT", "SHORT")],
    )
    assert [(leg.symbol, leg.side) for leg in proven] == [("BTCUSDT", "LONG")]
    assert exchange_only == {("MANUALUSDT", "SHORT")}
    assert stored_only_keys == {("OLDUSDT", "SHORT")}


def test_exact_symbol_and_side_are_required_for_proven_ownership():
    proven, exchange_only, stored_only = isolate_unproven_ownership(
        persisted=[_leg("BTCUSDT", "LONG")],
        positions=[_position("BTCUSDT", "SHORT")],
    )
    assert proven == []
    assert exchange_only == {("BTCUSDT", "SHORT")}
    assert stored_only == {("BTCUSDT", "LONG")}


def test_account_tick_keeps_only_risk_reducing_management_during_mismatch():
    start = MAIN.index("def _run_aster_strategy2_tick")
    end = MAIN.index("def aster_automation_public", start)
    tick = MAIN[start:end]
    assert "proven_owned,_,stored_only_s2=isolate_unproven_ownership" in tick
    assert "if missing or transfer_errors or len(transferred)!=len(active_keys)" not in tick
    assert "if transfer_errors:" in tick
    assert "if ownership_isolated and selected and not selected[1].risk_reducing" in tick
    assert "if not ownership_isolated and not protection_selected and not take_profit_selected and pending_reopens" in tick
    assert 'return {"status":"ownership-isolated","action":"HOLD"' in tick


def test_ownership_isolation_never_relaxes_queue_or_leverage_guards():
    queue = (ROOT / "aster_strategy2_queue.py").read_text(encoding="utf-8")
    assert "MAX_ORDERS_PER_ACCOUNT_SCAN = 15" in queue
    assert "new_position_leverage=settings.leverage" in MAIN
    assert "configure_maximum_usable_leverage" in MAIN
