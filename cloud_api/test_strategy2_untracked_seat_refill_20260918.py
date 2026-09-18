from __future__ import annotations

import time

import aster_multi_bb
from aster_multi_bb import run_multi_bb_step
from test_aster_multi_bb import Client, Ref, cfg


def _pos(symbol: str, side: str) -> dict:
    return {
        "symbol": symbol,
        "positionSide": side,
        "positionAmt": "1",
        "entryPrice": "100",
        "markPrice": "100",
        "leverage": "100",
    }


def _state(*keys: str) -> dict:
    return {
        "multiBbPositions": {
            key: {
                "cycleId": f"cycle-{i}",
                "dcaCount": 0,
                "lastBotFillPrice": 100,
                "lastKnownQty": 1,
                "lastKnownEntry": 100,
                "cycleStartedAtMs": 1,
                "botManaged": True,
            }
            for i, key in enumerate(keys)
        }
    }


def test_two_free_strategy_seats_refill_even_when_untracked_positions_make_account_count_equal_maximum_positions():
    # Regression for live 2026-09-18: Strategy 2 configured 45 seats, two bot
    # seats were visibly free, but unrelated/open Aster legs made the raw account
    # position count equal maximumPositions. The scanner therefore stopped before
    # scanning candidates even with the Bollinger entry filter disabled.
    positions = [
        _pos("AAUSDT", "LONG"),
        _pos("BBUSDT", "LONG"),
        _pos("CCUSDT", "LONG"),
        # Unrelated opposite-side Aster positions must not consume Strategy-2
        # LONG refill seats or the general bot-seat capacity.
        _pos("MAN1USDT", "SHORT"),
        _pos("MAN2USDT", "SHORT"),
    ]
    raw = _state("AAUSDT|LONG", "BBUSDT|LONG", "CCUSDT|LONG")
    tickers = [
        {"symbol": "NEW1USDT", "quoteVolume": "2000"},
        {"symbol": "NEW2USDT", "quoteVolume": "1000"},
    ]
    prices = {row["symbol"]: 100 for row in positions}
    prices.update({"NEW1USDT": 100, "NEW2USDT": 100})
    client = Client(positions=positions, tickers=tickers, prices=prices, leverage=100)

    result = run_multi_bb_step(
        client=client,
        ref=Ref(),
        raw_state=raw,
        settings=cfg(
            universeTopN=3,
            maximumPositions=5,
            longSlots=5,
            shortSlots=0,
            shortRequiresLongEnabled=False,
            bollingerEntryFilter15mEnabled=False,
        ),
        uid="u",
        account={"availableBalance": "1000"},
        positions=positions,
        open_orders=[],
        timestamp_ms=int(time.time() * 1000),
        dry_run=True,
        order_budget=5,
    )

    entries = [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert [(row["symbol"], row["side"]) for row in entries] == [
        ("NEW1USDT", "LONG"),
        ("NEW2USDT", "LONG"),
    ]
    assert result["strategyPositionCount"] == 5
    assert result["accountPositionCount"] == 7
    assert result["untrackedAccountPositionCount"] == 2
    assert result["remainingLong"] == 0
    assert result["remainingShort"] == 0
    assert result["scannedCandidateCount"] >= 2



def test_untracked_shorts_above_cap_block_new_short_but_still_allow_valid_long_refill():
    positions = []
    tracked_keys = []
    for i in range(4):
        symbol = f"L{i}USDT"
        positions.append(_pos(symbol, "LONG"))
        tracked_keys.append(f"{symbol}|LONG")
    for i in range(12):
        symbol = f"S{i}USDT"
        positions.append(_pos(symbol, "SHORT"))
        if i < 2:
            tracked_keys.append(f"{symbol}|SHORT")

    tickers = [
        {"symbol": "NEW1USDT", "quoteVolume": "3000"},
        {"symbol": "NEW2USDT", "quoteVolume": "2000"},
        {"symbol": "NEW3USDT", "quoteVolume": "1000"},
    ]
    prices = {row["symbol"]: 100 for row in positions}
    prices.update({row["symbol"]: 100 for row in tickers})
    client = Client(positions=positions, tickers=tickers, prices=prices, leverage=100)

    result = run_multi_bb_step(
        client=client,
        ref=Ref(),
        raw_state=_state(*tracked_keys),
        settings=cfg(
            universeTopN=20,
            maximumPositions=14,
            longSlots=7,
            shortSlots=7,
            shortRequiresLongEnabled=False,
            bollingerEntryFilter15mEnabled=False,
        ),
        uid="u",
        account={"availableBalance": "1000"},
        positions=positions,
        open_orders=[],
        timestamp_ms=int(time.time() * 1000),
        dry_run=True,
        order_budget=10,
    )

    entries = [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert [(row["symbol"], row["side"]) for row in entries] == [
        ("NEW1USDT", "LONG"),
        ("NEW2USDT", "LONG"),
        ("NEW3USDT", "LONG"),
    ]
    assert not any(row["side"] == "SHORT" for row in entries)
    assert result["remainingLong"] == 0
    assert result["remainingShort"] == 0


def test_pre_order_exchange_refresh_blocks_short_when_side_reaches_cap_after_scan(monkeypatch):
    initial_positions = [_pos(f"S{i}USDT", "SHORT") for i in range(6)]
    tracked_keys = [f"S{i}USDT|SHORT" for i in range(6)]
    seventh = _pos("EXTERNALUSDT", "SHORT")

    class RefreshingClient(Client):
        def position_risk(self, symbol=None):
            rows = list(self.positions) + [seventh]
            return [row for row in rows if symbol is None or row.get("symbol") == symbol]

    client = RefreshingClient(
        positions=initial_positions,
        tickers=[{"symbol": "NEWUSDT", "quoteVolume": "9999"}],
        prices={**{row["symbol"]: 100 for row in initial_positions}, "EXTERNALUSDT": 100, "NEWUSDT": 100},
        leverage=100,
    )

    def unexpected_execute(*_args, **_kwargs):
        raise AssertionError("new SHORT order must not be submitted once real Aster SHORT count reaches the cap")

    monkeypatch.setattr(aster_multi_bb, "execute_leg_once", unexpected_execute)

    result = run_multi_bb_step(
        client=client,
        ref=Ref(),
        raw_state=_state(*tracked_keys),
        settings=cfg(
            universeTopN=7,
            maximumPositions=7,
            longSlots=0,
            shortSlots=7,
            shortRequiresLongEnabled=False,
            bollingerEntryFilter15mEnabled=False,
        ),
        uid="u",
        account={"availableBalance": "1000"},
        positions=initial_positions,
        open_orders=[],
        timestamp_ms=int(time.time() * 1000),
        dry_run=False,
        order_budget=3,
    )

    assert any(
        row.get("kind") == "ENTRY_SKIP"
        and row.get("side") == "SHORT"
        and row.get("reason") == "SHORT_SLOT_CAP_REACHED"
        and row.get("stage") == "pre_order"
        for row in result["actions"]
    )
    assert not any(row.get("kind") == "ENTRY" for row in result["actions"])


def test_existing_short_dca_still_runs_when_real_short_count_is_above_cap():
    managed = _pos("AAAUSDT", "SHORT")
    managed["markPrice"] = "101"
    extra = [_pos(f"MAN{i}USDT", "SHORT") for i in range(7)]
    positions = [managed, *extra]
    raw = _state("AAAUSDT|SHORT")

    result = run_multi_bb_step(
        client=Client(
            positions=positions,
            prices={row["symbol"]: float(row.get("markPrice", 100)) for row in positions},
            leverage=100,
        ),
        ref=Ref(),
        raw_state=raw,
        settings=cfg(
            universeTopN=7,
            maximumPositions=7,
            longSlots=0,
            shortSlots=7,
            maxDca=3,
            dcaDistance=.003,
            shortRequiresLongEnabled=False,
        ),
        uid="u",
        account={"availableBalance": "1000"},
        positions=positions,
        open_orders=[],
        timestamp_ms=int(time.time() * 1000),
        dry_run=True,
        order_budget=5,
    )

    assert any(
        row.get("kind") == "DCA"
        and row.get("symbol") == "AAAUSDT"
        and row.get("side") == "SHORT"
        for row in result["actions"]
    )
