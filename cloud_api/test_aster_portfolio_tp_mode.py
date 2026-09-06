from __future__ import annotations

from dataclasses import dataclass

import pytest

from aster_gateway import PositionSide
from aster_multi_bb import MultiBbConfig, _PairAwareSettings, effective_pair_settings
from aster_multi_bb_portfolio import (
    FLAT_CONFIRMED,
    PORTFOLIO_TP_EXECUTING,
    PortfolioCycleOrderBlocked,
    assert_order_allowed,
    ensure_cycle,
    exchange_equity,
    portfolio_cycle_gate,
    target_equity,
)


class Snapshot:
    def __init__(self, data):
        self._data = data
    def to_dict(self):
        return self._data


class Audit:
    def __init__(self, ref): self.ref = ref
    def add(self, value): self.ref.audit.append(value)


class Ref:
    def __init__(self, raw=None):
        self.data = dict(raw or {})
        self.audit = []
    def get(self): return Snapshot(dict(self.data))
    def set(self, value, merge=False):
        if merge: self.data.update(value)
        else: self.data = dict(value)
    def collection(self, _name): return Audit(self)


class FakeClient:
    def __init__(self, *, equity=1000.0, positions=None, orders=None, enabled=True, partial_once=False):
        self.equity = equity
        self.positions = list(positions or [])
        self.orders = list(orders or [])
        self.partial_once = partial_once
        self.submissions = []
        self.cancellations = []
        self.enabled = enabled
    def account_information(self):
        return {"totalMarginBalance": str(self.equity), "availableBalance": str(self.equity)}
    def position_risk(self, symbol=None):
        rows = self.positions
        if symbol: rows = [x for x in rows if x["symbol"] == symbol]
        return [dict(x) for x in rows]
    def open_orders(self, symbol=None):
        rows = self.orders
        if symbol: rows = [x for x in rows if x["symbol"] == symbol]
        return [dict(x) for x in rows]
    def cancel_order(self, symbol, *, order_id=None, client_order_id=None):
        self.cancellations.append((symbol, order_id, client_order_id))
        self.orders = [x for x in self.orders if str(x.get("orderId")) != str(order_id) and str(x.get("clientOrderId")) != str(client_order_id)]
        return {"status": "CANCELED"}
    def submit_order_once(self, intent, **_kwargs):
        self.submissions.append(intent)
        qty = float(intent.quantity)
        for index, row in enumerate(list(self.positions)):
            if row["symbol"] != intent.symbol or row["positionSide"] != intent.position_side.value:
                continue
            if intent.action == "CLOSE":
                if self.partial_once:
                    self.partial_once = False
                    remaining = max(0.0, abs(float(row["positionAmt"])) - qty / 2)
                    self.positions[index] = {**row, "positionAmt": str(remaining)}
                    return ({"status": "FILLED", "executedQty": str(qty / 2), "avgPrice": row["markPrice"], "orderId": len(self.submissions)}, False)
                self.positions.pop(index)
                self.equity += 17.42
                return ({"status": "FILLED", "executedQty": str(qty), "avgPrice": row["markPrice"], "orderId": len(self.submissions)}, False)
        return ({"status": "FILLED", "executedQty": str(qty), "avgPrice": "1", "orderId": len(self.submissions)}, False)


def pos(symbol, side, qty=1, entry=100, mark=101):
    return {"symbol": symbol, "positionSide": side, "positionAmt": str(qty), "entryPrice": str(entry), "markPrice": str(mark), "leverage": "50"}


def config(**extra):
    raw = {"engine": "multi_bb_v1", "universeTopN": 30, "maximumPositions": 20,
           "longSlots": 10, "shortSlots": 10, "minimumLeverage": 50,
           "entryMarginUsd": 5, "entryNotionalUsd": 250, "entrySizingMode": "margin",
           "dcaDistance": .003, "dcaMarginUsd": 2, "maxDca": 15,
           "takeProfit": .015, "takeProfitEnabled": True}
    raw.update(extra)
    return MultiBbConfig.from_mapping(raw)


def _read(proxy, symbol, side):
    key = f"{symbol}|{side}"
    row = {"symbol": symbol, "positionSide": side}
    return proxy.dca_distance, proxy.dca_margin_usd, proxy.max_dca, proxy.take_profit, proxy.take_profit_enabled


def test_backward_compatibility_shared_values_migrate_to_both_sides():
    cfg = config(dcaDistance=.004, dcaMarginUsd=3.5, maxDca=9, takeProfit=.025)
    assert cfg.take_profit_mode == "PER_TRADE"
    assert cfg.long_dca_distance == cfg.short_dca_distance == .004
    assert cfg.long_dca_margin_usd == cfg.short_dca_margin_usd == 3.5
    assert cfg.max_dca_long == cfg.max_dca_short == 9
    assert cfg.long_take_profit_value == cfg.short_take_profit_value == .025


def test_legacy_disabled_tp_migrates_to_off():
    cfg = config(takeProfitEnabled=False)
    assert cfg.take_profit_mode == "OFF"


def test_long_short_config_are_independent():
    cfg = config(longDcaDistance=.003, shortDcaDistance=.03,
                 longDcaMarginUsd=2, shortDcaMarginUsd=7,
                 maxDcaLong=15, maxDcaShort=4,
                 longTakeProfitValue=.015, shortTakeProfitValue=.10)
    assert (cfg.long_dca_distance, cfg.short_dca_distance) == (.003, .03)
    assert (cfg.long_dca_margin_usd, cfg.short_dca_margin_usd) == (2, 7)
    assert (cfg.max_dca_long, cfg.max_dca_short) == (15, 4)
    assert (cfg.long_take_profit_value, cfg.short_take_profit_value) == (.015, .10)


def test_pair_override_side_precedence_and_reset_fallback():
    cfg = config(longDcaDistance=.003, shortDcaDistance=.03,
                 pairOverrides={"ETHUSDT": {"longDcaDistance": .006, "shortDcaDistance": .04,
                                             "maxDcaLong": 20, "maxDcaShort": 6,
                                             "longTakeProfitValue": .02, "shortTakeProfitValue": .12}})
    eth = effective_pair_settings(cfg, "ETH/USDT")
    btc = effective_pair_settings(cfg, "BTCUSDT")
    assert (eth["longDcaDistance"], eth["shortDcaDistance"]) == (.006, .04)
    assert (eth["maxDcaLong"], eth["maxDcaShort"]) == (20, 6)
    assert (eth["longTakeProfitValue"], eth["shortTakeProfitValue"]) == (.02, .12)
    assert (btc["longDcaDistance"], btc["shortDcaDistance"]) == (.003, .03)


def test_mode_portfolio_and_off_disable_individual_tp_without_losing_values():
    for mode in ("PORTFOLIO", "OFF"):
        cfg = config(takeProfitMode=mode, longTakeProfitValue=.015, shortTakeProfitValue=.10)
        assert cfg.public_dict()["longTakeProfitValue"] == .015
        assert cfg.public_dict()["shortTakeProfitValue"] == .10
        proxy = _PairAwareSettings(cfg)
        # Direct no-stack lookup proves the global gate itself is off; runtime
        # side selection is covered by effective settings above/core tests.
        assert proxy.take_profit_enabled is False


def test_target_is_always_original_cycle_baseline():
    raw = {"multiBbCycle": {"cycleId": "abc", "cycleStartEquity": 1000, "cycleStatus": "RUNNING"}}
    cycle, created = ensure_cycle(raw, uid="u", current_equity=1120, portfolio_tp_percent=20, timestamp_ms=2)
    assert created is False
    assert cycle["cycleStartEquity"] == 1000
    assert cycle["targetEquity"] == pytest.approx(1200)
    assert target_equity(1000, 20) == pytest.approx(1200)
    assert target_equity(1120, 20) == pytest.approx(1344)  # explicitly not used for this cycle


def test_cycle_baseline_is_created_even_in_per_trade_mode():
    raw = {"enabled": True, "multiBbPositions": {}}
    ref = Ref(raw)
    client = FakeClient(equity=1000)
    result = portfolio_cycle_gate(client=client, ref=ref, raw_state=raw, uid="u", account=client.account_information(),
        positions=[], open_orders=[], timestamp_ms=1, take_profit_mode="PER_TRADE", portfolio_tp_percent=20)
    assert result.handled is False
    assert ref.data["multiBbCycle"]["cycleStartEquity"] == 1000


def test_switch_to_portfolio_above_original_target_triggers_immediately():
    raw = {"enabled": True, "multiBbCycle": {"cycleId": "abc", "cycleStartEquity": 1000, "cycleStatus": "RUNNING"}}
    ref = Ref(raw)
    client = FakeClient(equity=1215)
    result = portfolio_cycle_gate(client=client, ref=ref, raw_state=raw, uid="u", account=client.account_information(),
        positions=[], open_orders=[], timestamp_ms=5, take_profit_mode="PORTFOLIO", portfolio_tp_percent=20)
    assert result.handled is True
    assert result.restart is True
    assert ref.audit[0]["event"] == "PORTFOLIO_TP_TRIGGERED"
    assert ref.data["multiBbLastCompletedCycle"]["cycleStartEquity"] == 1000


def test_portfolio_exit_cancels_bot_orders_closes_all_sides_and_restarts_from_real_equity():
    raw = {"enabled": True, "multiBbCycle": {"cycleId": "abc", "cycleStartEquity": 1000, "cycleStatus": "RUNNING"},
           "multiBbPositions": {"BTCUSDT|LONG": {"dcaCount": 15}, "ETHUSDT|SHORT": {"dcaCount": 4}}}
    ref = Ref(raw)
    client = FakeClient(equity=1200, positions=[pos("BTCUSDT", "LONG"), pos("ETHUSDT", "SHORT")],
                        orders=[{"symbol": "BTCUSDT", "orderId": 9, "clientOrderId": "mbb-dca-old"},
                                {"symbol": "ETHUSDT", "orderId": 10, "clientOrderId": "manual-order"}])
    result = portfolio_cycle_gate(client=client, ref=ref, raw_state=raw, uid="u", account=client.account_information(),
        positions=client.position_risk(), open_orders=client.open_orders(), timestamp_ms=100,
        take_profit_mode="PORTFOLIO", portfolio_tp_percent=20, order_budget=15)
    assert result.handled and result.restart
    assert {intent.position_side for intent in client.submissions} == {PositionSide.LONG, PositionSide.SHORT}
    assert client.positions == []
    assert any(x[1] == 9 for x in client.cancellations)
    # The manual order is deliberately not cancelled by bot cleanup.
    assert any(x.get("clientOrderId") == "manual-order" for x in client.orders)
    completed = ref.data["multiBbLastCompletedCycle"]
    assert completed["cycleEndEquity"] == pytest.approx(1234.84)
    assert ref.data["multiBbCycle"]["cycleStartEquity"] == pytest.approx(1234.84)
    assert ref.data["multiBbCycle"]["cycleStartEquity"] != 1200
    assert ref.data["multiBbPositions"] == {}


def test_partial_close_does_not_restart_before_exchange_flat():
    raw = {"enabled": True, "multiBbCycle": {"cycleId": "abc", "cycleStartEquity": 1000,
           "cycleStatus": PORTFOLIO_TP_EXECUTING}}
    ref = Ref(raw)
    client = FakeClient(equity=1210, positions=[pos("BTCUSDT", "LONG", qty=2)], partial_once=True)
    first = portfolio_cycle_gate(client=client, ref=ref, raw_state=raw, uid="u", account=client.account_information(),
        positions=client.position_risk(), open_orders=[], timestamp_ms=1, take_profit_mode="PORTFOLIO", portfolio_tp_percent=20)
    assert first.handled and not first.restart
    assert client.positions
    assert ref.data["multiBbCycle"]["cycleStatus"] == "FLAT_CONFIRMING"
    second_raw = ref.get().to_dict()
    second = portfolio_cycle_gate(client=client, ref=ref, raw_state=second_raw, uid="u", account=client.account_information(),
        positions=client.position_risk(), open_orders=[], timestamp_ms=2, take_profit_mode="PORTFOLIO", portfolio_tp_percent=20)
    assert second.handled and second.restart
    assert client.positions == []


def test_bot_off_finishes_exit_but_does_not_restart():
    raw = {"enabled": False, "multiBbCycle": {"cycleId": "abc", "cycleStartEquity": 1000,
           "cycleStatus": PORTFOLIO_TP_EXECUTING}}
    ref = Ref(raw)
    client = FakeClient(equity=1210, positions=[pos("BTCUSDT", "LONG")])
    result = portfolio_cycle_gate(client=client, ref=ref, raw_state=raw, uid="u", account=client.account_information(),
        positions=client.position_risk(), open_orders=[], timestamp_ms=1, take_profit_mode="PORTFOLIO", portfolio_tp_percent=20)
    assert result.handled and not result.restart
    assert ref.data["multiBbCycle"]["cycleStatus"] == FLAT_CONFIRMED
    assert client.positions == []


def test_stale_individual_tp_is_blocked_after_mode_switch():
    raw = {"settings": {"takeProfitMode": "PORTFOLIO", "portfolioTpPercent": 20},
           "multiBbCycle": {"cycleId": "abc", "cycleStartEquity": 1000, "cycleStatus": "RUNNING"}}
    ref = Ref(raw)
    intent = type("Intent", (), {"intent_id": "mbb-tp-old", "action": "CLOSE"})()
    with pytest.raises(PortfolioCycleOrderBlocked):
        assert_order_allowed(ref, intent)


def test_stale_open_is_blocked_when_portfolio_target_is_already_reached():
    raw = {"settings": {"takeProfitMode": "PORTFOLIO", "portfolioTpPercent": 20},
           "multiBbCycle": {"cycleId": "abc", "cycleStartEquity": 1000, "cycleStatus": "RUNNING"}}
    ref = Ref(raw)
    client = FakeClient(equity=1200)
    intent = type("Intent", (), {"intent_id": "mbb-open-stale", "action": "OPEN"})()
    with pytest.raises(PortfolioCycleOrderBlocked):
        assert_order_allowed(ref, intent, client=client)


def test_exchange_equity_prefers_real_joined_margin_total():
    assert exchange_equity({"totalMarginBalance": "1234.5", "totalWalletBalance": "999"}) == 1234.5
