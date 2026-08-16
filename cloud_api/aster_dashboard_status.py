"""Fail-closed, read-only Aster bot-status contract.

The dashboard consumes this projection verbatim.  It intentionally has no
exchange adapter, Firestore reference, order executor, or scheduler mutation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from aster_strategy2 import Strategy2Config
from aster_strategy2_runtime import scheduler_status as strategy2_scheduler_status
from aster_strategy3 import Strategy3Config
from aster_strategy3_status import strategy3_scheduler_status


EXCHANGE_DATA_MAX_AGE_SECONDS = 120
MANAGEMENT_ACTIONS = {
    "ADD_DCA", "ASSIGN_PROTECTION", "FULL_TP", "OPEN_PROTECTION",
    "PARTIAL_TP", "PROTECTION_INCREASE", "RELEASE_PROTECTION",
    "TRAILING_TP",
}
RECOVERY_PHASES = {"RECONCILING", "RECOVERY", "RECOVERING"}
DATA_HOLD_PHASES = {"DATA_HOLD", "API_ERROR"}
RISK_HOLD_PHASES = {"RISK_HOLD", "LIVE_HOLD", "CANARY_HOLD", "PAUSED"}


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result and abs(result) != float("inf") else 0.0


def _active_position_keys(snapshot: dict[str, Any]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    rows = snapshot.get("positions") if isinstance(snapshot.get("positions"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper()
        side = str(row.get("side", row.get("positionSide", ""))).upper()
        quantity = abs(_number(row.get("quantity", row.get("positionAmt", 0))))
        notional = abs(_number(row.get("notionalUsd", row.get("notional", 0))))
        if symbol and side in {"LONG", "SHORT"} and (quantity > 0 or notional > 0):
            result.add((symbol, side))
    return result


def _owned_keys(state: dict[str, Any], strategy_id: str, engine_type: str) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    rows = state.get("ownedLegs") if isinstance(state.get("ownedLegs"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_strategy = str(row.get("strategy_id", row.get("strategyId", ""))).lower()
        row_engine = str(row.get("engine_type", row.get("engineType", ""))).lower()
        symbol = str(row.get("symbol", "")).upper()
        side = str(row.get("side", "")).upper()
        if row_strategy == strategy_id and row_engine == engine_type and symbol and side in {"LONG", "SHORT"}:
            result.add((symbol, side))
    return result


def _scheduler_contract(state: dict[str, Any], strategy_id: int, now: datetime) -> dict[str, Any]:
    value = (strategy2_scheduler_status(state, now=now) if strategy_id == 2
             else strategy3_scheduler_status(state, now=now))
    return {
        "status": str(value.get("status", "STALE")),
        "lastTickAt": value.get("lastTickAt"),
        "ageSeconds": value.get("ageSeconds"),
        "warning": str(value.get("warning", "")),
    }


def _mode(config: Strategy2Config | Strategy3Config) -> str:
    return "LIVE" if config.mode == "live" else "PAPER"


def _live_gates(strategy_id: int, state: dict[str, Any], runtime_gates: dict[str, bool]) -> dict[str, bool]:
    common = bool(runtime_gates.get("asterLiveExecution", False))
    specific = bool(runtime_gates.get(f"strategy{strategy_id}Live", False))
    runtime = bool(runtime_gates.get(f"strategy{strategy_id}Runtime", specific))
    return {
        "asterLiveExecution": common,
        "strategyLive": specific,
        "runtimeEnabled": runtime,
        "canaryValidated": bool(state.get("canaryValidated", False)),
        "liveReady": bool(state.get("liveReady", False)),
    }


def _all_live_gates(gates: dict[str, bool]) -> bool:
    return all(gates.values())


def _strategy_status(*, state: dict[str, Any], config: Strategy2Config | Strategy3Config,
                     scheduler: dict[str, Any], gates: dict[str, bool], data_fresh: bool) -> str:
    enabled = bool(state.get("enabled", False))
    monitor = bool(state.get("monitor", False))
    phase = str(state.get("phase", "UNKNOWN")).upper()
    if not data_fresh:
        return "UNKNOWN"
    if phase in RECOVERY_PHASES or phase in DATA_HOLD_PHASES:
        return "RECOVERING"
    if not enabled or not monitor:
        return "STOPPED"
    if config.mode != "live":
        return "PAPER"
    if scheduler.get("status") != "HEALTHY" or not _all_live_gates(gates) or phase in RISK_HOLD_PHASES:
        return "BLOCKED"
    return "LIVE"


def _strategy_contract(*, strategy_id: int, state: dict[str, Any],
                       config: Strategy2Config | Strategy3Config,
                       active_keys: set[tuple[str, str]], owned_keys: set[tuple[str, str]],
                       data_fresh: bool, runtime_gates: dict[str, bool], now: datetime) -> dict[str, Any]:
    scheduler = _scheduler_contract(state, strategy_id, now)
    gates = _live_gates(strategy_id, state, runtime_gates)
    proven_owned = active_keys & owned_keys
    return {
        "status": _strategy_status(state=state, config=config, scheduler=scheduler, gates=gates, data_fresh=data_fresh),
        "mode": _mode(config),
        "enabled": bool(state.get("enabled", False)),
        "monitor": bool(state.get("monitor", False)),
        "phase": str(state.get("phase", "UNKNOWN")),
        "ownedPositions": len(proven_owned),
        "lastTickAt": state.get("lastTickAt"),
        "schedulerStatus": scheduler,
        "lastAction": str(state.get("lastAction", "NIET_BEWEZEN")),
        "lastActionAt": state.get("lastActionAt", state.get("lastAuditAt")),
        "lastReason": str(state.get("lastReason", "Geen bewezen reden beschikbaar")),
        "liveGates": gates,
        "ownershipStatus": "PROVEN" if owned_keys <= active_keys else "STALE_CLAIMS",
    }


def _result(status: str, code: str, text: str, *, checked_at: Any) -> dict[str, Any]:
    return {
        "status": status,
        "reasonCode": code,
        "reasonText": text,
        "strategyId": "aster-strategy-3",
        "checkedAt": checked_at,
    }


def _entry_checks(*, snapshot: dict[str, Any], state: dict[str, Any], config: Strategy3Config,
                  strategy: dict[str, Any], active_keys: set[tuple[str, str]],
                  s2_owned: set[tuple[str, str]], s3_owned: set[tuple[str, str]],
                  data_fresh: bool, counts_consistent: bool) -> list[dict[str, str]]:
    phase = str(state.get("phase", "UNKNOWN")).upper()
    account_state = state.get("accountSnapshot") if isinstance(state.get("accountSnapshot"), dict) else {}
    equity = _number(account_state.get("equity"))
    margin_ratio = _number(account_state.get("marginRatio"))
    strategy_margin = _number(account_state.get("strategyMargin"))
    universe = state.get("universe") if isinstance(state.get("universe"), dict) else {}
    selected = {str(symbol).upper() for symbol in universe.get("selectedSymbols", []) if str(symbol)}
    active_symbols = {symbol for symbol, _side in active_keys}
    checks = [
        ("ASTER_DATA_FRESH", data_fresh, "UNKNOWN", "Aster-data is recent bevestigd", "Aster-data is verouderd of ontbreekt"),
        ("ACCOUNT_COUNTS", counts_consistent, "UNKNOWN", "Accountaantallen zijn consistent", "Accountaantallen zijn tegenstrijdig"),
        ("OWNERSHIP_CONFLICT", not bool(s2_owned & s3_owned), "BLOCK", "Strategy-ownership botst niet", "Strategy-ownership botst"),
        ("OWNERSHIP_UNKNOWN", not bool(active_keys - (s2_owned | s3_owned)), "BLOCK", "Alle posities hebben bewezen ownership", "Position ownership is onduidelijk"),
        ("STRATEGY_ENABLED", bool(state.get("enabled", False)), "BLOCK", "Strategy 3 staat aan", "Strategy 3 staat uit"),
        ("MONITOR_ENABLED", bool(state.get("monitor", False)), "BLOCK", "Monitoring staat aan", "Monitoring staat uit"),
        ("LIVE_MODE", config.mode == "live", "BLOCK", "Live-modus is bewezen", "Strategy 3 staat in papermodus"),
        ("LIVE_GATES", _all_live_gates(strategy["liveGates"]), "BLOCK", "Alle live-gates zijn vrijgegeven", "Live-uitvoering is niet volledig vrijgegeven"),
        ("SCHEDULER_FRESH", strategy["schedulerStatus"].get("status") == "HEALTHY", "UNKNOWN", "Schedulerheartbeat is recent", "Scheduler is niet recent bevestigd"),
        ("OPEN_ORDERS", int(_number(snapshot.get("openOrders"))) == 0, "WAIT", "Geen open Aster-orders", "Open Aster-order moet eerst worden gereconcilieerd"),
        ("ACCOUNT_CAPACITY", len(active_keys) < config.maximum_positions, "BLOCK", "Accountbrede positieruimte beschikbaar", "Accountbrede positielimiet bereikt"),
        ("STRATEGY_ACCOUNT_STATE", equity > 0, "UNKNOWN", "Strategy-3-accountstaat is beschikbaar", "Strategy-3-accountstaat ontbreekt"),
        ("MARGIN_RATIO", equity > 0 and margin_ratio < config.defensive_margin_ratio, "BLOCK", "Margin ratio onder de ingestelde grens", "Margin ratio boven de ingestelde grens"),
        ("STRATEGY_BUDGET", equity > 0 and strategy_margin < equity * config.strategy_budget, "BLOCK", "Strategy-3-budget beschikbaar", "Strategy-3-budget bereikt"),
        ("MARKET_DATA", not bool(universe.get("entryBlocked", False)), "UNKNOWN", "Aster-marktdata is bruikbaar", str(universe.get("entryBlockReason", "Aster-marktdata ontbreekt"))),
        ("FREE_CONTRACT", bool(selected - active_symbols), "BLOCK", "Vrij Aster USDT-perpetualcontract beschikbaar", "Geen geschikt vrij Aster USDT-perpetualcontract"),
    ]
    if phase in DATA_HOLD_PHASES:
        checks.append(("DATA_HOLD", False, "UNKNOWN", "Geen data-hold", str(state.get("lastReason", "Exchange- of marktdata ontbreekt"))))
    elif phase in RECOVERY_PHASES:
        checks.append(("RECONCILING", False, "WAIT", "Geen reconciliatie nodig", str(state.get("lastReason", "Reconciliatie actief"))))
    elif phase in RISK_HOLD_PHASES:
        checks.append((phase, False, "BLOCK", "Geen blokkerende runtimefase", str(state.get("lastReason", phase))))
    return [{"code": code, "status": "PASS" if passed else failure, "text": good if passed else bad}
            for code, passed, failure, good, bad in checks]


def _entry_status(*, snapshot: dict[str, Any], state: dict[str, Any], config: Strategy3Config,
                  strategy: dict[str, Any], active_keys: set[tuple[str, str]],
                  s2_owned: set[tuple[str, str]], s3_owned: set[tuple[str, str]],
                  data_fresh: bool, counts_consistent: bool, now: datetime) -> dict[str, Any]:
    checked_at = state.get("lastTickAt")
    unknown = active_keys - (s2_owned | s3_owned)
    collisions = s2_owned & s3_owned
    gates = strategy["liveGates"]
    phase = str(state.get("phase", "UNKNOWN")).upper()
    scheduler = strategy["schedulerStatus"]
    if not data_fresh or not counts_consistent:
        return _result("UNKNOWN", "ASTER_DATA_STALE", "Aster-data is niet recent en volledig bevestigd", checked_at=checked_at)
    if collisions:
        return _result("BLOCKED", "OWNERSHIP_CONFLICT", "Position ownership botst tussen Strategy 2 en Strategy 3", checked_at=checked_at)
    if unknown:
        return _result("BLOCKED", "OWNERSHIP_UNKNOWN", "Niet alle actieve posities hebben bewezen ownership", checked_at=checked_at)
    if not bool(state.get("enabled", False)):
        return _result("BLOCKED", "STRATEGY_DISABLED", "Strategy 3 staat uit", checked_at=checked_at)
    if not bool(state.get("monitor", False)):
        return _result("BLOCKED", "MONITOR_DISABLED", "Strategy 3 monitoring staat uit", checked_at=checked_at)
    if config.mode != "live":
        return _result("BLOCKED", "PAPER_MODE", "Strategy 3 staat in papermodus", checked_at=checked_at)
    if not _all_live_gates(gates):
        return _result("BLOCKED", "LIVE_GATES_CLOSED", "Live-uitvoering is niet volledig vrijgegeven", checked_at=checked_at)
    if scheduler.get("status") != "HEALTHY":
        return _result("UNKNOWN", "SCHEDULER_STALE", "Scheduler is niet recent bevestigd", checked_at=checked_at)
    open_orders = int(_number(snapshot.get("openOrders")))
    if open_orders > 0:
        return _result("WAITING", "OPEN_ORDER_RECONCILIATION", "Een open Aster-order wordt eerst gereconcilieerd", checked_at=checked_at)
    if phase in DATA_HOLD_PHASES:
        reason = str(state.get("lastReason", "Exchange- of marktdata ontbreekt"))
        code = "ASTER_RATE_LIMIT" if "rate" in reason.lower() or "banned" in reason.lower() else "MARKET_DATA_MISSING"
        return _result("UNKNOWN", code, reason, checked_at=checked_at)
    if phase in RECOVERY_PHASES:
        return _result("WAITING", "RECONCILING", str(state.get("lastReason", "Ownership en exchange-state worden gereconcilieerd")), checked_at=checked_at)
    if phase in RISK_HOLD_PHASES:
        return _result("BLOCKED", phase, str(state.get("lastReason", "Een veiligheidsregel blokkeert nieuwe exposure")), checked_at=checked_at)
    maximum = config.maximum_positions
    if len(active_keys) >= maximum:
        return _result("BLOCKED", "ACCOUNT_POSITION_LIMIT", f"Accountbrede positielimiet bereikt: {len(active_keys)} van {maximum}", checked_at=checked_at)
    snapshot_state = state.get("accountSnapshot") if isinstance(state.get("accountSnapshot"), dict) else {}
    equity = _number(snapshot_state.get("equity"))
    margin_ratio = _number(snapshot_state.get("marginRatio"))
    strategy_margin = _number(snapshot_state.get("strategyMargin"))
    if equity <= 0:
        return _result("UNKNOWN", "STRATEGY_ACCOUNT_STATE_MISSING", "Actuele Strategy-3-accountstaat ontbreekt", checked_at=checked_at)
    if margin_ratio >= config.defensive_margin_ratio:
        return _result("BLOCKED", "MARGIN_RATIO_LIMIT", "Margin ratio ligt boven de ingestelde Strategy-3-grens", checked_at=checked_at)
    if strategy_margin >= equity * config.strategy_budget:
        return _result("BLOCKED", "STRATEGY_BUDGET_LIMIT", "Strategy-3-budget is bereikt", checked_at=checked_at)
    universe = state.get("universe") if isinstance(state.get("universe"), dict) else {}
    if bool(universe.get("entryBlocked", False)):
        reason = str(universe.get("entryBlockReason", "Aster-marktdata is niet betrouwbaar beschikbaar"))
        missing = any(word in reason.lower() for word in ("verlopen", "ontbreekt", "rate", "api", "banned", "ververst"))
        return _result("UNKNOWN" if missing else "BLOCKED", "MARKET_DATA_MISSING" if missing else "NO_TRADABLE_CONTRACT", reason, checked_at=checked_at)
    selected = {str(symbol).upper() for symbol in universe.get("selectedSymbols", []) if str(symbol)}
    active_symbols = {symbol for symbol, _side in active_keys}
    if not selected or not (selected - active_symbols):
        return _result("BLOCKED", "NO_FREE_CONTRACT", "Geen geschikt vrij Aster USDT-perpetualcontract", checked_at=checked_at)
    last_action = str(state.get("lastAction", "")).upper()
    last_action_at = _utc(state.get("lastActionAt", state.get("lastAuditAt")))
    if last_action in MANAGEMENT_ACTIONS and last_action_at and (now - last_action_at).total_seconds() <= 180:
        return _result("WAITING", "MANAGEMENT_ACTION_PRIORITY", "Een bestaande TP-, DCA- of beschermingsactie heeft deze tick voorrang", checked_at=checked_at)
    return _result("ALLOWED", "ALL_CHECKS_PASSED", "Alle actuele Strategy-3-instapcontroles zijn geslaagd", checked_at=checked_at)


def _strategy2_result(status: str, code: str, text: str, *, checked_at: Any) -> dict[str, Any]:
    return {
        "status": status,
        "reasonCode": code,
        "reasonText": text,
        "strategyId": "aster-strategy-2",
        "checkedAt": checked_at,
    }


def _strategy2_entry_checks(*, snapshot: dict[str, Any], state: dict[str, Any],
                            config: Strategy2Config, strategy: dict[str, Any],
                            active_keys: set[tuple[str, str]],
                            s2_owned: set[tuple[str, str]], s3_owned: set[tuple[str, str]],
                            data_fresh: bool, counts_consistent: bool) -> list[dict[str, str]]:
    phase = str(state.get("phase", "UNKNOWN")).upper()
    account_state = state.get("accountSnapshot") if isinstance(state.get("accountSnapshot"), dict) else {}
    equity = _number(account_state.get("equity"))
    margin_ratio = _number(account_state.get("marginRatio"))
    high_water_mark = _number(account_state.get("highWaterMark"))
    drawdown = _number(account_state.get("drawdown"))
    if drawdown <= 0 and equity > 0 and high_water_mark > 0:
        drawdown = max(0.0, 1 - equity / high_water_mark)
    strategy_margin = _number(account_state.get("strategyMargin"))
    next_margin = config.base_notional / max(1, config.leverage)
    universe = state.get("universe") if isinstance(state.get("universe"), dict) else {}
    selected = {str(symbol).upper() for symbol in universe.get("selectedSymbols", []) if str(symbol)}
    active_symbols = {symbol for symbol, _side in active_keys}
    checks = [
        ("ASTER_DATA_FRESH", data_fresh, "UNKNOWN", "Aster-data is recent bevestigd", "Aster-data is verouderd of ontbreekt"),
        ("ACCOUNT_COUNTS", counts_consistent, "UNKNOWN", "Accountaantallen zijn consistent", "Accountaantallen zijn tegenstrijdig"),
        ("OWNERSHIP_CONFLICT", not bool(s2_owned & s3_owned), "BLOCK", "Strategy-ownership botst niet", "Strategy-ownership botst"),
        ("OWNERSHIP_UNKNOWN", not bool(active_keys - (s2_owned | s3_owned)), "BLOCK", "Alle posities hebben bewezen ownership", "Position ownership is onduidelijk"),
        ("STRATEGY2_ENABLED", bool(state.get("enabled", False)), "BLOCK", "Strategy 2 staat aan", "Strategy 2 staat uit"),
        ("STRATEGY2_MONITOR", bool(state.get("monitor", False)), "BLOCK", "Strategy-2-monitoring staat aan", "Strategy-2-monitoring staat uit"),
        ("STRATEGY2_LIVE_MODE", config.mode == "live", "BLOCK", "Strategy 2 staat in live-modus", "Strategy 2 staat in papermodus"),
        ("STRATEGY2_LIVE_GATES", _all_live_gates(strategy["liveGates"]), "BLOCK", "Alle Strategy-2-livepoorten zijn vrijgegeven", "Strategy-2-live-uitvoering is niet volledig vrijgegeven"),
        ("STRATEGY2_SCHEDULER", strategy["schedulerStatus"].get("status") == "HEALTHY", "UNKNOWN", "Strategy-2-schedulerheartbeat is recent", "Strategy-2-scheduler is niet recent bevestigd"),
        ("OPEN_ORDERS", int(_number(snapshot.get("openOrders"))) == 0, "WAIT", "Geen open Aster-orders", "Open Aster-order moet eerst worden gereconcilieerd"),
        ("STRATEGY2_TARGET", len(s2_owned & active_keys) < config.maximum_pairs, "BLOCK", "Strategy-2-doel heeft vrije ruimte", "Ingesteld Strategy-2-positiedoel is bereikt"),
        ("STRATEGY2_ACCOUNT_STATE", equity > 0, "UNKNOWN", "Strategy-2-accountstaat is beschikbaar", "Strategy-2-accountstaat ontbreekt"),
        ("STRATEGY2_RISK_MODE", equity > 0 and margin_ratio < config.emergency_margin_ratio and drawdown < config.emergency_drawdown,
         "BLOCK", "Strategy 2 staat niet in noodmodus", "Strategy 2 is tijdelijk geblokkeerd door noodmodus"),
        ("STRATEGY2_BUDGET", equity > 0 and strategy_margin + next_margin <= equity * config.strategy_budget,
         "BLOCK", "Strategy-2-budget heeft ruimte", "Strategy-2-budget is bereikt"),
        ("STRATEGY2_MARKET_DATA", not bool(universe.get("entryBlocked", True)), "UNKNOWN",
         "Aster-marktdata is bruikbaar", str(universe.get("entryBlockReason", "Aster-marktdata ontbreekt"))),
        ("STRATEGY2_FREE_CONTRACT", bool(selected - active_symbols), "BLOCK",
         "Vrij Aster USDT-perpetualcontract beschikbaar", "Geen geschikt vrij Aster USDT-perpetualcontract"),
    ]
    if phase in DATA_HOLD_PHASES:
        checks.append(("STRATEGY2_DATA_HOLD", False, "UNKNOWN", "Geen data-hold", str(state.get("lastReason", "Exchange- of marktdata ontbreekt"))))
    elif phase in RECOVERY_PHASES:
        checks.append(("STRATEGY2_RECONCILING", False, "WAIT", "Geen reconciliatie nodig", str(state.get("lastReason", "Reconciliatie actief"))))
    elif phase in RISK_HOLD_PHASES:
        checks.append((f"STRATEGY2_{phase}", False, "BLOCK", "Geen blokkerende runtimefase", str(state.get("lastReason", phase))))
    return [{"code": code, "status": "PASS" if passed else failure, "text": good if passed else bad}
            for code, passed, failure, good, bad in checks]


def _strategy2_entry_status(*, snapshot: dict[str, Any], state: dict[str, Any],
                            config: Strategy2Config, strategy: dict[str, Any],
                            active_keys: set[tuple[str, str]],
                            s2_owned: set[tuple[str, str]], s3_owned: set[tuple[str, str]],
                            data_fresh: bool, counts_consistent: bool) -> dict[str, Any]:
    checked_at = state.get("lastTickAt")
    checks = _strategy2_entry_checks(snapshot=snapshot, state=state, config=config, strategy=strategy,
        active_keys=active_keys, s2_owned=s2_owned, s3_owned=s3_owned,
        data_fresh=data_fresh, counts_consistent=counts_consistent)
    active_blocks = [check for check in checks if check["status"] != "PASS"]
    first = active_blocks[0] if active_blocks else None
    if first:
        status = "UNKNOWN" if first["status"] == "UNKNOWN" else "WAITING" if first["status"] == "WAIT" else "BLOCKED"
        result = _strategy2_result(status, first["code"], first["text"], checked_at=checked_at)
    else:
        result = _strategy2_result("ALLOWED", "ALL_STRATEGY2_CHECKS_PASSED",
            "Alle actuele Strategy-2-instapcontroles zijn geslaagd", checked_at=checked_at)
    result["checks"] = checks
    result["activeBlocks"] = active_blocks
    return result


def build_aster_dashboard_status(*, snapshot: dict[str, Any], strategy2_state: dict[str, Any],
                                 strategy3_state: dict[str, Any], strategy2_config: Strategy2Config,
                                 strategy3_config: Strategy3Config, runtime_gates: dict[str, bool],
                                 evaluated_at: datetime | None = None) -> dict[str, Any]:
    """Build one authoritative dashboard contract without mutating any source."""
    now = (evaluated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    exchange_at = _utc(snapshot.get("capturedAt"))
    data_fresh = bool(exchange_at and 0 <= (now - exchange_at).total_seconds() <= EXCHANGE_DATA_MAX_AGE_SECONDS)
    active_keys = _active_position_keys(snapshot)
    reported_active = int(_number(snapshot.get("activePositions")))
    counts_consistent = reported_active == len(active_keys)
    s2_owned = _owned_keys(strategy2_state, "aster-strategy-2", "strategy2")
    s3_owned = _owned_keys(strategy3_state, "aster-strategy-3", "strategy3")
    long_positions = sum(1 for _symbol, side in active_keys if side == "LONG")
    short_positions = sum(1 for _symbol, side in active_keys if side == "SHORT")
    strategy2 = _strategy_contract(strategy_id=2, state=strategy2_state, config=strategy2_config,
        active_keys=active_keys, owned_keys=s2_owned, data_fresh=data_fresh and counts_consistent,
        runtime_gates=runtime_gates, now=now)
    strategy3 = _strategy_contract(strategy_id=3, state=strategy3_state, config=strategy3_config,
        active_keys=active_keys, owned_keys=s3_owned, data_fresh=data_fresh and counts_consistent,
        runtime_gates=runtime_gates, now=now)
    strategy2["targetPositions"] = strategy2_config.maximum_pairs
    strategy2["activeTargetPositions"] = len(s2_owned & active_keys)
    strategy2["remainingToTarget"] = max(0, strategy2_config.maximum_pairs - strategy2["activeTargetPositions"])
    strategy2["capacityBasis"] = "SERVER_OWNED_STRATEGY_POSITIONS"
    maximum = strategy3_config.maximum_positions
    strategy3["maximumPositions"] = maximum
    strategy3["remainingAccountCapacity"] = max(0, maximum - len(active_keys))
    entry = _entry_status(snapshot=snapshot, state=strategy3_state, config=strategy3_config,
        strategy=strategy3, active_keys=active_keys, s2_owned=s2_owned, s3_owned=s3_owned,
        data_fresh=data_fresh, counts_consistent=counts_consistent, now=now)
    entry["checks"] = _entry_checks(snapshot=snapshot, state=strategy3_state, config=strategy3_config,
        strategy=strategy3, active_keys=active_keys, s2_owned=s2_owned, s3_owned=s3_owned,
        data_fresh=data_fresh, counts_consistent=counts_consistent)
    entry["activeBlocks"] = [check for check in entry["checks"] if check["status"] != "PASS"]
    strategy2_entry = _strategy2_entry_status(snapshot=snapshot, state=strategy2_state,
        config=strategy2_config, strategy=strategy2, active_keys=active_keys,
        s2_owned=s2_owned, s3_owned=s3_owned, data_fresh=data_fresh,
        counts_consistent=counts_consistent)
    cadence = int(_number(strategy3_state.get("schedulerIntervalSeconds")))
    cadence_verified = bool(strategy3_state.get("schedulerCadenceVerified", False))
    tick_at = _utc(strategy3_state.get("lastTickAt"))
    next_check = tick_at + timedelta(seconds=cadence) if cadence_verified and cadence > 0 and tick_at else None
    return {
        "evaluatedAt": now,
        "exchangeDataAt": exchange_at,
        "dataFresh": data_fresh and counts_consistent,
        "account": {
            "activePositions": len(active_keys),
            "longPositions": long_positions,
            "shortPositions": short_positions,
            "openOrders": int(_number(snapshot.get("openOrders"))),
            "maintenanceMarginPercent": _number(snapshot.get("marginRatio")) * 100,
        },
        "strategy2": strategy2,
        "strategy3": strategy3,
        "strategy2NewEntry": strategy2_entry,
        "newEntry": entry,
        "nextExpectedCheckAt": next_check,
        "evidence": {
            "accountCountsConsistent": counts_consistent,
            "unknownOwnershipCount": len(active_keys - (s2_owned | s3_owned)),
            "ownershipConflictCount": len(s2_owned & s3_owned),
            "browserDerived": False,
        },
    }
