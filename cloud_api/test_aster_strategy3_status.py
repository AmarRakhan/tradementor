from datetime import datetime, timedelta, timezone
from pathlib import Path

from aster_strategy2_state import OwnedLeg
from aster_strategy3 import PortfolioState, Strategy3Config
from aster_strategy3_status import strategy3_position_tp_contract


def _state(now, **overrides):
    value = {"monitor": True, "enabled": True, "liveReady": True, "canaryValidated": True,
        "runtimeEnabled": True, "phase": "RUNNING", "lastTickAt": now, "lastReason": "Actieve controle"}
    value.update(overrides)
    return value


def _owned(symbol, side, qty, entry, now, *, fees=0.0, funding=0.0, role="HARVEST"):
    return OwnedLeg("aster-strategy-3", "strategy3", symbol, side, "s3-cycle", 7, qty, entry,
        role=role, fees=fees, funding=funding, costs_updated_at_ms=int(now.timestamp() * 1000))


def _portfolio(**overrides):
    values = dict(equity=1000, high_water_mark=1000, margin_ratio=.1,
        long_exposure=100, short_exposure=100, strategy_margin=10)
    values.update(overrides)
    return PortfolioState(**values)


def test_cc_like_negative_position_uses_strategy3_contract_and_costs():
    now = datetime(2026, 8, 14, 19, 0, tzinfo=timezone.utc)
    config = Strategy3Config(mode="live", take_profit=.009)
    owned = _owned("CCUSDT", "LONG", 59.01, 1, now, fees=.03, funding=-.01)
    row = {"symbol": "CCUSDT", "side": "LONG", "quantity": 59.01, "entryPrice": 1,
        "markPrice": 1, "notionalUsd": 59.01, "unrealizedPnl": -.78}
    result = strategy3_position_tp_contract(row=row, owned=owned, config=config,
        state=_state(now), portfolio=_portfolio(), now=now)
    assert result["status"] == "TP nog niet bereikt"
    assert round(result["netProfitUsd"], 6) == round(-.78 - .01 - .03 - 59.01 * .0005, 6)
    assert round(result["takeProfitPercent"], 6) == .9 and result["decision"] in {"HOLD", "ADD_DCA"}
    assert result["blockReason"]


def test_profitable_strategy3_position_uses_persisted_harvest_target():
    now = datetime(2026, 8, 14, 19, 0, tzinfo=timezone.utc)
    config = Strategy3Config.from_mapping({"takeProfit": .011, "mode": "paper"})
    config = Strategy3Config(**{**config.__dict__, "mode": "live"})
    owned = _owned("WINUSDT", "SHORT", 20, 1, now, fees=.02, funding=.01)
    row = {"symbol": "WINUSDT", "side": "SHORT", "quantity": 20, "entryPrice": 1,
        "markPrice": 1, "notionalUsd": 20, "unrealizedPnl": .30}
    result = strategy3_position_tp_contract(row=row, owned=owned, config=config,
        state=_state(now), portfolio=_portfolio(), now=now)
    assert result["status"] == "TP bereikt" and result["decision"] == "FULL_TP"
    assert round(result["takeProfitPercent"], 6) == 1.1 and round(result["takeProfitTargetUsd"], 6) == .22
    assert round(result["netProfitUsd"], 6) == .28


def test_missing_strategy3_ownership_is_fail_closed_and_never_orderable():
    now = datetime(2026, 8, 14, 19, 0, tzinfo=timezone.utc)
    result = strategy3_position_tp_contract(row={"notionalUsd": 20, "unrealizedPnl": 5}, owned=None,
        config=Strategy3Config(mode="live"), state=_state(now), portfolio=_portfolio(), now=now)
    assert result["status"] == "Niet betrouwbaar te bepalen"
    assert result["netProfitUsd"] is None and result["takeProfitTargetUsd"] is None
    assert result["decision"] == "HOLD" and result["ownershipProven"] is False


def test_stale_strategy3_scheduler_warns_but_keeps_complete_amounts():
    now = datetime(2026, 8, 14, 19, 0, tzinfo=timezone.utc)
    owned = _owned("CCUSDT", "LONG", 59.01, 1, now)
    result = strategy3_position_tp_contract(row={"notionalUsd": 59.01, "unrealizedPnl": -.78},
        owned=owned, config=Strategy3Config(mode="live"), state=_state(now - timedelta(minutes=10)),
        portfolio=_portfolio(), now=now)
    assert result["status"] == "TP nog niet bereikt"
    assert result["scheduler"]["status"] == "STALE" and result["scheduler"]["warning"]
    assert result["estimatedCloseFeeUsd"] is not None


def test_missing_portfolio_blocks_only_protection_not_simple_net_tp():
    now = datetime(2026, 8, 14, 19, 0, tzinfo=timezone.utc)
    owned = _owned("WINUSDT", "SHORT", 20, 1, now, fees=.02, funding=.01)
    result = strategy3_position_tp_contract(row={"notionalUsd":20,"unrealizedPnl":.30},
        owned=owned,config=Strategy3Config(mode="live",take_profit=.011),state=_state(now),portfolio=None,now=now)
    assert result["status"]=="TP bereikt" and result["netProfitUsd"] is not None
    assert result["decision"]=="HOLD" and "portfoliostaat" in result["blockReason"]


def test_trailing_and_protection_explain_why_reached_tp_does_not_fully_close():
    now = datetime(2026, 8, 14, 19, 0, tzinfo=timezone.utc)
    trailing = Strategy3Config(mode="live", take_profit=.015, trailing_enabled=True,
        trailing_activation=.02, trailing_distance=.005)
    owned = _owned("TRAILUSDT", "LONG", 100, 1, now)
    row = {"symbol": "TRAILUSDT", "side": "LONG", "quantity": 100, "entryPrice": 1,
        "markPrice": 1, "notionalUsd": 100, "unrealizedPnl": 2.5}
    result = strategy3_position_tp_contract(row=row, owned=owned, config=trailing,
        state=_state(now), portfolio=_portfolio(), trailing_peak_return=.025, now=now)
    assert result["status"] == "TP bereikt" and result["decision"] == "ARM_TRAILING"
    assert result["trailing"]["active"] is True and "Trailing actief" in result["blockReason"]

    protected = strategy3_position_tp_contract(row=row, owned=owned, config=Strategy3Config(mode="live"),
        state=_state(now, phase="PROTECTION"),
        portfolio=_portfolio(equity=900, high_water_mark=1000, margin_ratio=.6,
            long_exposure=50, short_exposure=800), now=now)
    assert protected["decision"] in {"PARTIAL_TP", "ASSIGN_PROTECTION"}
    assert protected["blockReason"]


def test_status_projection_and_history_refresh_are_strictly_read_only():
    status_source = Path(__file__).with_name("aster_strategy3_status.py").read_text()
    assert "aster_gateway" not in status_source and "aster_strategy3_execution" not in status_source
    assert "execute_strategy3_decision" not in status_source and ".set(" not in status_source

    main_source = Path(__file__).with_name("main.py").read_text()
    assert "def _read_strategy3_cost_evidence" not in main_source
    assert "from aster_strategy3_status import" not in main_source
    status_route = main_source[main_source.index('def aster_status('):main_source.index('@app.get("/v1/me/aster/trade-events")')]
    assert 'row["strategy3Tp"]=strategy3_position_tp_contract' not in status_route
    assert "aster_strategy3_reference" not in status_route
