"""High-volume deterministic paper test; never imports an exchange adapter."""
import math
import random
from dataclasses import replace

from aster_strategy3 import Strategy3Config, LegState, PortfolioState, decide, net_return, update_trailing_peak


def test_ten_thousand_strategy3_paper_trade_cycles_without_invalid_state():
    rng = random.Random(20260812)
    config = Strategy3Config(
        base_notional=15,
        take_profit=.015,
        long_dca_distance=.02,
        short_dca_distance=.025,
        long_max_dca=10,
        short_max_dca=8,
        leverage=50,
        strategy_budget=.50,
        trailing_enabled=True,
        trailing_activation=.018,
        trailing_distance=.005,
        trailing_min_net_profit=.003,
    ).validated()
    kinds: dict[str, int] = {}
    protection_events = 0
    trailing_events = 0
    simulated_closes = 0
    simulated_dca = 0

    for cycle in range(10_000):
        side = "LONG" if cycle % 2 == 0 else "SHORT"
        entry = 50 + (cycle % 137) / 10
        dca_count = cycle % (config.long_max_dca + 1 if side == "LONG" else config.short_max_dca + 1)
        size = config.base_notional * (1 + dca_count)
        # Repeatable mix of winners, losers, trailing pullbacks and flat ticks.
        signed_move = rng.uniform(-.18, .18)
        current = entry * (1 + signed_move)
        pnl_return = signed_move if side == "LONG" else -signed_move
        peak = max(config.trailing_activation, pnl_return + rng.uniform(0, .02)) if cycle % 7 == 0 else None
        leg = LegState(side, size, entry, current, dca_count=dca_count,
            unrealized_pnl=size*pnl_return, fees=size*.0004, funding=-size*.00005,
            trailing_peak_return=peak)
        stress = cycle % 19 == 0
        portfolio = PortfolioState(
            equity=850 if stress else 1000,
            high_water_mark=1000,
            margin_ratio=.74 if stress else rng.uniform(.05, .32),
            long_exposure=500 if side == "SHORT" and stress else 120,
            short_exposure=500 if side == "LONG" and stress else 120,
            strategy_margin=rng.uniform(0, 250),
        )
        result = decide(config, leg, portfolio, close_fee=size*.0004)
        kinds[result.kind] = kinds.get(result.kind, 0) + 1
        protection_events += int(result.kind in {"ASSIGN_PROTECTION", "PARTIAL_TP"})
        trailing_events += int(result.kind in {"ARM_TRAILING", "TRAILING_TP"})
        simulated_closes += int(result.kind in {"FULL_TP", "PARTIAL_TP", "TRAILING_TP"})
        simulated_dca += int(result.kind == "ADD_DCA")
        assert result.side == side
        assert math.isfinite(result.notional) and result.notional >= 0
        assert math.isfinite(result.retain_notional) and 0 <= result.retain_notional <= size
        assert dca_count <= (config.long_max_dca if side == "LONG" else config.short_max_dca)
        if result.kind == "ARM_TRAILING":
            updated = update_trailing_peak(leg, net_return(leg))
            assert updated.trailing_peak_return is not None and math.isfinite(updated.trailing_peak_return)
        if stress and result.kind in {"ADD_DCA", "TRAILING_TP", "FULL_TP"}:
            raise AssertionError(f"Bescherming had actie {result.kind} in stress moeten blokkeren of aanpassen")

    assert sum(kinds.values()) == 10_000
    assert protection_events > 0
    assert trailing_events > 0
    assert simulated_closes > 0
    assert simulated_dca > 0
    print({"cycles":10_000,"decisions":kinds,"simulatedCloses":simulated_closes,
        "simulatedDca":simulated_dca,"protectionEvents":protection_events,"trailingEvents":trailing_events})
