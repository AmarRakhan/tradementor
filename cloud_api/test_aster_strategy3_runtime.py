from aster_strategy3 import Strategy3Config
from aster_strategy2_runtime import balanced_entry_targets, next_balanced_entry_side
from aster_strategy2_state import OwnedLeg
from aster_strategy3 import account_canary_proven, persisted_runtime_mode, account_entry_side


def s3(side: str, symbol: str = "BTCUSDT") -> OwnedLeg:
    return OwnedLeg("aster-strategy-3", "strategy3", symbol, side, "cycle", 1, 1, 10)


def test_strategy3_live_mode_cannot_be_opened_by_config_payload():
    config = Strategy3Config.from_mapping({"mode": "live"})
    assert config.mode == "paper"
    assert config.public_dict()["mode"] == "paper"
    assert Strategy3Config.from_mapping({"mode": "invalid"}).mode == "paper"


def test_strategy3_balanced_capacity_is_per_leg():
    assert balanced_entry_targets(5) == (3, 2)
    owned = [s3("LONG", "BTCUSDT"), s3("SHORT", "ETHUSDT")]
    assert next_balanced_entry_side(owned, 5) == "LONG"


def test_shared_seat_counter_counts_every_live_leg_even_for_legacy_strategy3_fixture():
    owned = [s3("LONG"), OwnedLeg("aster-strategy-3", "strategy3", "ETHUSDT", "SHORT", "p", 1, 1, 10, role="PROTECTION")]
    assert next_balanced_entry_side(owned, 2) is None


def test_strategy3_account_limit_counts_other_and_unknown_positions():
    active={(f"L{x}USDT","LONG") for x in range(54)}|{(f"S{x}USDT","SHORT") for x in range(56)}
    assert account_entry_side(active,100) is None
    assert account_entry_side(set(list(active)[:99]),100) in {"LONG","SHORT"}


def test_strategy3_account_entry_balances_complete_account():
    assert account_entry_side({("BTCUSDT","LONG"),("ETHUSDT","LONG"),("SOLUSDT","SHORT")},10)=="SHORT"


def test_live_account_requires_completed_own_canary_document():
    assert not account_canary_proven({"canaryValidated": True}, {"status": "OPENED"})
    assert account_canary_proven({"canaryValidated": True}, {"status": "COMPLETED"})
    assert not account_canary_proven({"liveAccountAuthorized": True}, {})
    assert persisted_runtime_mode({"mode":"live"},{"status":"COMPLETED"}) == "live"
    assert persisted_runtime_mode({"mode":"live"},{"status":"OPENED"}) == "paper"
    assert persisted_runtime_mode({"mode":"paper"},{"status":"COMPLETED"}) == "paper"
