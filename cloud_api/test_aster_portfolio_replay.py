from aster_portfolio_replay import ReplayCandle, ReplaySeed, comparison_conclusion, config_with_overrides, run_portfolio_replay
from aster_strategy2 import Strategy2Config


def candles(prices):
    return [ReplayCandle((i + 1) * 60_000, value, value * 1.04, value * .96, value) for i, value in enumerate(prices)]


def test_identical_inputs_are_identical_and_no_live_adapter_exists():
    config = Strategy2Config.from_mapping({"takeProfit": .015, "baseNotional": 15, "leverage": 20, "strategyBudget": .8})
    args = dict(candles={"BTCUSDT": candles([100, 101, 102, 103])}, seeds=[ReplaySeed("BTCUSDT", "LONG", 60_000)], config=config, start_equity=400, comparison_at_ms=999_999)
    assert run_portfolio_replay(**args) == run_portfolio_replay(**args)


def test_open_positions_are_marked_to_market():
    config = Strategy2Config.from_mapping({"takeProfit": .20, "baseNotional": 100, "leverage": 10, "strategyBudget": .8})
    result = run_portfolio_replay(candles={"BTCUSDT": candles([100, 90])}, seeds=[ReplaySeed("BTCUSDT", "LONG", 60_000)], config=config, start_equity=400, comparison_at_ms=999_999, fee_rate=0, slippage_rate=0)
    assert result["closedTrades"] == 0
    assert result["openPositions"] == 1
    assert result["unrealizedPnl"] < 0
    assert result["endingPortfolio"] < 400


def test_only_requested_override_changes():
    base = Strategy2Config.from_mapping({"takeProfit": .015, "baseNotional": 15, "leverage": 50})
    changed = config_with_overrides(base, {"takeProfit": .03})
    assert changed.take_profit == .03
    assert changed.base_notional == base.base_notional
    assert changed.leverage == base.leverage


def test_reference_deviation_blocks_hard_winner():
    row = {"endingPortfolio": 470}
    conclusion = comparison_conclusion(live_equity=400, reference=row, test_a={"endingPortfolio": 500}, test_b={"endingPortfolio": 480})
    assert conclusion["reliable"] is False
    assert conclusion["winner"] is None


def test_matching_reference_allows_winner():
    conclusion = comparison_conclusion(live_equity=444, reference={"endingPortfolio": 443}, test_a={"endingPortfolio": 478, "closedResultToday": 12, "maintenancePct": 20}, test_b={"endingPortfolio": 450}, live_closed_today=8, live_maintenance_pct=25)
    assert conclusion["reliable"] is True
    assert conclusion["winner"] == "Test A"
    assert conclusion["primaryMetric"] == "endingPortfolio"
    assert "gesloten resultaat vandaag" in conclusion["text"].lower()
    assert "maintenance" in conclusion["text"].lower()


def test_five_percent_variant_ignores_one_and_half_percent_target():
    series = [
        ReplayCandle(60_000, 100, 102, 99, 101),
        ReplayCandle(120_000, 101, 102, 100, 101),
    ]
    common = dict(candles={"BTCUSDT": series}, seeds=[ReplaySeed("BTCUSDT", "LONG", 60_000)], start_equity=400, comparison_at_ms=999_999, fee_rate=0, slippage_rate=0)
    low_tp = run_portfolio_replay(config=Strategy2Config.from_mapping({"takeProfit": .015, "baseNotional": 100, "autoRestart": False}), **common)
    high_tp = run_portfolio_replay(config=Strategy2Config.from_mapping({"takeProfit": .05, "baseNotional": 100, "autoRestart": False}), **common)
    assert low_tp["closedTrades"] == 1
    assert high_tp["closedTrades"] == 0
    assert high_tp["openPositions"] == 1


def test_high_tp_variant_can_dca_after_price_previously_crossed_low_tp():
    series = [
        ReplayCandle(60_000, 100, 102, 99, 101),
        ReplayCandle(120_000, 101, 101, 97, 98),
    ]
    config = Strategy2Config.from_mapping({"takeProfit": .05, "baseNotional": 100, "longDcaDistance": .02, "longMaxDca": 3, "strategyBudget": .9, "leverage": 10})
    result = run_portfolio_replay(candles={"BTCUSDT": series}, seeds=[ReplaySeed("BTCUSDT", "LONG", 60_000)], config=config, start_equity=400, comparison_at_ms=999_999, fee_rate=0, slippage_rate=0)
    assert result["closedTrades"] == 0
    assert result["dcaOrders"] == 1
    assert result["openPositions"] == 1


def test_three_primary_metrics_are_calculated():
    series = [
        ReplayCandle(60_000, 100, 102, 99, 101),
        ReplayCandle(120_000, 101, 102, 100, 101),
    ]
    config = Strategy2Config.from_mapping({"takeProfit": .015, "baseNotional": 100, "autoRestart": False})
    result = run_portfolio_replay(candles={"BTCUSDT": series}, seeds=[ReplaySeed("BTCUSDT", "LONG", 60_000)], config=config, start_equity=400, comparison_at_ms=999_999, fee_rate=0, slippage_rate=0, day_start_ms=30_000, maintenance_rate=.01)
    assert result["endingPortfolio"] > 400
    assert result["closedResultToday"] > 0
    assert result["maintenancePct"] == 0
    open_result = run_portfolio_replay(candles={"BTCUSDT": series}, seeds=[ReplaySeed("BTCUSDT", "LONG", 60_000)], config=Strategy2Config.from_mapping({"takeProfit": .20, "baseNotional": 100}), start_equity=400, comparison_at_ms=999_999, fee_rate=0, slippage_rate=0, day_start_ms=30_000, maintenance_rate=.01)
    assert open_result["maintenancePct"] > 0
    assert open_result["maxMaintenancePct"] > 0
