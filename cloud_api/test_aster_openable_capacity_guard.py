from __future__ import annotations

from decimal import Decimal

import pytest

from aster_execution import NewPositionLeverageBlocked, PairExecutionPlan, execute_leg_once
from aster_gateway import PositionSide


class CapacityClient:
    def __init__(self, *, remaining: float, active: bool = False):
        self.remaining = remaining
        self.active = active
        self.capacity_calls = []
        self.margin_calls = []
        self.leverage_calls = []
        self.submit_calls = []

    def remaining_openable_notional_value(self, symbol, leverage):
        self.capacity_calls.append((symbol, leverage))
        return self.remaining

    def leverage_brackets(self, symbol):
        return [{"symbol": symbol, "brackets": [
            {"notionalFloor": "0", "notionalCap": "3000", "initialLeverage": "300", "maintMarginRatio": ".004"}
        ]}]

    def position_risk(self, symbol=None):
        if not self.active:
            return []
        return [{"symbol": symbol or "HYPEUSDT", "positionAmt": "1", "leverage": "300"}]

    def change_margin_type(self, symbol, margin_type):
        self.margin_calls.append((symbol, margin_type))
        return {"code": 200}

    def change_leverage(self, symbol, leverage):
        self.leverage_calls.append((symbol, leverage))
        return {"symbol": symbol, "leverage": leverage}

    def submit_order_once(self, intent, **kwargs):
        self.submit_calls.append(intent)
        return ({"status": "FILLED", "avgPrice": "80", "executedQty": str(intent.quantity)}, False)


def hype_plan(notional: str = "29.60") -> PairExecutionPlan:
    return PairExecutionPlan("HYPEUSDT", Decimal("0.37"), Decimal(notional), 300)


def test_new_exact_entry_checks_openable_capacity_before_any_mutation_or_submit():
    client = CapacityClient(remaining=0)
    with pytest.raises(NewPositionLeverageBlocked) as caught:
        execute_leg_once(client, hype_plan(), side=PositionSide.LONG, action="OPEN",
                         id_prefix="hype-cap", confirm=True, new_position_leverage=300)
    assert caught.value.reason_code == "SYMBOL_OPENABLE_NOTIONAL_BELOW_PLANNED"
    assert client.capacity_calls == [("HYPEUSDT", 300)]
    assert client.margin_calls == []
    assert client.leverage_calls == []
    assert client.submit_calls == []


def test_new_exact_entry_submits_when_openable_capacity_is_sufficient():
    client = CapacityClient(remaining=100)
    result = execute_leg_once(client, hype_plan(), side=PositionSide.LONG, action="OPEN",
                              id_prefix="hype-ok", confirm=True, new_position_leverage=300)
    assert client.capacity_calls == [("HYPEUSDT", 300)]
    assert client.margin_calls == [("HYPEUSDT", "CROSSED")]
    assert client.leverage_calls == [("HYPEUSDT", 300)]
    assert len(client.submit_calls) == 1
    assert result["leverage"] == 300


def test_managed_existing_contract_dca_keeps_existing_path_without_new_entry_capacity_gate():
    client = CapacityClient(remaining=0, active=True)
    result = execute_leg_once(client, hype_plan("15"), side=PositionSide.LONG, action="OPEN",
                              id_prefix="hype-dca", confirm=True, new_position_leverage=300,
                              allow_existing_contract_leverage_change=True)
    assert client.capacity_calls == []
    assert len(client.submit_calls) == 1
    assert result["leverage"] == 300
