from __future__ import annotations

import time

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
        _pos("CCUSDT", "SHORT"),
        _pos("MAN1USDT", "LONG"),
        _pos("MAN2USDT", "SHORT"),
    ]
    raw = _state("AAUSDT|LONG", "BBUSDT|LONG", "CCUSDT|SHORT")
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
            longSlots=4,
            shortSlots=1,
            shortRequiresLongEnabled=True,
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
