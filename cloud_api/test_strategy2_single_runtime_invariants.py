from pathlib import Path

from aster_strategy2 import Strategy2Config
from aster_strategy2_runtime import (
    entry_order_limit, queued_entry_order_limit, transfer_active_ownership_to_strategy2,
)
from aster_strategy2_state import OwnedLeg

ROOT = Path(__file__).resolve().parent
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")

def legs(count: int):
    result=[]
    for i in range(count):
        side="LONG" if i % 2 == 0 else "SHORT"
        result.append(OwnedLeg("aster-strategy-2","strategy2",f"S{i}USDT",side,f"c{i}",1,1,100))
    return result

def test_72_of_100_exposes_28_missing_and_first_scan_caps_at_15():
    owned=legs(72)
    assert entry_order_limit(True,owned,100)==28
    assert queued_entry_order_limit(True,owned,100,orders_used=0,maximum_orders=15)==15

def test_next_scan_continues_remaining_13_after_fifteen_confirmed_entries():
    owned=legs(87)
    assert entry_order_limit(True,owned,100)==13
    assert queued_entry_order_limit(True,owned,100,orders_used=0,maximum_orders=15)==13

def test_legacy_strategy3_owner_normalizes_to_strategy2_without_order_action():
    legacy=OwnedLeg("aster-strategy-3","strategy3","BTCUSDT","LONG","legacy",7,2,100)
    positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"2","entryPrice":"100"}]
    transferred,missing,errors=transfer_active_ownership_to_strategy2(
        positions=positions,strategy2_legs=[],strategy3_legs=[legacy],strategy1_legs=[])
    assert not missing and not errors and len(transferred)==1
    assert transferred[0].strategy_id=="aster-strategy-2"
    assert transferred[0].engine_type=="strategy2"
    assert transferred[0].symbol=="BTCUSDT" and transferred[0].side=="LONG"

def test_strategy3_conflict_text_is_impossible_in_strategy2_tick():
    tick=MAIN[MAIN.index("def _run_aster_strategy2_tick"):MAIN.index("def _aster_brackets")]
    assert "botst met Strategy 3" not in tick
    assert "LEGACY_OWNERSHIP_NORMALIZED_TO_STRATEGY2" in tick
    assert "RECOVERY_ISOLATED_FROM_SEAT_REFILL" in tick

def test_candidate_failure_paths_continue_scanning():
    tick=MAIN[MAIN.index("def _run_aster_strategy2_tick"):MAIN.index("def _aster_brackets")]
    candidate=tick[tick.index("for candidate in candidates"):tick.index("if not plan or opened is None:break")]
    assert "NewPositionLeverageBlocked" in candidate
    assert "ENTRY_CANDIDATE_REJECTED" in candidate
    assert "ENTRY_CANDIDATE_VALIDATION_SKIPPED" in candidate
    assert candidate.count("continue") >= 4

def test_seat_refill_is_not_stopped_by_accountwide_emergency_or_local_zero_order_management():
    from aster_strategy2_runtime import scanner_allowed
    from aster_strategy2 import PortfolioState
    cfg=Strategy2Config(base_notional=10,leverage=10,maximum_pairs=100)
    emergency=PortfolioState(1000,1000,.99,0,0,0,available_balance=100)
    assert scanner_allowed(cfg,emergency,legs(72)) is True
    queue=MAIN[MAIN.index("def _run_aster_strategy2_queue_scan"):MAIN.index('@app.post("/internal/mexc-automation/tick")')]
    assert 'retryable_zero_order=' in queue
    for action in ("DCA_BLOCKED_MINIMUM","PROTECTION_BUDGET_SKIPPED","CLOSE_BLOCKED_NET_NON_POSITIVE","RISK_BLOCKED","MANAGEMENT_SKIPPED"):
        assert action in queue
    tick=MAIN[MAIN.index("def _run_aster_strategy2_tick"):MAIN.index("def _aster_brackets")]
    risk=tick[tick.index("except Strategy2RiskBlocked"):tick.index("except Exception as exc", tick.index("except Strategy2RiskBlocked"))]
    assert 'blockedManagementActions' in risk and 'retryAfterSeconds' in risk
    assert 'seat_shortage=len(owned)<settings.maximum_pairs' in tick
    assert 'protection_selected=(None if seat_shortage else portfolio_protection_decision' in tick
    assert 'if seat_shortage:' in tick and 'selected=take_profit_selected' in tick

def test_same_symbol_long_and_short_are_distinct_active_keys():
    cfg=Strategy2Config(maximum_pairs=2)
    positions=[
        {"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100"},
        {"symbol":"BTCUSDT","positionSide":"SHORT","positionAmt":"1","entryPrice":"101"},
    ]
    s2=[OwnedLeg("aster-strategy-2","strategy2","BTCUSDT","LONG","l",1,1,100),
        OwnedLeg("aster-strategy-2","strategy2","BTCUSDT","SHORT","s",1,1,101)]
    transferred,missing,errors=transfer_active_ownership_to_strategy2(positions=positions,strategy2_legs=s2)
    assert not missing and not errors and len(transferred)==cfg.maximum_pairs


def test_queue_lease_outlives_cloud_scheduler_request_and_scan_has_wall_clock_budget():
    source=MAIN
    assert 'orderQueueLease":{"token":token,"until":now+timedelta(minutes=10)' in source
    tick=source[source.index('def _run_aster_strategy2_queue_scan'):source.index('@app.post("/internal/mexc-automation/tick")')]
    assert 'scan_deadline=time.monotonic()+120' in tick
    assert 'if time.monotonic()>=scan_deadline:' in tick
    assert 'volgende minuut gaat verder' in tick
    assert 'token_hex(4)' in tick

def test_queue_scan_completion_always_advances_visible_server_check_time():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    start = source.index("def _run_aster_strategy2_queue_scan")
    end = source.index('@app.post("/internal/mexc-automation/tick")', start)
    queue = source[start:end]
    assert '"lastTickAt":completed_at' in queue
    assert '"queueLastCompletedAt":completed_at' in queue
    assert '"updatedAt":completed_at' in queue
