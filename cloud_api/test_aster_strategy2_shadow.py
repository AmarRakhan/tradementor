import random

import pytest

from aster_strategy2 import PortfolioState, Strategy2Config
from aster_strategy2_queue import PendingReopen
from aster_strategy2_shadow import (
    ReadOnlyShadowBoundary,
    ShadowInputs,
    ShadowMutationBlocked,
    plan_validated_shadow,
)
from aster_strategy2_state import OwnedLeg


def leg(symbol, side, index, *, entry=100.0, fees=0.0, funding=0.0, dca=0):
    return OwnedLeg(
        "aster-strategy-2", "strategy2", symbol, side, f"cycle-{index}", 1,
        1.0, entry, dca_count=dca, fees=fees, funding=funding,
        costs_updated_at_ms=1,
    )


def position(symbol, side, mark, pnl):
    return {"symbol": symbol, "positionSide": side, "positionAmt": "1",
            "entryPrice": "100", "markPrice": str(mark),
            "unRealizedProfit": str(pnl), "leverage": "10"}


def portfolio(**changes):
    values = dict(equity=10_000, adjusted_high_water_mark=10_000,
                  margin_ratio=.10, long_exposure=100, short_exposure=100,
                  strategy_exposure=200, strategy_margin=20,
                  available_balance=5_000)
    values.update(changes)
    return PortfolioState(**values)


def test_shadow_boundary_blocks_every_external_mutation_class():
    guard = ReadOnlyShadowBoundary()
    for call in (guard.persist, guard.submit_order, guard.change_leverage):
        with pytest.raises(ShadowMutationBlocked):
            call("anything")


def test_shadow_orders_risk_then_profit_then_carried_pending_reopen_and_caps_at_fifteen():
    config = Strategy2Config(mode="live", base_notional=25, take_profit=.005,
                             maximum_pairs=20, long_dca_distance=.02)
    owned = (
        leg("PROTECTUSDT", "LONG", 0),
        leg("PROFITUSDT", "LONG", 1),
        leg("DCAUSDT", "LONG", 2, dca=0),
    )
    positions = (
        position("PROTECTUSDT", "LONG", 90, -10),
        position("PROFITUSDT", "LONG", 110, 10),
        position("DCAUSDT", "LONG", 95, -5),
    )
    pending = (PendingReopen("REOPENUSDT", "SHORT", "closed", "package", 25, "prior"),)
    value = ShadowInputs(
        "account", "scan", config,
        portfolio(equity=1000, adjusted_high_water_mark=1000,
                  margin_ratio=.71, long_exposure=2000, short_exposure=0),
        owned, positions, pending,
        tuple(f"E{i}USDT" for i in range(30)),
    )
    plan = plan_validated_shadow(value)
    assert plan["externalWrites"] == plan["exchangeSubmissions"] == 0
    assert plan["wouldSendCount"] <= 15
    assert plan["actions"][0]["kind"] == "RISK_REDUCE"
    assert plan["actions"][1]["kind"] == "TAKE_PROFIT_CLOSE"
    assert plan["actions"][2]["kind"] == "REOPEN"


def test_shadow_orders_profit_before_dca_before_new_entries():
    config = Strategy2Config(mode="live", base_notional=25, take_profit=.005,
                             maximum_pairs=20, long_dca_distance=.02)
    owned = (leg("PROFITUSDT", "LONG", 1), leg("DCAUSDT", "LONG", 2))
    positions = (position("PROFITUSDT", "LONG", 110, 10),
                 position("DCAUSDT", "LONG", 95, -5))
    plan = plan_validated_shadow(ShadowInputs(
        "account", "scan", config, portfolio(), owned, positions,
        entry_symbols=("NEWUSDT",),
    ))
    kinds = [item["kind"] for item in plan["actions"]]
    assert kinds == ["TAKE_PROFIT_CLOSE", "DCA", "OPEN_BASE"]


def test_uncertain_shadow_fails_closed_with_zero_actions():
    value = ShadowInputs("account", "scan", Strategy2Config(), portfolio(), (), (),
                         entry_symbols=("BTCUSDT",), halted_uncertain=True)
    plan = plan_validated_shadow(value)
    assert plan["wouldSendCount"] == 0 and plan["actions"] == []


def test_ten_thousand_validated_shadows_never_mutate_or_exceed_budget():
    rng = random.Random(20260819)
    for index in range(10_000):
        owned = tuple(leg(f"C{x}USDT", "LONG" if x % 2 == 0 else "SHORT", x)
                      for x in range(rng.randrange(0, 20)))
        positions = tuple(position(x.symbol, x.side, 100 + rng.randrange(-10, 11),
                                   rng.randrange(-20, 21)) for x in owned)
        value = ShadowInputs(
            f"account-{index % 4}", f"scan-{index}",
            Strategy2Config(maximum_pairs=100), portfolio(), owned, positions,
            entry_symbols=tuple(f"E{x}USDT" for x in range(30)),
            orders_used=rng.randrange(0, 16),
            halted_uncertain=rng.randrange(0, 500) == 0,
        )
        before = repr(value)
        plan = plan_validated_shadow(value)
        assert repr(value) == before
        assert plan["wouldSendCount"] <= 15 - value.orders_used
        assert plan["externalWrites"] == plan["exchangeSubmissions"] == 0
