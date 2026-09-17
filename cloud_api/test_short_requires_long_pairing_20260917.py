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



def test_different_symbol_long_does_not_authorize_short():
    other_long = pos("BBBUSDT", "LONG")
    result = run(
        settings=cfg(maximumPositions=2, longSlots=1, shortSlots=1, shortRequiresLongEnabled=True),
        positions=[other_long], raw_state=state_for("BBBUSDT", "LONG"),
        tickers=[{"symbol": "AAAUSDT", "quoteVolume": "1000"}], prices={"AAAUSDT": 100, "BBBUSDT": 100},
    )
    assert not [row for row in result["actions"] if row.get("kind") == "ENTRY" and row.get("side") == "SHORT"]
    assert any(row.get("symbol") == "AAAUSDT" and row.get("reason") == "SHORT_REQUIRES_LONG" for row in result["actions"])


def test_manual_selected_short_cannot_bypass_same_pair_long_gate():
    result = run(settings=cfg(
        maximumPositions=1, longSlots=0, shortSlots=1, shortRequiresLongEnabled=True,
        manualSymbolSelectionEnabled=True, manualSymbols=[{"symbol": "AAAUSDT", "side": "SHORT"}],
    ))
    assert not [row for row in result["actions"] if row.get("kind") == "ENTRY" and row.get("side") == "SHORT"]
    assert any(row.get("reason") == "SHORT_REQUIRES_LONG" for row in result["actions"])


def test_asymmetric_mode_defers_same_tick_short_until_long_preexists():
    result = run(settings=cfg(
        maximumPositions=2, longSlots=1, shortSlots=1, shortRequiresLongEnabled=True,
        asymmetricHedgeModeEnabled=True, shortStartMultiplier=2,
    ))
    assert any(row.get("kind") == "ENTRY" and row.get("side") == "LONG" for row in result["actions"])
    assert not any(row.get("kind") == "ASYM_SHORT_ENTRY" for row in result["actions"])
    assert any(row.get("kind") == "ASYM_SHORT_ENTRY_PENDING" and row.get("reason") == "SHORT_REQUIRES_PREEXISTING_LONG" for row in result["actions"])


def test_source_reapplies_gate_after_final_bollinger_side_selection():
    source = (Path(__file__).resolve().parent / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    selected = source.index("side = selected_side")
    final_gate = source.index('"stage": "final_side"')
    planning = source.index("paired = bool(settings.asymmetric_hedge_enabled)", final_gate)
    assert selected < final_gate < planning
    assert "short_requires_long_gate = settings.short_requires_long_enabled and not settings.asymmetric_hedge_enabled" not in source


def test_paired_short_recovery_rechecks_exchange_long_before_live_submit():
    source = (Path(__file__).resolve().parent / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    recovery = source.index("# Recover an initial paired SHORT idempotently")
    pre_order_guard = source.index('"stage": "pre_order"', recovery)
    submit = source.index('id_prefix=f"mbb-asym-short-', pre_order_guard)
    assert recovery < pre_order_guard < submit



def test_orphan_outside_top_n_is_injected_and_forced_long_first():
    short = pos("ZECUSDT", "SHORT")
    result = run(
        settings=cfg(maximumPositions=3, longSlots=2, shortSlots=1, shortRequiresLongEnabled=True, universeTopN=2),
        positions=[short], raw_state=state_for("ZECUSDT", "SHORT"),
        tickers=[{"symbol": "AAAUSDT", "quoteVolume": "999999"}],
        prices={"AAAUSDT": 100, "ZECUSDT": 100},
    )
    entries = [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert entries, result
    assert entries[0]["symbol"] == "ZECUSDT"
    assert entries[0]["side"] == "LONG"
    assert "ZECUSDT" in result["orphanShortSymbols"]


def test_multiple_orphan_shorts_consume_free_long_seats_before_normal_candidates():
    shorts = [pos("AAAUSDT", "SHORT"), pos("BBBUSDT", "SHORT")]
    raw = {"multiBbPositions": {}}
    raw["multiBbPositions"].update(state_for("AAAUSDT", "SHORT")["multiBbPositions"])
    raw["multiBbPositions"].update(state_for("BBBUSDT", "SHORT")["multiBbPositions"])
    result = run(
        settings=cfg(maximumPositions=4, longSlots=2, shortSlots=2, shortRequiresLongEnabled=True, universeTopN=2),
        positions=shorts, raw_state=raw,
        tickers=[{"symbol": "CCCUSDT", "quoteVolume": "999999"}],
        prices={"AAAUSDT": 100, "BBBUSDT": 100, "CCCUSDT": 100},
    )
    entries = [(row["symbol"], row["side"]) for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert entries[:2] == [("AAAUSDT", "LONG"), ("BBBUSDT", "LONG")]



def test_orphan_priority_uses_exchange_truth_when_caller_snapshot_is_stale():
    # Reproduces the live 2026-09-17 failure: Aster has ZEC SHORT, while the
    # caller-provided snapshot is one tick stale and contains no positions.
    short = pos("ZECUSDT", "SHORT")
    client = Client(
        positions=[short],
        tickers=[{"symbol": "AAAUSDT", "quoteVolume": "999999"}],
        prices={"AAAUSDT": 100, "ZECUSDT": 100},
        leverage=100,
    )
    result = run_multi_bb_step(
        client=client, ref=Ref(), raw_state=state_for("ZECUSDT", "SHORT"),
        settings=cfg(maximumPositions=3, longSlots=2, shortSlots=1,
                     shortRequiresLongEnabled=True, universeTopN=2),
        uid="u", account={"availableBalance": "1000"},
        positions=[], open_orders=[], timestamp_ms=int(time.time() * 1000), dry_run=True,
    )
    entries = [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert entries, result
    assert entries[0]["symbol"] == "ZECUSDT"
    assert entries[0]["side"] == "LONG"
    assert "ZECUSDT" in result["orphanShortSymbols"]



def test_orphan_long_execution_marks_existing_contract_counterpart_for_capacity_preflight():
    source = (Path(__file__).resolve().parent / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    orphan = source.index("orphan_priority = bool(ranked_row.get(\"orphanShortPriority\"))")
    submit = source.index("existing_contract_counterpart_open=orphan_priority", orphan)
    assert orphan < submit


def test_orphan_long_inherits_existing_short_contract_leverage():
    # Aster leverage is contract-wide. A rescue LONG may not try to rewrite
    # the leverage of an already-open same-symbol SHORT. This reproduces ZEC:
    # existing SHORT at 75x while a tiny fresh leg would otherwise resolve 100x.
    short = pos("ZECUSDT", "SHORT")
    short["leverage"] = "75"
    client = Client(
        positions=[short],
        tickers=[{"symbol":"AAAUSDT","quoteVolume":"999999"}],
        prices={"AAAUSDT":100,"ZECUSDT":100}, leverage=100,
    )
    result = run_multi_bb_step(
        client=client, ref=Ref(), raw_state=state_for("ZECUSDT","SHORT"),
        settings=cfg(maximumPositions=3,longSlots=2,shortSlots=1,
                     shortRequiresLongEnabled=True, universeTopN=2, minimumLeverage=50),
        uid="u", account={"availableBalance":"1000"}, positions=[short],
        open_orders=[], timestamp_ms=int(time.time()*1000), dry_run=True,
    )
    entry = next(row for row in result["actions"] if row.get("kind")=="ENTRY")
    assert entry["symbol"] == "ZECUSDT"
    assert entry["side"] == "LONG"
    assert entry["leverage"] == 75
    assert entry.get("orphanShortPriority") is True
    assert entry.get("pairedContractLeverage") == 75



def test_failed_orphan_priority_does_not_reserve_free_long_seat():
    class BrokenZecLeverageClient(Client):
        def leverage_brackets(self, symbol=None):
            sym = symbol or "AAAUSDT"
            if sym == "ZECUSDT":
                raise RuntimeError("temporary ZEC leverage data failure")
            return super().leverage_brackets(sym)

    short = pos("ZECUSDT", "SHORT")
    short["leverage"] = "75"
    client = BrokenZecLeverageClient(
        positions=[short],
        tickers=[{"symbol": "AAAUSDT", "quoteVolume": "999999"}],
        prices={"ZECUSDT": 100, "AAAUSDT": 100}, leverage=100,
    )
    result = run_multi_bb_step(
        client=client, ref=Ref(), raw_state=state_for("ZECUSDT", "SHORT"),
        settings=cfg(maximumPositions=2, longSlots=1, shortSlots=1,
                     shortRequiresLongEnabled=True, minimumLeverage=50,
                     bollingerEntryFilter15mEnabled=False),
        uid="u", account={"availableBalance": "1000"}, positions=[short],
        open_orders=[], timestamp_ms=int(time.time() * 1000), dry_run=True,
    )
    entries = [a for a in result["actions"] if a.get("kind") == "ENTRY"]
    assert entries, result
    assert entries[0]["symbol"] == "AAAUSDT"
    assert entries[0]["side"] == "LONG"
    assert any(a.get("symbol") == "ZECUSDT" and "leverage-data" in str(a.get("reason", "")) for a in result["actions"])
    assert not any(a.get("reason") == "ORPHAN_LONG_SEAT_RESERVED" for a in result["actions"])
    assert result["orphanLongReservedSlots"] == 0
    assert result["orphanLongReservedRemaining"] == 0


def test_fresh_account_opens_long_first_and_does_not_authorize_same_tick_short():
    result = run(
        settings=cfg(maximumPositions=2, longSlots=1, shortSlots=1, shortRequiresLongEnabled=True),
        tickers=[{"symbol": "AAAUSDT", "quoteVolume": "2000"}, {"symbol": "BBBUSDT", "quoteVolume": "1000"}],
        prices={"AAAUSDT": 100, "BBBUSDT": 100},
    )
    entries = [a for a in result["actions"] if a.get("kind") == "ENTRY"]
    assert entries
    assert entries[0]["side"] == "LONG"
    assert not any(a.get("side") == "SHORT" and a.get("kind") == "ENTRY" for a in result["actions"])
    assert any(a.get("reason") == "SHORT_REQUIRES_LONG" for a in result["actions"])


def test_pairing_truth_refresh_failure_blocks_new_seat_allocation():
    class BrokenTruthClient(Client):
        def position_risk(self, symbol=None):
            raise RuntimeError("exchange position truth unavailable")

    client = BrokenTruthClient(
        tickers=[{"symbol": "AAAUSDT", "quoteVolume": "999999"}],
        prices={"AAAUSDT": 100}, leverage=100,
    )
    result = run_multi_bb_step(
        client=client, ref=Ref(), raw_state={},
        settings=cfg(maximumPositions=2, longSlots=1, shortSlots=1,
                     shortRequiresLongEnabled=True, universeTopN=1),
        uid="u", account={"availableBalance": "1000"},
        positions=[], open_orders=[], timestamp_ms=int(time.time() * 1000), dry_run=True,
    )
    assert not [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert any(row.get("kind") == "ENTRY_SCAN_BLOCKED" and
               row.get("reason") == "PAIRING_POSITION_TRUTH_UNAVAILABLE"
               for row in result["actions"])
