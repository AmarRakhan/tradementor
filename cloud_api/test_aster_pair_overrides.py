import pytest

from aster_multi_bb import MultiBbConfig, _PairAwareSettings, effective_pair_settings


def _config(**extra):
    raw = {
        "engine": "multi_bb_v1",
        "universeTopN": 30,
        "maximumPositions": 30,
        "longSlots": 20,
        "shortSlots": 10,
        "minimumLeverage": 50,
        "entryMarginUsd": 5,
        "entryNotionalUsd": 250,
        "entrySizingMode": "margin",
        "dcaDistance": .003,
        "dcaMarginUsd": 2,
        "maxDca": 3,
        "takeProfit": .015,
        "takeProfitEnabled": True,
    }
    raw.update(extra)
    return MultiBbConfig.from_mapping(raw)


def _read_effective(proxy, symbol):
    # The pair-aware facade resolves the currently handled symbol from the
    # unchanged engine frame. Keep a local named `symbol` to mirror that loop.
    return proxy.max_dca, proxy.dca_margin_usd, proxy.dca_distance, proxy.take_profit


def test_pair_override_round_trips_and_is_sparse():
    config = _config(pairOverrides={
        "HYPE/USDT": {
            "enabled": True,
            "maxDca": 12,
            "dcaMarginUsd": 7.5,
            "dcaDistance": .0045,
            "takeProfit": .025,
        }
    })

    assert config.pair_overrides["HYPEUSDT"] == {
        "maxDca": 12,
        "dcaDistance": .0045,
        "dcaMarginUsd": 7.5,
        "takeProfit": .025,
    }
    saved = config.public_dict()["pairOverrides"]["HYPEUSDT"]
    assert saved["enabled"] is True
    assert saved["maxDca"] == 12
    assert saved["takeProfit"] == .025
    assert "entryMarginUsd" not in saved


def test_pair_override_precedence_does_not_change_other_pairs():
    config = _config(pairOverrides={"HYPEUSDT": {"maxDca": 9, "dcaMarginUsd": 6, "takeProfit": .03}})
    proxy = _PairAwareSettings(config)

    assert _read_effective(proxy, "HYPEUSDT") == (9, 6, .003, .03)
    assert _read_effective(proxy, "BTCUSDT") == (3, 2, .003, .015)

    hype = effective_pair_settings(config, "HYPE/USDT")
    btc = effective_pair_settings(config, "BTCUSDT")
    assert hype["custom"] is True and hype["maxDca"] == 9
    assert btc["custom"] is False and btc["maxDca"] == 3


def test_disabled_or_empty_override_restores_global_settings():
    disabled = _config(pairOverrides={"HYPEUSDT": {"enabled": False, "maxDca": 99}})
    empty = _config(pairOverrides={"HYPEUSDT": {"enabled": True}})
    assert disabled.pair_overrides == {}
    assert empty.pair_overrides == {}


def test_next_cycle_fields_can_be_overridden_per_pair():
    config = _config(pairOverrides={"HYPEUSDT": {
        "entryMarginUsd": 12,
        "minimumLeverage": 125,
        "shortStartMultiplier": 2,
    }})
    hype = effective_pair_settings(config, "HYPEUSDT")
    btc = effective_pair_settings(config, "BTCUSDT")
    assert (hype["entryMarginUsd"], hype["minimumLeverage"], hype["shortStartMultiplier"]) == (12, 125, 2)
    assert (btc["entryMarginUsd"], btc["minimumLeverage"], btc["shortStartMultiplier"]) == (5, 50, 5)


@pytest.mark.parametrize("override", [
    {"minimumLeverage": 0},
    {"minimumLeverage": 301},
    {"entryMarginUsd": 0},
    {"dcaMarginUsd": -1},
    {"dcaDistance": 0},
    {"dcaDistance": .51},
    {"maxDca": -1},
    {"maxDca": 501},
    {"takeProfit": 0},
    {"shortStartMultiplier": .5},
    {"shortStartMultiplier": 11},
])
def test_invalid_pair_overrides_fail_closed(override):
    with pytest.raises(ValueError):
        _config(pairOverrides={"HYPEUSDT": override})


def test_invalid_symbol_fails_closed():
    with pytest.raises(ValueError):
        _config(pairOverrides={"../../HYPE": {"maxDca": 5}})
