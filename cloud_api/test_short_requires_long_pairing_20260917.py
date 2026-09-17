from pathlib import Path
import time

from aster_multi_bb import run_multi_bb_step
from test_aster_multi_bb import Client, Ref, cfg


def pos(symbol: str, side: str, *, mark: float = 100.0):
    return {"symbol": symbol, "positionSide": side, "positionAmt": "1", "entryPrice": "100", "markPrice": str(mark), "leverage": "100"}


def state_for(symbol: str, side: str):
    return {"multiBbPositions": {f"{symbol}|{side}": {"cycleId": "c1", "dcaCount": 0, "lastBotFillPrice": 100, "lastKnownQty": 1, "lastKnownEntry": 100, "cycleStartedAtMs": 1, "botManaged": True}}}


def run(*, settings, positions=None, raw_state=None, tickers=None, prices=None):
    positions = list(positions or [])
    tickers = list(tickers or [{"symbol": "AAAUSDT", "quoteVolume": "1000"}])
    prices = dict(prices or {str(row["symbol"]): 100 for row in tickers})
    client = Client(positions=positions, tickers=tickers, prices=prices, leverage=100)
    return run_multi_bb_step(
        client=client, ref=Ref(), raw_state=raw_state or {}, settings=settings, uid="u",
        account={"availableBalance": "1000"}, positions=positions, open_orders=[],
        timestamp_ms=int(time.time() * 1000), dry_run=True,
    )


def test_toggle_roundtrips_through_public_settings():
    settings = cfg(shortRequiresLongEnabled=True)
    assert settings.short_requires_long_enabled is True
    assert settings.public_dict()["shortRequiresLongEnabled"] is True


def test_new_short_is_blocked_without_same_symbol_long_when_enabled():
    result = run(settings=cfg(maximumPositions=1, longSlots=0, shortSlots=1, shortRequiresLongEnabled=True))
    assert not [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert any(row.get("reason") == "SHORT_REQUIRES_LONG" for row in result["actions"])


def test_legacy_short_entry_still_works_when_toggle_is_off():
    result = run(settings=cfg(maximumPositions=1, longSlots=0, shortSlots=1, shortRequiresLongEnabled=False))
    entry = next(row for row in result["actions"] if row.get("kind") == "ENTRY")
    assert entry["symbol"] == "AAAUSDT"
    assert entry["side"] == "SHORT"


def test_short_can_open_when_same_symbol_long_already_exists():
    long = pos("AAAUSDT", "LONG")
    result = run(
        settings=cfg(maximumPositions=2, longSlots=1, shortSlots=1, shortRequiresLongEnabled=True),
        positions=[long], raw_state=state_for("AAAUSDT", "LONG"),
    )
    entry = next(row for row in result["actions"] if row.get("kind") == "ENTRY")
    assert entry["symbol"] == "AAAUSDT"
    assert entry["side"] == "SHORT"


def test_orphan_short_symbol_gets_long_priority_over_higher_volume_unpaired_coin():
    short = pos("AAAUSDT", "SHORT")
    result = run(
        settings=cfg(maximumPositions=2, longSlots=1, shortSlots=1, shortRequiresLongEnabled=True),
        positions=[short], raw_state=state_for("AAAUSDT", "SHORT"),
        tickers=[{"symbol": "BBBUSDT", "quoteVolume": "2000"}, {"symbol": "AAAUSDT", "quoteVolume": "1000"}],
        prices={"AAAUSDT": 100, "BBBUSDT": 100},
    )
    entry = next(row for row in result["actions"] if row.get("kind") == "ENTRY")
    assert entry["symbol"] == "AAAUSDT"
    assert entry["side"] == "LONG"


def test_existing_short_dca_is_not_blocked_by_entry_only_pairing_gate():
    short = pos("AAAUSDT", "SHORT", mark=101.0)
    result = run(
        settings=cfg(maximumPositions=1, longSlots=0, shortSlots=1, shortRequiresLongEnabled=True, maxDca=3),
        positions=[short], raw_state=state_for("AAAUSDT", "SHORT"),
        tickers=[], prices={"AAAUSDT": 101.0},
    )
    assert any(row.get("kind") == "DCA" and row.get("side") == "SHORT" for row in result["actions"])


def test_frontend_toggle_is_loaded_saved_and_rendered_next_to_seat_controls():
    source = (Path(__file__).resolve().parents[1] / "web/components/aster-strategy2-maker.tsx").read_text(encoding="utf-8")
    assert "shortRequiresLongEnabled: boolean" in source
    assert "shortRequiresLongEnabled: x.shortRequiresLongEnabled === true" in source
    assert "shortRequiresLongEnabled: v.shortRequiresLongEnabled" in source
    assert "SHORT alleen met LONG" in source
    assert "LONG mag altijd zelfstandig openen" in source
