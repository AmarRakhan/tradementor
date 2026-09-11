from __future__ import annotations

import inspect

import aster_dynamic_hedge_execution as engine


class Snap:
    def __init__(self, value): self.value = value
    def to_dict(self): return dict(self.value)


class Ref:
    def __init__(self, value): self.value = dict(value)
    def get(self): return Snap(self.value)
    def set(self, value, merge=False): self.value = {**self.value, **value} if merge else dict(value)


class Settings: pass


def account(equity=300, maintenance=30, available=50):
    return {"totalMarginBalance": equity, "totalWalletBalance": equity,
            "totalUnrealizedProfit": 0, "totalMaintMargin": maintenance,
            "availableBalance": available}


def row(symbol, side, notional, pnl=1):
    mark = 100; qty = notional / mark
    return {"symbol": symbol, "positionSide": side,
            "positionAmt": qty if side == "LONG" else -qty,
            "markPrice": mark, "entryPrice": mark, "leverage": 20,
            "marginType": "cross", "unRealizedProfit": pnl}


class Client:
    def __init__(self, rows, acc=None): self.rows=list(rows);self.acc=acc or account();self.query={}
    def position_risk(self): return list(self.rows)
    def account_information(self): return dict(self.acc)
    def query_order(self, symbol, client_id): return dict(self.query.get((symbol,client_id),{}))


def test_reduction_planner_has_maximum_notional_guard():
    assert "maximum_notional_usd" in inspect.signature(engine._plan_profitable_reduction).parameters
    client = Client([row("ETHUSDT", "SHORT", 150)])
    assert engine._plan_profitable_reduction(client, "u", client.rows, "SHORT", "test", maximum_notional_usd=100) is None


def test_over_target_reduction_is_capped_at_excess_notional(monkeypatch):
    rows=[row("BTCUSDT","LONG",1000),row("ETHUSDT","SHORT",500)]
    client=Client(rows)
    ref=Ref({"enabled":True,"ownershipState":"DYNAMIC_HEDGE_ACTIVE"})
    captured={}
    def planner(*args, **kwargs):
        captured.update(kwargs);return None
    monkeypatch.setattr(engine,"_plan_profitable_reduction",planner)
    out=engine.run_dynamic_hedge_overlay(client=client,control_ref=ref,settings=Settings(),uid="u",
        account=client.account_information(),positions=client.position_risk(),open_orders=[],timestamp_ms=1,dry_run=True,order_budget=1)
    assert out["reason"]=="HEDGE_ABOVE_DYNAMIC_TARGET"
    assert round(captured["maximum_notional_usd"],8)==100


def test_pending_dynamic_intent_reconciles_before_manual_lock_state_gate():
    rows=[row("BTCUSDT","LONG",1000),row("SOLUSDT","SHORT",20)]
    client=Client(rows)
    ref=Ref({"enabled":True,"ownershipState":"MANUAL_ACTION_LOCK","pendingIntent":{
        "clientOrderId":"dh-test-open-short","symbol":"SOLUSDT","side":"SHORT","action":"OPEN",
        "quantity":.2,"beforeQuantity":0,"notionalUsd":20,
    }})
    out=engine.run_dynamic_hedge_overlay(client=client,control_ref=ref,settings=Settings(),uid="u",
        account=client.account_information(),positions=client.position_risk(),open_orders=[],timestamp_ms=1,dry_run=False,order_budget=1)
    assert out["status"]=="reconciled"
    assert ref.value["ownershipState"]=="ADOPTING"
    assert ref.value["pendingIntent"]=={}
