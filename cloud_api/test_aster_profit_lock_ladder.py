from __future__ import annotations

import pytest

from aster_multi_bb import MultiBbConfig, _PairAwareSettings
from aster_profit_lock_ladder import (
    DEFAULT_LEVELS,
    account_summary,
    ladder_decision,
    normalize_levels,
)
from aster_dynamic_hedge_sequence import run_dynamic_hedge_sequence


def pos(symbol: str, side: str, qty: float, mark: float, pnl: float, entry: float | None = None):
    return {
        "symbol": symbol,
        "positionSide": side,
        "positionAmt": str(qty),
        "markPrice": str(mark),
        "entryPrice": str(entry if entry is not None else mark),
        "unRealizedProfit": str(pnl),
        "leverage": "50",
    }


def test_default_is_opt_in_and_legacy_slot_mix_is_unchanged():
    cfg = MultiBbConfig.from_mapping({"maximumPositions": 30, "longSlots": 20, "shortSlots": 10})
    assert cfg.profit_lock_ladder_enabled is False
    assert cfg.long_slots == 20
    assert cfg.short_slots == 10
    assert cfg.profit_lock_levels == DEFAULT_LEVELS
    assert cfg.public_dict()["profitLockLadderEnabled"] is False


def test_enabled_mode_is_runtime_long_only_but_preserves_saved_user_choices():
    cfg = MultiBbConfig.from_mapping({
        "maximumPositions": 30,
        "longSlots": 15,
        "shortSlots": 15,
        "manualSymbolSelectionEnabled": True,
        "manualSymbols": [
            {"symbol": "HYPEUSDT", "side": "SHORT"},
            {"symbol": "BTCUSDT", "side": "LONG"},
        ],
        "profitLockLadderEnabled": True,
    })
    # Stored/public values remain intact so disabling Profit Lock restores them.
    assert cfg.long_slots == 15
    assert cfg.short_slots == 15
    assert cfg.manual_symbols == (("HYPEUSDT", "SHORT"), ("BTCUSDT", "LONG"))
    saved = cfg.public_dict()
    assert saved["longSlots"] == 15
    assert saved["shortSlots"] == 15
    assert saved["manualSymbols"][0]["side"] == "SHORT"
    assert saved["profitLockPrimarySide"] == "LONG"

    # The execution proxy is the hard backend enforcement layer.
    runtime = _PairAwareSettings(cfg)
    assert runtime.long_slots == 30
    assert runtime.short_slots == 0
    assert runtime.manual_symbols == (("HYPEUSDT", "LONG"), ("BTCUSDT", "LONG"))


def test_profit_lock_rejects_asymmetric_primary_hedge_mode():
    with pytest.raises(ValueError, match="Asymmetrische Hedge"):
        MultiBbConfig.from_mapping({
            "maximumPositions": 20,
            "longSlots": 10,
            "shortSlots": 10,
            "asymmetricHedgeModeEnabled": True,
            "profitLockLadderEnabled": True,
        })


def test_ladder_validation_requires_strictly_increasing_levels_and_100_percent_exit():
    levels = normalize_levels([
        {"profitUsd": 2.5, "hedgePercent": 25},
        {"profitUsd": 5, "hedgePercent": 50},
        {"profitUsd": 10, "hedgePercent": 100},
    ])
    assert levels[-1] == (10.0, 100.0)
    with pytest.raises(ValueError, match="strikt oplopen"):
        normalize_levels([{"profitUsd": 5, "hedgePercent": 20}, {"profitUsd": 5, "hedgePercent": 40}, {"profitUsd": 10, "hedgePercent": 100}])
    with pytest.raises(ValueError, match="exact 100%"):
        normalize_levels([{"profitUsd": 5, "hedgePercent": 20}, {"profitUsd": 10, "hedgePercent": 80}])


def test_ladder_uses_total_cycle_profit_not_long_profit_alone():
    long = pos("HYPEUSDT", "LONG", 10, 100, 22)
    short = pos("HYPEUSDT", "SHORT", 2, 100, -3)
    state = {"cycleFees": 1, "profitLockLevelIndex": 0}
    decision = ladder_decision(long_row=long, short_row=short, state=state, levels=DEFAULT_LEVELS)
    # 22 LONG - 3 SHORT - 1 fee = 18; +20 level is not reached yet.
    assert decision["netCycleProfit"] == pytest.approx(18)
    assert decision["reachedLevelIndex"] == 2
    assert decision["targetHedgePercent"] == 60


def test_short_is_a_one_way_ratchet_when_profit_drops():
    long = pos("HYPEUSDT", "LONG", 10, 100, 8)
    short = pos("HYPEUSDT", "SHORT", 4, 100, -2)
    state = {"profitLockLevelIndex": 1, "profitLockHighWaterProfit": 12}
    decision = ladder_decision(long_row=long, short_row=short, state=state, levels=DEFAULT_LEVELS)
    assert decision["action"] == "HOLD"
    assert decision["reason"] == "WAITING_NEXT_NET_PROFIT_LEVEL"
    assert decision["shortNotional"] == pytest.approx(400)
    assert decision["currentHedgePercent"] == pytest.approx(40)


def test_long_dca_can_lower_effective_ratio_without_requesting_short_close():
    # Existing $400 SHORT was 40% against a $1000 LONG. After LONG DCA it is 32%.
    long = pos("HYPEUSDT", "LONG", 12.5, 100, 11)
    short = pos("HYPEUSDT", "SHORT", 4, 100, 0)
    state = {"profitLockLevelIndex": 1, "profitLockHighWaterProfit": 12}
    decision = ladder_decision(long_row=long, short_row=short, state=state, levels=DEFAULT_LEVELS)
    assert decision["currentHedgePercent"] == pytest.approx(32)
    assert decision["action"] == "HOLD"
    # The helper has no REDUCE action by design.
    assert decision["action"] != "REDUCE"


def test_new_profit_level_adds_only_needed_short_and_never_overhedges():
    long = pos("HYPEUSDT", "LONG", 12.5, 100, 21)
    short = pos("HYPEUSDT", "SHORT", 4, 100, -1)
    state = {"profitLockLevelIndex": 1}
    decision = ladder_decision(long_row=long, short_row=short, state=state, levels=DEFAULT_LEVELS)
    assert decision["targetHedgePercent"] == 80
    assert decision["targetShortNotional"] == pytest.approx(1000)
    assert decision["hedgeDeltaNotional"] == pytest.approx(600)
    assert decision["targetShortNotional"] <= decision["longNotional"]


def test_final_level_first_fills_to_100_then_exits_on_confirmed_full_hedge():
    long = pos("HYPEUSDT", "LONG", 10, 100, 30)
    short_80 = pos("HYPEUSDT", "SHORT", 8, 100, -2)
    locking = ladder_decision(long_row=long, short_row=short_80, state={"profitLockLevelIndex": 3}, levels=DEFAULT_LEVELS)
    assert locking["action"] == "INCREASE"
    assert locking["reason"] == "FINAL_100_PERCENT_LEVEL_LOCKING"
    assert locking["targetHedgePercent"] == 100
    assert locking["hedgeDeltaNotional"] == pytest.approx(200)
    assert locking["exitAfterFullHedge"] is True

    short_100 = pos("HYPEUSDT", "SHORT", 10, 100, -2)
    exit_decision = ladder_decision(long_row=long, short_row=short_100, state={"profitLockLevelIndex": 4}, levels=DEFAULT_LEVELS)
    assert exit_decision["action"] == "EXIT"
    assert exit_decision["reason"] == "FINAL_100_PERCENT_LEVEL_REACHED"


def test_existing_overhedge_blocks_risk_increase():
    long = pos("HYPEUSDT", "LONG", 10, 100, 30)
    short = pos("HYPEUSDT", "SHORT", 11, 100, -2)
    decision = ladder_decision(long_row=long, short_row=short, state={}, levels=DEFAULT_LEVELS)
    assert decision["action"] == "BLOCK"
    assert decision["reason"] == "OVER_HEDGED"


def test_portfolio_summary_is_weighted_not_average_of_coin_percentages():
    positions = [
        pos("HYPEUSDT", "LONG", 10, 100, 0),
        pos("HYPEUSDT", "SHORT", 8, 100, 0),
        pos("BTCUSDT", "LONG", 10, 400, 0),
        pos("BTCUSDT", "SHORT", 2, 400, 0),
    ]
    state = {
        "HYPEUSDT|LONG": {"cycleId": "a", "profitLockLevelIndex": 3},
        "HYPEUSDT|SHORT": {"cycleId": "a", "profitLockHedge": True},
        "BTCUSDT|LONG": {"cycleId": "b", "profitLockLevelIndex": 0},
        "BTCUSDT|SHORT": {"cycleId": "b", "profitLockHedge": True},
    }
    summary = account_summary(positions=positions, state=state, levels=DEFAULT_LEVELS, enabled=True)
    # $800 + $800 short / ($1000 + $4000 long) = 32%, not average (80% + 20%) / 2 = 50%.
    assert summary["hedgeCoveragePercent"] == pytest.approx(32)
    assert summary["hedgedPositionCount"] == 2
    assert summary["positionCount"] == 2


def test_dynamic_hedge_yields_short_ownership_to_profit_lock_ladder():
    settings = type("Settings", (), {"profit_lock_ladder_enabled": True})()
    result = run_dynamic_hedge_sequence(
        client=None, control_ref=None, settings=settings, uid="u", account={}, positions=[],
        open_orders=[], timestamp_ms=1, dry_run=False,
    )
    assert result["ordersSent"] == 0
    assert result["reason"] == "HEDGE_STABLE"
    assert result["suppressedByProfitLockLadder"] is True
