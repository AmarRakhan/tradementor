from aster_source_ownership import matching_source_ownership


def source(*, positions, unknown=0, conflicts=0, fresh=True):
    return {
        "configured": True, "credentialsVerified": True, "positions": positions,
        "botStatusDashboard": {"dataFresh": fresh, "evidence": {
            "accountCountsConsistent": True, "unknownOwnershipCount": unknown,
            "ownershipConflictCount": conflicts, "browserDerived": False,
        }},
    }


def test_exact_server_proven_strategy2_and_strategy3_rows_are_recoverable():
    current = [
        {"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"2","entryPrice":"100"},
        {"symbol":"ETHUSDT","positionSide":"SHORT","positionAmt":"-3","entryPrice":"50"},
    ]
    status = source(positions=[
        {"symbol":"BTCUSDT","side":"LONG","quantity":2,"entryPrice":100,"strategyId":"aster-strategy-2","dcaCount":2},
        {"symbol":"ETHUSDT","side":"SHORT","quantity":3,"entryPrice":50,"strategyId":"aster-strategy-3"},
    ])
    result = matching_source_ownership(current_positions=current, source_status=status, config_version=7)
    assert result.accepted and [(x.symbol,x.side,x.config_version) for x in result.strategy2_legs] == [("BTCUSDT","LONG",7)]
    assert [(x.symbol,x.side) for x in result.strategy3_legs] == [("ETHUSDT","SHORT")]


def test_unknown_conflicting_or_browser_derived_source_never_assigns_ownership():
    current = [{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"2","entryPrice":"100"}]
    row = {"symbol":"BTCUSDT","side":"LONG","quantity":2,"entryPrice":100,"strategyId":"aster-strategy-2"}
    for status in (source(positions=[row], unknown=1), source(positions=[row], conflicts=1), source(positions=[row], fresh=False)):
        result = matching_source_ownership(current_positions=current, source_status=status)
        assert not result.accepted and not result.strategy2_legs and not result.strategy3_legs


def test_quantity_entry_or_key_mismatch_remains_fail_closed():
    current = [{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"2","entryPrice":"100"}]
    variants = [
        {"symbol":"BTCUSDT","side":"LONG","quantity":3,"entryPrice":100,"strategyId":"aster-strategy-2"},
        {"symbol":"BTCUSDT","side":"LONG","quantity":2,"entryPrice":101,"strategyId":"aster-strategy-2"},
        {"symbol":"ETHUSDT","side":"LONG","quantity":2,"entryPrice":100,"strategyId":"aster-strategy-2"},
    ]
    for row in variants:
        assert not matching_source_ownership(current_positions=current, source_status=source(positions=[row])).accepted


def test_unlabelled_or_non_strategy_source_position_is_never_claimed():
    current = [{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"2","entryPrice":"100"}]
    for strategy_id in ("", "aster-strategy-1", "manual"):
        row = {"symbol":"BTCUSDT","side":"LONG","quantity":2,"entryPrice":100,"strategyId":strategy_id}
        assert not matching_source_ownership(current_positions=current, source_status=source(positions=[row])).accepted
