from aster_strategy2_readiness import build_readiness_report, combined_strategy_ownership


def good(**changes):
    values=dict(hedge_mode=True,account={"totalMarginBalance":"125"},positions=[],open_orders=[],
        ownership_keys=set(),order_history_readable=True,fills_readable=True,income_readable=True,
        reconciliation_passed=True,canary_validated=False)
    values.update(changes)
    return build_readiness_report(**values)


def test_software_can_be_ready_without_claiming_live_ready():
    report=good()
    assert report["softwareReady"] is True
    assert report["liveReady"] is False
    assert report["ordersSent"] == 0


def test_unknown_position_ownership_blocks_new_live_risk():
    report=good(positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":".01"}])
    assert report["softwareReady"] is False
    assert report["unownedPositions"] == [{"symbol":"BTCUSDT","side":"LONG"}]


def test_proven_strategy3_position_does_not_block_strategy2_readiness():
    strategy3_key = ("ETHUSDT", "SHORT")
    known, collisions = combined_strategy_ownership(
        strategy1_keys=set(), strategy2_keys=set(), strategy3_keys={strategy3_key})
    report=good(
        positions=[{"symbol":"ETHUSDT","positionSide":"SHORT","positionAmt":".5"}],
        ownership_keys=known,
        reconciliation_passed=not collisions,
    )
    assert collisions == set()
    assert report["softwareReady"] is True
    assert report["unownedPositions"] == []


def test_strategy2_strategy3_duplicate_claim_stays_fail_closed():
    duplicate = ("SOLUSDT", "LONG")
    known, collisions = combined_strategy_ownership(
        strategy1_keys=set(), strategy2_keys={duplicate}, strategy3_keys={duplicate})
    report=good(
        positions=[{"symbol":"SOLUSDT","positionSide":"LONG","positionAmt":"1"}],
        ownership_keys=known,
        reconciliation_passed=not collisions,
    )
    assert collisions == {duplicate}
    assert report["softwareReady"] is False


def test_live_ready_requires_separate_canary_validation():
    assert good(canary_validated=True)["liveReady"] is True
