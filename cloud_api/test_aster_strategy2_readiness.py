from aster_strategy2_readiness import build_readiness_report


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


def test_live_ready_requires_separate_canary_validation():
    assert good(canary_validated=True)["liveReady"] is True
