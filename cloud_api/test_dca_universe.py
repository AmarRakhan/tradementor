import pytest

from aster_strategy import AsterStrategySettings
from aster_strategy2 import Strategy2Config
from aster_strategy3 import Strategy3Config
from aster_universe import normalize_top_n


def test_arbitrary_positive_top_n_is_preserved_without_clamping_or_rounding():
    assert [normalize_top_n(value) for value in (1, 50, 137, 150, 200, 999)] == [1, 50, 137, 150, 200, 999]
    with pytest.raises(ValueError):
        normalize_top_n(150.5)


def test_top_150_survives_server_serialization_for_all_strategies():
    for config_type in (AsterStrategySettings, Strategy2Config, Strategy3Config):
        saved = config_type.from_mapping({"universeTopN": 150}).public_dict()
        assert config_type.from_mapping(saved).universe_top_n == 150
