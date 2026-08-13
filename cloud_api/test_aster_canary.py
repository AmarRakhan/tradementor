import pytest
from aster_canary import choose_flat_symbol,existing_canary_action

def test_uncertain_or_in_progress_canary_is_never_retried():
    assert existing_canary_action("UNKNOWN")=="block"
    assert existing_canary_action("OPENED")=="block"
    assert existing_canary_action("COMPLETED")=="replay"

def test_canary_never_adds_to_an_existing_position():
    info={"symbols":[{"symbol":"BTCUSDT","status":"TRADING"},{"symbol":"ETHUSDT","status":"TRADING"}]}
    assert choose_flat_symbol(info,{"BTCUSDT":1,"ETHUSDT":1},{"BTCUSDT"})["symbol"]=="ETHUSDT"
    with pytest.raises(ValueError):choose_flat_symbol(info,{"BTCUSDT":1,"ETHUSDT":1},{"BTCUSDT","ETHUSDT"})
