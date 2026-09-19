from __future__ import annotations

from types import SimpleNamespace
import pytest

import aster_stop_loss
import aster_multi_bb
from aster_stop_loss import StopLossGateResult
from aster_leverage_tiers import resolve_entry
from aster_multi_bb import ENGINE, MultiBbConfig, run_multi_bb_step
from aster_stop_loss import run_stop_loss_gate


def brackets(maximum: int, symbol: str = "AAAUSDT"):
    return [{"symbol": symbol, "brackets": [{
        "notionalFloor": "0", "notionalCap": "1000000",
        "initialLeverage": str(maximum), "maintMarginRatio": ".004",
    }]}]


@pytest.mark.parametrize(
    "pair_max,configured_maximum,expected",
    [(300, None, 300), (300, 50, 50), (300, 75, 75), (60, 75, 60), (50, 75, 50)],
)
def test_maximum_leverage_caps_new_entry_and_none_preserves_legacy(pair_max, configured_maximum, expected):
    result = resolve_entry(
        brackets(pair_max), "AAAUSDT", configured_minimum=50,
        configured_maximum=configured_maximum,
        entry_margin_usd=1, entry_notional_usd=30, entry_sizing_mode="notional",
    )
    assert result["leverage"] == expected


def test_pair_below_minimum_is_rejected_even_with_higher_configured_cap():
    with pytest.raises(Exception, match="minimum 50x"):
        resolve_entry(
            brackets(40), "AAAUSDT", configured_minimum=50, configured_maximum=75,
            entry_margin_usd=1, entry_notional_usd=30, entry_sizing_mode="notional",
        )


def config(**updates):
    raw = {
        "engine": ENGINE, "universeTopN": 1, "maximumPositions": 1,
        "longSlots": 1, "shortSlots": 0, "minimumLeverage": 50,
        "entryMarginUsd": 1, "entryNotionalUsd": 30, "entrySizingMode": "notional",
        "dcaDistance": .003, "dcaMarginUsd": 1, "maxDca": 3, "takeProfit": .015,
    }
    raw.update(updates)
    return MultiBbConfig.from_mapping(raw)


def test_maximum_leverage_config_validation_and_backward_compatibility():
    legacy = config()
    assert legacy.maximum_leverage is None
    assert "maximumLeverage" not in legacy.public_dict()

    same = config(maximumLeverage=50)
    assert same.maximum_leverage == 50
    assert same.public_dict()["maximumLeverage"] == 50

    with pytest.raises(ValueError, match="gelijk aan of hoger"):
        config(maximumLeverage=49)


class _Collection:
    def __init__(self, owner):
        self.owner = owner

    def add(self, row):
        self.owner.audit.append(dict(row))


class _Ref:
    def __init__(self):
        self.updates = []
        self.audit = []

    def set(self, row, merge=True):
        self.updates.append(dict(row))

    def collection(self, _name):
        return _Collection(self)


class _EntryClient:
    def public_exchange_info(self):
        return {"symbols": [{
            "symbol": "AAAUSDT", "quoteAsset": "USDT", "status": "TRADING",
            "filters": [
                {"filterType": "PRICE_FILTER", "minPrice": ".001", "maxPrice": "1000000", "tickSize": ".001"},
                {"filterType": "LOT_SIZE", "minQty": ".001", "maxQty": "1000000", "stepSize": ".001"},
                {"filterType": "MARKET_LOT_SIZE", "minQty": ".001", "maxQty": "1000000", "stepSize": ".001"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        }]}

    def ticker_prices(self):
        return [{"symbol": "AAAUSDT", "price": "100"}]

    def ticker_24h(self):
        return [{"symbol": "AAAUSDT", "quoteVolume": "1000"}]

    def leverage_brackets(self, symbol=None):
        return brackets(300, symbol or "AAAUSDT")

    def position_risk(self, symbol=None):
        return []


def test_dry_run_entry_plan_uses_configured_maximum_not_pair_300x():
    settings = config(maximumLeverage=75)
    result = run_multi_bb_step(
        client=_EntryClient(), ref=_Ref(), raw_state={}, settings=settings, uid="u",
        account={"availableBalance": "100"}, positions=[], open_orders=[],
        timestamp_ms=1_700_000_000_000, dry_run=True,
    )
    entry = next(action for action in result["actions"] if action["kind"] == "ENTRY")
    assert entry["leverage"] == 75


def stop_settings(*, enabled=True, mode="USD", long=5, short=5, profit_lock=False):
    return SimpleNamespace(
        stop_loss_enabled=enabled,
        stop_loss_mode=mode,
        stop_loss_long=float(long),
        stop_loss_short=float(short),
        profit_lock_ladder_enabled=profit_lock,
    )


def position(side="LONG", *, mark=95, entry=100, qty=1, pnl=None, symbol="AAAUSDT"):
    row = {
        "symbol": symbol, "positionSide": side, "positionAmt": str(qty),
        "entryPrice": str(entry), "markPrice": str(mark), "leverage": "50",
    }
    if pnl is not None:
        row["unRealizedProfit"] = str(pnl)
    return row


def state_for(*rows, profit_lock_short=False, asymmetric=False):
    state = {}
    for row in rows:
        key = f"{row['symbol']}|{row['positionSide']}"
        state[key] = {
            "cycleId": f"cycle-{row['symbol']}", "dcaCount": 0,
            "lastKnownQty": abs(float(row["positionAmt"])),
            "lastKnownEntry": float(row["entryPrice"]),
            "cycleStartedAtMs": 1, "botManaged": True,
        }
        if row["positionSide"] == "SHORT" and profit_lock_short:
            state[key]["profitLockHedge"] = True
            state[key]["pairedLongKey"] = f"{row['symbol']}|LONG"
        if asymmetric:
            state[key]["asymmetricHedge"] = True
    return {"multiBbPositions": state}


class _StopClient:
    def __init__(self, rows, open_orders=None):
        self.positions = [dict(row) for row in rows]
        self.orders = list(open_orders or [])

    def position_risk(self, symbol=None):
        return [dict(row) for row in self.positions if symbol is None or row["symbol"] == symbol]

    def open_orders(self):
        return list(self.orders)

    def account_information(self):
        return {"availableBalance": "1000"}


def call_gate(client, raw_state, settings, ref=None, *, dry_run=False, budget=15):
    ref = ref or _Ref()
    result = run_stop_loss_gate(
        client=client, ref=ref, raw_state=raw_state, settings=settings, uid="u",
        account={"availableBalance": "1000"}, positions=client.position_risk(),
        open_orders=client.open_orders(), timestamp_ms=1_700_000_000_000,
        dry_run=dry_run, order_budget=budget,
    )
    return result, ref


def install_full_fill(monkeypatch, calls):
    def fake_execute(client, plan, **kwargs):
        calls.append({"plan": plan, **kwargs})
        side = kwargs["side"].value if hasattr(kwargs["side"], "value") else str(kwargs["side"])
        client.positions = [
            row for row in client.positions
            if not (row["symbol"] == plan.symbol and row["positionSide"] == side)
        ]
        return {"result": {"orderId": f"o-{len(calls)}", "status": "FILLED", "executedQty": str(plan.quantity)}}
    monkeypatch.setattr(aster_stop_loss, "execute_leg_once", fake_execute)


def test_stoploss_off_never_closes_even_at_large_loss(monkeypatch):
    calls = []
    install_full_fill(monkeypatch, calls)
    row = position(mark=10, pnl=-90)
    result, _ = call_gate(_StopClient([row]), state_for(row), stop_settings(enabled=False))
    assert result.handled is False
    assert calls == []


@pytest.mark.parametrize(
    "side,pnl,should_trigger",
    [("LONG", -4.99, False), ("LONG", -5.0, True), ("LONG", -5.01, True),
     ("SHORT", -4.99, False), ("SHORT", -5.0, True), ("SHORT", -5.01, True)],
)
def test_dollar_stoploss_boundaries(monkeypatch, side, pnl, should_trigger):
    calls = []
    install_full_fill(monkeypatch, calls)
    row = position(side=side, mark=95 if side == "LONG" else 105, pnl=pnl)
    result, _ = call_gate(_StopClient([row]), state_for(row), stop_settings(mode="USD", long=5, short=5))
    assert result.handled is should_trigger
    assert bool(calls) is should_trigger


@pytest.mark.parametrize(
    "side,mark,should_trigger",
    [("LONG", 95.01, False), ("LONG", 95.0, True), ("LONG", 94.99, True),
     ("SHORT", 104.99, False), ("SHORT", 105.0, True), ("SHORT", 105.01, True)],
)
def test_percent_stoploss_uses_same_unleveraged_entry_price_basis_as_tp(monkeypatch, side, mark, should_trigger):
    calls = []
    install_full_fill(monkeypatch, calls)
    row = position(side=side, mark=mark)
    result, _ = call_gate(_StopClient([row]), state_for(row), stop_settings(mode="PERCENT", long=5, short=5))
    assert result.handled is should_trigger
    assert bool(calls) is should_trigger


def test_only_triggered_position_closes_when_multiple_independent_positions(monkeypatch):
    calls = []
    install_full_fill(monkeypatch, calls)
    loser = position("LONG", mark=90, symbol="AAAUSDT")
    safe = position("SHORT", mark=101, symbol="BBBUSDT")
    client = _StopClient([loser, safe])
    result, _ = call_gate(client, state_for(loser, safe), stop_settings(mode="PERCENT", long=5, short=5))
    assert result.handled is True
    assert [(call["plan"].symbol, call["side"].value) for call in calls] == [("AAAUSDT", "LONG")]
    assert any(row["symbol"] == "BBBUSDT" for row in client.positions)


def test_open_order_on_triggered_leg_blocks_close_and_other_actions_this_tick(monkeypatch):
    calls = []
    install_full_fill(monkeypatch, calls)
    row = position("LONG", mark=90)
    client = _StopClient([row], [{"symbol": "AAAUSDT", "positionSide": "LONG"}])
    result, _ = call_gate(client, state_for(row), stop_settings(mode="PERCENT", long=5, short=5))
    assert result.handled is True
    assert calls == []
    assert any(a["kind"] == "STOP_LOSS_WAIT" and a["reason"] == "OPEN_ORDER_ON_CYCLE" for a in result.report["actions"])


def test_profit_lock_stoploss_closes_hedge_short_before_long(monkeypatch):
    calls = []
    install_full_fill(monkeypatch, calls)
    long_row = position("LONG", mark=90)
    short_row = position("SHORT", mark=90)
    client = _StopClient([long_row, short_row])
    result, _ = call_gate(
        client, state_for(long_row, short_row, profit_lock_short=True),
        stop_settings(mode="PERCENT", long=5, short=50, profit_lock=True),
    )
    assert result.handled is True
    assert [call["side"].value for call in calls] == ["SHORT", "LONG"]


def test_asymmetric_stoploss_closes_short_before_long(monkeypatch):
    calls = []
    install_full_fill(monkeypatch, calls)
    long_row = position("LONG", mark=90)
    short_row = position("SHORT", mark=90)
    result, _ = call_gate(
        _StopClient([long_row, short_row]), state_for(long_row, short_row, asymmetric=True),
        stop_settings(mode="PERCENT", long=5, short=50),
    )
    assert result.handled is True
    assert [call["side"].value for call in calls] == ["SHORT", "LONG"]


def test_partial_fill_is_reconciled_until_flat(monkeypatch):
    calls = []
    row = position("LONG", mark=90, qty=2)
    client = _StopClient([row])

    def partial_then_full(client_arg, plan, **kwargs):
        calls.append(kwargs["id_prefix"])
        if len(calls) == 1:
            client_arg.positions[0]["positionAmt"] = "1"
            return {"result": {"orderId": "p1", "status": "PARTIALLY_FILLED"}}
        client_arg.positions = []
        return {"result": {"orderId": "p2", "status": "FILLED"}}

    monkeypatch.setattr(aster_stop_loss, "execute_leg_once", partial_then_full)
    result, _ = call_gate(client, state_for(row), stop_settings(mode="PERCENT", long=5, short=5))
    assert result.handled is True
    assert len(calls) == 2
    assert any(a["kind"] == "STOP_LOSS_PARTIAL_FILL" for a in result.report["actions"])
    assert any(a["kind"] == "STOP_LOSS_CLOSED" for a in result.report["actions"])


def test_duplicate_evaluation_after_confirmed_flat_sends_no_second_close(monkeypatch):
    calls = []
    install_full_fill(monkeypatch, calls)
    row = position("LONG", mark=90)
    client = _StopClient([row])
    first, ref = call_gate(client, state_for(row), stop_settings(mode="PERCENT", long=5, short=5))
    assert first.handled is True and len(calls) == 1
    second, _ = call_gate(client, first.raw_state, stop_settings(mode="PERCENT", long=5, short=5), ref)
    assert second.handled is False
    assert len(calls) == 1


def test_error_is_audited_and_position_state_is_retained_for_later_retry(monkeypatch):
    prefixes = []
    row = position("LONG", mark=90)
    client = _StopClient([row])
    raw = state_for(row)

    def fail(_client, _plan, **kwargs):
        prefixes.append(kwargs["id_prefix"])
        raise TimeoutError("exchange timeout")

    monkeypatch.setattr(aster_stop_loss, "execute_leg_once", fail)
    first, ref = call_gate(client, raw, stop_settings(mode="PERCENT", long=5, short=5))
    second, _ = call_gate(client, first.raw_state, stop_settings(mode="PERCENT", long=5, short=5), ref)
    assert first.handled and second.handled
    assert any(a["kind"] == "STOP_LOSS_ERROR" for a in first.report["actions"])
    assert "AAAUSDT|LONG" in first.raw_state["multiBbPositions"]
    assert prefixes[0] == prefixes[1]
    assert any(row["event"] == "MULTI_BB_STOP_LOSS_ERROR" for row in ref.audit)


def test_dry_run_simulates_trigger_without_sending_order(monkeypatch):
    calls = []
    install_full_fill(monkeypatch, calls)
    row = position("SHORT", mark=110)
    result, _ = call_gate(_StopClient([row]), state_for(row), stop_settings(mode="PERCENT", long=5, short=5), dry_run=True)
    assert result.handled is True
    assert result.orders_sent == 0
    assert calls == []
    kinds = [a["kind"] for a in result.report["actions"]]
    assert "STOP_LOSS_TRIGGERED" in kinds
    assert "STOP_LOSS_WOULD_CLOSE" in kinds


def test_stoploss_gate_preempts_portfolio_tp_profit_lock_dca_and_entry(monkeypatch):
    settings = config(stopLossEnabled=True, stopLossMode="PERCENT", stopLossLong=5, stopLossShort=5)
    sentinel = StopLossGateResult(
        True,
        {"status": "EXECUTED", "ordersSent": 1, "actions": [{"kind": "STOP_LOSS_CLOSED"}]},
        {"multiBbPositions": {}}, {"availableBalance": "100"}, [], [], 1,
    )

    monkeypatch.setattr(aster_multi_bb, "run_stop_loss_gate", lambda **_kwargs: sentinel)

    def forbidden(**_kwargs):
        raise AssertionError("later strategy gate must not run after Stoploss handled the tick")

    monkeypatch.setattr(aster_multi_bb, "portfolio_cycle_gate", forbidden)
    monkeypatch.setattr(aster_multi_bb, "run_profit_lock_ladder_gate", forbidden)
    monkeypatch.setattr(aster_multi_bb, "run_smart_rescue_gate", forbidden)

    result = aster_multi_bb.run_multi_bb_step(
        client=object(), ref=_Ref(), raw_state={}, settings=settings, uid="u",
        account={"availableBalance": "100"}, positions=[], open_orders=[],
        timestamp_ms=1_700_000_000_000, dry_run=False, order_budget=5,
    )
    assert result["action"] == "STOP_LOSS"
    assert result["ordersSent"] == 1
