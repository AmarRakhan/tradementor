from aster_dashboard_status import _strategy2_entry_checks
from aster_strategy2 import Strategy2Config


def _base_state(*, margin_ratio: float, drawdown: float, strategy_margin: float = 100.0):
    return {
        "enabled": True,
        "monitor": True,
        "phase": "INITIAL_BUILD",
        "accountSnapshot": {
            "equity": 346.10,
            "marginRatio": margin_ratio,
            "drawdown": drawdown,
            "highWaterMark": 432.0,
            "strategyMargin": strategy_margin,
        },
        "universe": {
            "entryBlocked": False,
            "selectedSymbols": ["BTCUSDT", "ETHUSDT"],
        },
    }


def _strategy_contract():
    return {
        "liveGates": {
            "asterLiveExecution": True,
            "strategyLive": True,
            "runtimeEnabled": True,
            "canaryValidated": True,
            "liveReady": True,
        },
        "schedulerStatus": {"status": "HEALTHY"},
    }


def _checks(state):
    return _strategy2_entry_checks(
        snapshot={"openOrders": 0},
        state=state,
        config=Strategy2Config(mode="live", maximum_pairs=80, base_notional=10, leverage=50),
        strategy=_strategy_contract(),
        active_keys={("BTCUSDT", "LONG")},
        s2_owned={("BTCUSDT", "LONG")},
        s3_owned=set(),
        data_fresh=True,
        counts_consistent=True,
    )


def test_historical_drawdown_does_not_block_fresh_strategy2_entry():
    checks = {row["code"]: row for row in _checks(_base_state(margin_ratio=0.2321, drawdown=0.20))}
    assert checks["STRATEGY2_RISK_MODE"]["status"] == "PASS"
    assert checks["STRATEGY2_BUDGET"]["status"] == "PASS"


def test_actual_emergency_margin_still_blocks_fresh_strategy2_entry():
    checks = {row["code"]: row for row in _checks(_base_state(margin_ratio=0.71, drawdown=0.0))}
    assert checks["STRATEGY2_RISK_MODE"]["status"] == "BLOCK"


def test_strategy2_budget_guard_remains_enforced():
    checks = {row["code"]: row for row in _checks(_base_state(margin_ratio=0.20, drawdown=0.0, strategy_margin=200.0))}
    assert checks["STRATEGY2_RISK_MODE"]["status"] == "PASS"
    assert checks["STRATEGY2_BUDGET"]["status"] == "BLOCK"
