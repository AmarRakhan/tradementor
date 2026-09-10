from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

import aster_dynamic_hedge_execution as engine
from aster_execution import PairExecutionPlan
from aster_gateway import AsterOrderIntent, AsterSubmissionUncertain, AsterValidationError, PositionSide


class FakeSnapshot:
    def __init__(self, data): self.data = deepcopy(data)
    def to_dict(self): return deepcopy(self.data)


class FakeRef:
    def __init__(self, data=None): self.data = deepcopy(data or {}); self.writes = []
    def get(self): return FakeSnapshot(self.data)
    def set(self, value, merge=False):
        if merge: self.data.update(deepcopy(value))
        else: self.data = deepcopy(value)
        self.writes.append(deepcopy(value))


class Settings:
    entry_margin_long_usd = .8
    entry_margin_short_usd = .8
    long_dca_margin_usd = .8
    short_dca_margin_usd = .8
    entry_sizing_mode = "margin"
    entry_notional_usd = 16
    minimum_leverage = 20
    long_slots = 35
    short_slots = 65
    universe_top_n = 100
    manual_symbol_selection_enabled = False
    manual_symbols = ()


def account(equity=300, maintenance=30, available=60):
    return {"totalMarginBalance": equity, "totalWalletBalance": equity,
            "totalUnrealizedProfit": 0, "totalMaintMargin": maintenance,
            "availableBalance": available}


def row(symbol, side, notional, mark=100, leverage=20, pnl=0):
    qty = notional / mark
    return {"symbol": symbol, "positionSide": side,
            "positionAmt": qty if side == "LONG" else -qty,
            "markPrice": mark, "entryPrice": mark, "leverage": leverage,
            "marginType": "cross", "unRealizedProfit": pnl}


class FakeClient:
    def __init__(self, account_value, rows):
        self.account = deepcopy(account_value); self.rows = deepcopy(rows); self.query = {}
    def account_information(self): return deepcopy(self.account)
    def position_risk(self): return deepcopy(self.rows)
    def query_order(self, symbol, client_order_id): return deepcopy(self.query.get((symbol, client_order_id), {}))


def safe_projected():
    return {"currentMarginBufferUsd": 270, "currentBufferRatio": 10,
            "projectedMarginBufferUsd": 250, "projectedBufferRatio": 6,
            "projectedMaintenanceMarginUsd": 45, "projectedEquity": 295}


def test_projected_margin_requires_enough_available_margin():
    brackets = [{"initialLeverage": 20, "notionalFloor": 0, "notionalCap": 10000, "maintMarginRatio": .01}]
    positions = [row("BTCUSDT", "LONG", 1000)]
    assert engine.projected_margin_candidate(account=account(available=.2), positions=positions,
        symbol="ETHUSDT", add_notional_usd=20, leverage=20, bracket_rows=brackets) is None
    ok = engine.projected_margin_candidate(account=account(available=60), positions=positions,
        symbol="ETHUSDT", add_notional_usd=20, leverage=20, bracket_rows=brackets)
    assert ok is not None
    assert ok["projectedMarginBufferUsd"] < 270
    assert ok["requiredAvailableMarginUsd"] > 1


def test_projected_margin_charges_existing_contract_for_tier_jump_conservatively():
    brackets = [
        {"initialLeverage": 50, "notionalFloor": 0, "notionalCap": 1000, "maintMarginRatio": .01},
        {"initialLeverage": 20, "notionalFloor": 1000, "notionalCap": 5000, "maintMarginRatio": .02},
    ]
    positions = [row("BTCUSDT", "LONG", 900, leverage=20)]
    out = engine.projected_margin_candidate(account=account(500, 30, 100), positions=positions,
        symbol="BTCUSDT", add_notional_usd=200, leverage=20, bracket_rows=brackets)
    assert out is not None
    assert round(out["incrementalMaintenanceMarginUsd"], 6) == 13
    assert out["projectedMaintenanceMarginUsd"] == 43


def test_single_intent_open_rejects_unrelated_side_change():
    before = [row("BTCUSDT", "LONG", 1000), row("ETHUSDT", "SHORT", 300)]
    after = [row("BTCUSDT", "LONG", 1000), row("ETHUSDT", "SHORT", 300), row("SOLUSDT", "SHORT", 20)]
    proof = engine.validate_single_intent_delta(before, after, symbol="SOLUSDT", side="SHORT", action="OPEN", expected_quantity=.2)
    assert proof["deltaQuantity"] == .2
    broken = deepcopy(after); broken[0]["positionAmt"] *= .9
    with pytest.raises(RuntimeError):
        engine.validate_single_intent_delta(before, broken, symbol="SOLUSDT", side="SHORT", action="OPEN", expected_quantity=.2)


def test_strategy2_cannot_modify_dynamic_hedge_side():
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    rows = [row("BTCUSDT", "LONG", 1000), row("ETHUSDT", "SHORT", 300)]
    short_open = AsterOrderIntent("test-short", "SOLUSDT", PositionSide.SHORT, Decimal("1"), "OPEN")
    with pytest.raises(AsterValidationError):
        engine.dynamic_strategy_order_guard(ref, short_open, account(), rows)
    long_open = AsterOrderIntent("test-long", "SOLUSDT", PositionSide.LONG, Decimal("1"), "OPEN")
    engine.dynamic_strategy_order_guard(ref, long_open, account(), rows)


def test_strategy2_new_dominant_exposure_is_blocked_when_margin_not_safe():
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    rows = [row("BTCUSDT", "LONG", 1000), row("ETHUSDT", "SHORT", 300)]
    intent = AsterOrderIntent("test-long", "SOLUSDT", PositionSide.LONG, Decimal("1"), "OPEN")
    with pytest.raises(AsterValidationError):
        engine.dynamic_strategy_order_guard(ref, intent, account(100, 60, 20), rows)


def test_overlay_dry_run_plans_one_order_and_sends_nothing(monkeypatch):
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    rows = [row("BTCUSDT", "LONG", 1000), row("ETHUSDT", "SHORT", 100)]
    client = FakeClient(account(500, 20, 100), rows)
    plan = PairExecutionPlan("SOLUSDT", Decimal(".2"), Decimal("20"), 20)
    monkeypatch.setattr(engine, "_plan_add_candidate", lambda *args, **kwargs: {"symbol":"SOLUSDT","side":"SHORT","plan":plan,"projected":safe_projected(),"existing":False})
    out = engine.run_dynamic_hedge_overlay(client=client, control_ref=ref, settings=Settings(), uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[], timestamp_ms=1, dry_run=True, order_budget=1)
    assert out["status"] == "simulated"
    assert out["wouldSendCount"] == 1
    assert out["ordersSent"] == 0
    assert out["action"] == "OPEN_SHORT"


def test_overlay_execution_gate_closed_never_calls_executor(monkeypatch):
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    rows = [row("BTCUSDT", "LONG", 1000), row("ETHUSDT", "SHORT", 100)]
    client = FakeClient(account(500, 20, 100), rows)
    plan = PairExecutionPlan("SOLUSDT", Decimal(".2"), Decimal("20"), 20)
    monkeypatch.setattr(engine, "_plan_add_candidate", lambda *args, **kwargs: {"symbol":"SOLUSDT","side":"SHORT","plan":plan,"projected":safe_projected(),"existing":False})
    monkeypatch.setattr(engine, "execute_leg_once", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not execute")))
    monkeypatch.delenv("ASTER_DYNAMIC_HEDGE_EXECUTION_ENABLED", raising=False)
    out = engine.run_dynamic_hedge_overlay(client=client, control_ref=ref, settings=Settings(), uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[], timestamp_ms=1, order_budget=1)
    assert out["status"] == "paused"
    assert out["ordersSent"] == 0


def test_overlay_live_sends_exactly_one_side_safe_order_then_forces_adoption(monkeypatch):
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    rows = [row("BTCUSDT", "LONG", 1000), row("ETHUSDT", "SHORT", 100)]
    client = FakeClient(account(500, 20, 100), rows)
    plan = PairExecutionPlan("SOLUSDT", Decimal(".2"), Decimal("20"), 20)
    monkeypatch.setattr(engine, "_plan_add_candidate", lambda *args, **kwargs: {"symbol":"SOLUSDT","side":"SHORT","plan":plan,"projected":safe_projected(),"existing":False})
    calls = []
    def execute(_client, _plan, **kwargs):
        calls.append(kwargs)
        client.rows.append(row("SOLUSDT", "SHORT", 20))
        return {"result": {"status": "FILLED"}}
    monkeypatch.setattr(engine, "execute_leg_once", execute)
    monkeypatch.setenv("ASTER_DYNAMIC_HEDGE_EXECUTION_ENABLED", "true")
    out = engine.run_dynamic_hedge_overlay(client=client, control_ref=ref, settings=Settings(), uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[], timestamp_ms=1, order_budget=1)
    assert out["ordersSent"] == 1
    assert len(calls) == 1
    assert calls[0]["side"] is PositionSide.SHORT
    assert ref.data["ownershipState"] == "ADOPTING"
    assert ref.data["pendingIntent"] == {}
    assert ref.data["lastExecutionProof"]["side"] == "SHORT"


def test_uncertain_submit_is_locked_and_not_retried(monkeypatch):
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    rows = [row("BTCUSDT", "LONG", 1000), row("ETHUSDT", "SHORT", 100)]
    client = FakeClient(account(500, 20, 100), rows)
    plan = PairExecutionPlan("SOLUSDT", Decimal(".2"), Decimal("20"), 20)
    monkeypatch.setattr(engine, "_plan_add_candidate", lambda *args, **kwargs: {"symbol":"SOLUSDT","side":"SHORT","plan":plan,"projected":safe_projected(),"existing":False})
    monkeypatch.setattr(engine, "execute_leg_once", lambda *args, **kwargs: (_ for _ in ()).throw(AsterSubmissionUncertain("503 uncertain")))
    monkeypatch.setenv("ASTER_DYNAMIC_HEDGE_EXECUTION_ENABLED", "true")
    out = engine.run_dynamic_hedge_overlay(client=client, control_ref=ref, settings=Settings(), uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[], timestamp_ms=1, order_budget=1)
    assert out["status"] == "uncertain"
    assert ref.data["ownershipState"] == "MANUAL_ACTION_LOCK"
    assert ref.data["pendingIntent"]["clientOrderId"]
