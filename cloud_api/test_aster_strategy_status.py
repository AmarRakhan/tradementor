from aster_strategy_status import (OWNERSHIP_CONFIRMED_REASON, operating_status_contract,
    ownership_reason_contract, position_count_contract, proven_owned_rows,
    reconciled_ownership_update)
from pathlib import Path


def _universe(*, blocked=False, stale=False, selected=50):
    return {"requestedTopN": 50, "eligibleMarketCount": 80, "selectedMarketCount": selected,
        "stale": stale, "entryBlocked": blocked,
        "entryBlockReason": "Aster-data ontbreekt" if blocked else ""}


def test_strategy2_off_blocks_entries_but_describes_safe_existing_management():
    status = operating_status_contract(enabled=False, monitor=True, runtime_enabled=False,
        owned_leg_count=3, universe=_universe())
    assert status["bot"] == {"state": "OFF", "enabled": False}
    assert status["newEntries"]["state"] == "BLOCKED_BOT_OFF"
    assert status["existingPositionManagement"]["state"] == "SAFE_EXISTING_ONLY"
    assert status["existingPositionManagement"]["exchangeConfirmed"] is True
    assert status["marketData"]["state"] == "READY"


def test_stale_market_data_blocks_only_new_entries_not_management():
    status = operating_status_contract(enabled=True, monitor=True, runtime_enabled=True,
        owned_leg_count=2, universe=_universe(blocked=True, stale=True))
    assert status["newEntries"] == {"state": "BLOCKED_MARKET_DATA", "blocked": True,
        "reason": "Aster-data ontbreekt"}
    assert status["existingPositionManagement"]["state"] == "FULL"
    assert status["marketData"]["state"] == "STALE"


def test_rest_ban_never_claims_existing_position_management_is_confirmed():
    status = operating_status_contract(enabled=False, monitor=True, runtime_enabled=False,
        owned_leg_count=3, universe=_universe(blocked=True, stale=True), exchange_data_fresh=False)
    assert status["bot"]["state"] == "OFF"
    assert status["newEntries"]["blocked"] is True
    assert status["existingPositionManagement"]["state"] == "UNCONFIRMED"
    assert status["existingPositionManagement"]["exchangeConfirmed"] is False
    assert "niet worden bevestigd" in status["existingPositionManagement"]["reason"]


def test_counts_distinguish_unique_markets_and_position_legs():
    rows = [
        {"strategy_id":"aster-strategy-2","engine_type":"strategy2","symbol":"BTCUSDT","side":"LONG"},
        {"strategy_id":"aster-strategy-2","engine_type":"strategy2","symbol":"BTCUSDT","side":"SHORT"},
        {"strategy_id":"aster-strategy-2","engine_type":"strategy2","symbol":"ETHUSDT","side":"SHORT"},
    ]
    counts = position_count_contract(rows, scope="strategy2-proven-owned")
    assert counts["uniqueMarketCount"] == 2
    assert counts["positionLegCount"] == 3
    assert counts["longLegs"] == 1 and counts["shortLegs"] == 2


def test_strategy2_ownership_never_includes_accountwide_or_strategy3_rows():
    rows = [
        {"strategy_id":"aster-strategy-2","engine_type":"strategy2","symbol":"BTCUSDT","side":"LONG"},
        {"strategy_id":"aster-strategy-3","engine_type":"strategy3","symbol":"ETHUSDT","side":"SHORT"},
        {"symbol":"SOLUSDT","side":"LONG"},
        {"strategy_id":"aster-strategy-2","engine_type":"strategy2","symbol":"","side":"LONG"},
    ]
    owned = proven_owned_rows(rows, strategy_id="aster-strategy-2", engine_type="strategy2")
    assert [(row["symbol"], row["side"]) for row in owned] == [("BTCUSDT", "LONG")]


def test_resolved_ownership_warning_is_not_published_as_current():
    assert ownership_reason_contract("Actieve exposure zonder bewezen ownership", 0) == OWNERSHIP_CONFIRMED_REASON
    assert ownership_reason_contract("Actieve Aster-exposure zonder bewezen Strategy-ownership", 0) == OWNERSHIP_CONFIRMED_REASON


def test_active_ownership_warning_and_unrelated_reasons_are_preserved():
    warning = "Actieve exposure zonder bewezen ownership"
    assert ownership_reason_contract(warning, 1) == warning
    assert ownership_reason_contract("Nieuwe entry geblokkeerd door risicobudget", 0) == "Nieuwe entry geblokkeerd door risicobudget"


def test_successful_reconciliation_clears_counter_and_stale_reason_atomically():
    assert reconciled_ownership_update("Actieve exposure zonder bewezen ownership") == {
        "unassignedPositions": 0,
        "lastReason": OWNERSHIP_CONFIRMED_REASON,
    }


def test_strategy2_off_returns_before_every_new_entry_path_but_after_management():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    start = source.index("def _run_aster_strategy2_tick")
    end = source.index("def _aster_brackets", start)
    tick = source[start:end]
    management = tick.index("selected=portfolio_protection_decision")
    off_guard = tick.index("if not enabled or not scanner_allowed")
    universe_fetch = tick.index("exchange_info=client.public_exchange_info()", off_guard)
    assert management < off_guard < universe_fetch
    guard_block = tick[off_guard:universe_fetch]
    assert '"ordersSent":0' in guard_block
    assert 'reason="Strategy 2 staat veilig gestopt"' in guard_block


def test_no_backend_module_contains_removed_external_market_fallback():
    removed_name = "".join(("coin", "market", "cap"))
    for path in Path(__file__).parent.glob("*.py"):
        if path == Path(__file__):
            continue
        assert removed_name not in path.read_text(encoding="utf-8").lower(), path.name


def test_strategy2_entry_paths_use_the_shared_aster_snapshot_builder():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    assert "build_aster_universe_snapshot" in source
    assert source.count('universe_contract["selectedSymbols"]') >= 2


def test_public_dashboard_status_never_refreshes_every_position_cost_from_aster():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    route = source[source.index("def aster_status("):source.index('@app.get("/v1/me/aster/trade-events")')]
    assert "_read_strategy_cost_evidence(" not in route
    assert "refresh_owned_costs(" not in route
    assert "strategy2_costs_by_key=dict(strategy2_owned_by_key)" in route
    assert "aster_strategy3_reference" not in route
    assert "aster_automation_public" not in route
