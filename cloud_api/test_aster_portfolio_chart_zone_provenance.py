from aster_portfolio_chart import aggregate_trade_activity


def test_zone_origin_and_soldier_role_survive_portfolio_marker_aggregation():
    markers = aggregate_trade_activity({
        "entries": [{
            "timestampMs": 900_000,
            "side": "LONG",
            "executedNotionalUsd": 125,
            "originZone": -1,
            "soldierRole": "ZONE_BASE",
        }],
        "exits": [],
    }, "15m")
    assert len(markers) == 1
    assert markers[0]["originZones"] == [-1]
    assert markers[0]["soldierRoles"] == ["ZONE_BASE"]
