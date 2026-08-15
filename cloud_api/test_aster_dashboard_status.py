from datetime import datetime, timedelta, timezone
from dataclasses import replace

from aster_dashboard_status import build_aster_dashboard_status
from aster_strategy2 import Strategy2Config
from aster_strategy3 import Strategy3Config
from pathlib import Path


NOW = datetime(2026, 8, 15, 0, 0, tzinfo=timezone.utc)


def leg(strategy: int, symbol: str, side: str) -> dict:
    return {"strategy_id": f"aster-strategy-{strategy}", "engine_type": f"strategy{strategy}",
            "symbol": symbol, "side": side}


def position(symbol: str, side: str) -> dict:
    return {"symbol": symbol, "side": side, "quantity": 1, "notionalUsd": 10}


def contract(*, positions=None, s2=None, s3=None, maximum=200, now=NOW, snapshot=None,
             gates=None, strategy2_config=None):
    positions = [position("BTCUSDT", "LONG")] if positions is None else positions
    account = {"capturedAt": now, "activePositions": len(positions), "positions": positions,
               "openOrders": 0, "marginRatio": .10}
    account.update(snapshot or {})
    state2 = {"enabled": False, "monitor": False, "phase": "STOPPED", "ownedLegs": [], "lastTickAt": now}
    state2.update(s2 or {})
    state3 = {"enabled": True, "monitor": True, "phase": "RUNNING", "canaryValidated": True,
              "liveReady": True, "lastTickAt": now, "lastReason": "Geen veilige actie nodig",
              "ownedLegs": [leg(3, row["symbol"], row["side"]) for row in positions],
              "accountSnapshot": {"equity": 1000, "marginRatio": .10, "strategyMargin": 10},
              "universe": {"entryBlocked": False, "selectedSymbols": ["BTCUSDT", "ETHUSDT"]}}
    state3.update(s3 or {})
    gates = gates or {"asterLiveExecution": True, "strategy2Live": False, "strategy2Runtime": False,
                      "strategy3Live": True, "strategy3Runtime": True}
    return build_aster_dashboard_status(snapshot=account, strategy2_state=state2, strategy3_state=state3,
        strategy2_config=strategy2_config or Strategy2Config(),
        strategy3_config=replace(Strategy3Config(), mode="live", maximum_positions=maximum),
        runtime_gates=gates, evaluated_at=now)


def test_strategy3_proven_live_and_healthy():
    value = contract()
    assert value["strategy3"]["status"] == "LIVE"
    assert value["newEntry"]["status"] == "ALLOWED"


def test_strategy3_disabled_is_blocked():
    value = contract(s3={"enabled": False})
    assert value["strategy3"]["status"] == "STOPPED"
    assert value["newEntry"]["reasonCode"] == "STRATEGY_DISABLED"


def test_strategy2_entries_are_independent_when_strategy3_is_off():
    positions = [position("ETHUSDT", "SHORT")]
    value = contract(
        positions=positions,
        s2={
            "enabled": True, "monitor": True, "phase": "RUNNING", "canaryValidated": True,
            "liveReady": True, "ownedLegs": [leg(2, "ETHUSDT", "SHORT")],
            "accountSnapshot": {"equity": 1000, "highWaterMark": 1000, "marginRatio": .10,
                                "strategyMargin": 1},
            "universe": {"entryBlocked": False, "selectedSymbols": ["ETHUSDT", "BTCUSDT"]},
        },
        s3={"enabled": False, "monitor": False, "phase": "STOPPED", "ownedLegs": []},
        gates={"asterLiveExecution": True, "strategy2Live": True, "strategy2Runtime": True,
               "strategy3Live": False, "strategy3Runtime": False},
        strategy2_config=replace(Strategy2Config(), mode="live", maximum_pairs=100),
    )
    assert value["strategy2"]["status"] == "LIVE"
    assert value["strategy3"]["status"] == "STOPPED"
    assert value["strategy2NewEntry"]["status"] == "ALLOWED"
    assert value["strategy2NewEntry"]["strategyId"] == "aster-strategy-2"
    assert value["strategy2NewEntry"]["reasonCode"] == "ALL_STRATEGY2_CHECKS_PASSED"
    assert value["strategy2"]["targetPositions"] == 100
    assert value["strategy2"]["activeTargetPositions"] == 1
    assert value["strategy2"]["remainingToTarget"] == 99
    assert value["newEntry"]["reasonCode"] == "STRATEGY_DISABLED"


def test_strategy2_entry_reason_never_uses_strategy3_switch():
    value = contract(
        positions=[],
        s2={"enabled": False, "monitor": False},
        s3={"enabled": False, "monitor": False},
        gates={"asterLiveExecution": True, "strategy2Live": True, "strategy2Runtime": True,
               "strategy3Live": False, "strategy3Runtime": False},
        strategy2_config=replace(Strategy2Config(), mode="live"),
    )
    assert value["strategy2NewEntry"]["reasonCode"] == "STRATEGY2_ENABLED"
    assert value["strategy2NewEntry"]["reasonText"] == "Strategy 2 staat uit"


def test_strategy2_and_strategy3_counts_are_separate_from_account_total():
    positions = [position("BTCUSDT", "LONG"), position("ETHUSDT", "SHORT"), position("SOLUSDT", "LONG")]
    value = contract(positions=positions, s2={"ownedLegs": [leg(2, "BTCUSDT", "LONG")]},
                     s3={"ownedLegs": [leg(3, "ETHUSDT", "SHORT"), leg(3, "SOLUSDT", "LONG")]})
    assert value["account"]["activePositions"] == 3
    assert value["strategy2"]["ownedPositions"] == 1
    assert value["strategy3"]["ownedPositions"] == 2


def test_stopped_strategy2_positions_still_count_account_wide():
    positions = [position("BTCUSDT", "LONG"), position("ETHUSDT", "SHORT")]
    value = contract(positions=positions, maximum=3, s2={"ownedLegs": [leg(2, "BTCUSDT", "LONG")]},
                     s3={"ownedLegs": [leg(3, "ETHUSDT", "SHORT")]})
    assert value["strategy2"]["status"] == "STOPPED"
    assert value["strategy3"]["remainingAccountCapacity"] == 1


def test_92_of_200_leaves_108_account_slots():
    positions = [position(f"COIN{i}USDT", "LONG" if i % 2 == 0 else "SHORT") for i in range(92)]
    value = contract(positions=positions, maximum=200,
        s3={"ownedLegs": [leg(3, row["symbol"], row["side"]) for row in positions],
            "universe": {"entryBlocked": False, "selectedSymbols": ["FREEUSDT"]}})
    assert value["strategy3"]["remainingAccountCapacity"] == 108
    assert value["account"]["longPositions"] == 46 and value["account"]["shortPositions"] == 46


def test_account_limit_reached():
    value = contract(maximum=1)
    assert value["newEntry"]["reasonCode"] == "ACCOUNT_POSITION_LIMIT"


def test_strategy_budget_reached():
    value = contract(s3={"accountSnapshot": {"equity": 100, "marginRatio": .1, "strategyMargin": 35}})
    assert value["newEntry"]["reasonCode"] == "STRATEGY_BUDGET_LIMIT"


def test_margin_ratio_above_configured_boundary():
    value = contract(s3={"accountSnapshot": {"equity": 100, "marginRatio": .51, "strategyMargin": 1}})
    assert value["newEntry"]["reasonCode"] == "MARGIN_RATIO_LIMIT"


def test_management_action_has_waiting_priority():
    value = contract(s3={"lastAction": "FULL_TP", "lastActionAt": NOW})
    assert value["newEntry"]["status"] == "WAITING"
    assert value["newEntry"]["reasonCode"] == "MANAGEMENT_ACTION_PRIORITY"


def test_open_order_waits_for_reconciliation():
    value = contract(snapshot={"openOrders": 1})
    assert value["newEntry"]["status"] == "WAITING"
    assert value["newEntry"]["reasonCode"] == "OPEN_ORDER_RECONCILIATION"


def test_ownership_conflict_blocks():
    value = contract(s2={"ownedLegs": [leg(2, "BTCUSDT", "LONG")]})
    assert value["newEntry"]["reasonCode"] == "OWNERSHIP_CONFLICT"


def test_stale_or_missing_aster_data_never_green():
    stale = contract(snapshot={"capturedAt": NOW - timedelta(minutes=5)})
    missing = contract(snapshot={"capturedAt": None})
    assert stale["newEntry"]["status"] == "UNKNOWN"
    assert missing["newEntry"]["status"] == "UNKNOWN"


def test_stale_scheduler_never_reports_active_or_allowed():
    value = contract(s3={"lastTickAt": NOW - timedelta(minutes=5)})
    assert value["strategy3"]["status"] == "BLOCKED"
    assert value["newEntry"]["status"] == "UNKNOWN"


def test_missing_live_gate_blocks():
    value = contract(s3={"liveReady": False})
    assert value["newEntry"]["reasonCode"] == "LIVE_GATES_CLOSED"


def test_unknown_ownership_blocks():
    value = contract(s3={"ownedLegs": []})
    assert value["newEntry"]["reasonCode"] == "OWNERSHIP_UNKNOWN"


def test_data_hold_and_rate_limit_are_unknown():
    value = contract(s3={"phase": "DATA_HOLD", "lastReason": "Aster rate limit"})
    assert value["newEntry"]["status"] == "UNKNOWN"
    assert value["newEntry"]["reasonCode"] == "ASTER_RATE_LIMIT"


def test_reconciling_is_waiting():
    value = contract(s3={"phase": "RECONCILING", "lastReason": "Exchange-state controleren"})
    assert value["newEntry"]["status"] == "WAITING"


def test_next_check_is_only_emitted_for_verified_cadence():
    assert contract()["nextExpectedCheckAt"] is None
    value = contract(s3={"schedulerCadenceVerified": True, "schedulerIntervalSeconds": 60})
    assert value["nextExpectedCheckAt"] == NOW + timedelta(seconds=60)


def test_browser_contract_marks_every_decision_server_owned():
    value = contract()
    assert value["evidence"]["browserDerived"] is False


def test_detail_contract_exposes_every_active_check_and_block():
    value = contract(s3={"liveReady": False}, snapshot={"openOrders": 1})
    codes = {row["code"] for row in value["newEntry"]["checks"]}
    blocked = {row["code"] for row in value["newEntry"]["activeBlocks"]}
    assert {"ASTER_DATA_FRESH", "OWNERSHIP_UNKNOWN", "LIVE_GATES", "OPEN_ORDERS", "STRATEGY_BUDGET"} <= codes
    assert {"LIVE_GATES", "OPEN_ORDERS"} <= blocked


def test_contract_module_is_read_only_and_endpoint_is_get_only():
    contract_source = Path("aster_dashboard_status.py").read_text()
    main_source = Path("main.py").read_text()
    for forbidden in ("AsterV3Client", "firestore", "execute_", ".set({", ".add({"):
        assert forbidden not in contract_source
    assert '@app.get("/v1/me/aster/status")' in main_source
    assert '"botStatusDashboard": dashboard_status' in main_source
