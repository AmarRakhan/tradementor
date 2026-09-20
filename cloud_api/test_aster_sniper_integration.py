from pathlib import Path

import aster_sniper_runtime as runtime
from aster_sniper import SniperSettings


class PendingClient:
    def __init__(self, positions=None, orders=None):
        self.positions = list(positions or [])
        self.orders = list(orders or [])

    def position_risk(self, symbol=None):
        if not symbol:
            return list(self.positions)
        return [x for x in self.positions if str(x.get("symbol", "")).upper() == symbol.upper()]

    def open_orders(self, symbol=None):
        if not symbol:
            return list(self.orders)
        return [x for x in self.orders if str(x.get("symbol", "")).upper() == symbol.upper()]


def test_pending_open_is_recovered_from_exchange_truth_without_second_order():
    state = {
        "pendingIntent": {
            "action": "OPEN", "symbol": "BTCUSDT", "side": "LONG", "tradeId": "sn-test-0001",
            "createdAtMs": 1_000, "marginUsd": 1, "tpPercent": .18, "checks": [], "timeframe": "1m",
        },
        "activeTrades": [],
    }
    client = PendingClient(positions=[{
        "symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "0.001",
        "entryPrice": "100000", "markPrice": "100100", "leverage": "20",
    }])
    released = []
    next_state, event = runtime.reconcile_pending(
        client=client, state=state, settings=SniperSettings(), now_ms=2_000, release_symbol=released.append,
    )
    assert next_state["pendingIntent"] is None
    assert len(next_state["activeTrades"]) == 1
    assert next_state["activeTrades"][0]["symbol"] == "BTCUSDT"
    assert event["event"] == "RECOVERED_OPEN"
    assert released == []


def test_stale_unaccepted_pending_entry_releases_symbol_only_after_reconciliation():
    state = {
        "pendingIntent": {
            "action": "OPEN", "symbol": "SOLUSDT", "side": "SHORT", "tradeId": "sn-test-0002",
            "createdAtMs": 1_000,
        },
        "activeTrades": [],
    }
    released = []
    next_state, event = runtime.reconcile_pending(
        client=PendingClient(), state=state, settings=SniperSettings(), now_ms=62_000,
        release_symbol=released.append,
    )
    assert next_state["pendingIntent"] is None
    assert event["event"] == "PENDING_CLEARED"
    assert released == ["SOLUSDT"]


def test_sniper_stop_blocks_new_entries_but_still_closes_owned_timeout(monkeypatch):
    class ClosingClient(PendingClient):
        def __init__(self):
            super().__init__([{
                "symbol": "ETHUSDT", "positionSide": "LONG", "positionAmt": "1",
                "entryPrice": "100", "markPrice": "100", "leverage": "20", "unRealizedProfit": "0",
            }])
            self.closed = False

        def position_risk(self, symbol=None):
            return [] if self.closed else super().position_risk(symbol)

    client = ClosingClient()
    released, persisted = [], []

    def fake_execute(client_arg, plan, **kwargs):
        assert kwargs["action"] == "CLOSE"
        assert kwargs["side"].value == "LONG"
        client_arg.closed = True
        return {"result": {"orderId": 99, "clientOrderId": "sniper-close-test"}}

    monkeypatch.setattr(runtime, "execute_leg_once", fake_execute)
    result = runtime.run_sniper_tick(
        client=client,
        state={
            "enabled": False, "monitor": True,
            "activeTrades": [{
                "tradeId": "sn-test-0003", "symbol": "ETHUSDT", "side": "LONG",
                "openedAtMs": 1_000, "tpPercent": .18,
            }],
        },
        settings=SniperSettings(),
        blocked_symbols=set(),
        claim_symbol=lambda *_: True,
        release_symbol=released.append,
        persist_pending=persisted.append,
        live_enabled=True,
        now_ms=182_000,
    )
    assert result["action"] == "CLOSE_TIMEOUT"
    assert result["ordersSent"] == 1
    assert result["historyRecord"]["tradeId"] == "sn-test-0003"
    assert released == ["ETHUSDT"]
    assert persisted[-1] is None


def test_main_contract_filters_strategy_profit_close_and_emergency_disables_both_bots():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    assert 'owned_symbols=_aster_strategy2_owned_symbols(str(user["uid"]))' in source
    assert 'initial = profitable_positions([row for row in client.position_risk() if str(row.get("symbol","")).upper() in owned_symbols])' in source
    assert 'txn.set(aster_sniper_reference(uid),{"enabled":False,"monitor":False,"phase":"EMERGENCY_STOP"' in source
    assert "_release_all_aster_symbol_claims(uid)" in source
    close_block=source[source.index('@app.post("/v1/me/aster/automation/close-all")'):]
    assert '_portfolio_growth_estimate(user,persist_quote=False)' not in close_block
    assert '"emergency":True' in close_block


def test_scheduler_has_independent_sniper_collection_and_runtime():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    assert 'db.collection("asterSniper").where("monitor","==",True)' in source
    assert "_run_aster_sniper_tick(item.id)" in source
    assert '"sniper":sniper_results' in source


def test_stale_close_intent_keeps_symbol_owned_when_position_still_exists():
    state={
        "pendingIntent":{"action":"CLOSE","symbol":"BTCUSDT","side":"LONG","tradeId":"sn-close-0001","createdAtMs":1_000},
        "activeTrades":[{"tradeId":"sn-close-0001","symbol":"BTCUSDT","side":"LONG"}],
    }
    client=PendingClient(positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"0.001","markPrice":"100000"}])
    released=[]
    next_state,event=runtime.reconcile_pending(client=client,state=state,settings=SniperSettings(),now_ms=62_000,release_symbol=released.append)
    assert next_state["pendingIntent"] is None
    assert event["event"]=="CLOSE_RETRY_READY"
    assert released==[]


def test_main_has_exact_sniper_close_accounting_and_shared_account_fence():
    source=Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    assert "def _sniper_confirmed_close_evidence" in source
    assert "paged_user_trades(client,symbol" in source
    assert "paged_income_history(client,symbol=symbol" in source
    assert '"netRealizedPnlUsd":gross+funding-fees' in source
    assert "_acquire_sniper_execution_lease(ref)" in source
    assert '_acquire_aster_account_coordination(uid,"SNIPER","MANUAL_CLOSE")' in source
    assert '_acquire_aster_account_coordination(uid,"EMERGENCY","CLOSE_ALL")' in source
    assert '_acquire_aster_account_coordination(uid,"ASTER","SCHEDULER")' in source
