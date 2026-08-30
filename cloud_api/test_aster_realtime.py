from __future__ import annotations

import asyncio
import json

from aster_realtime import (
    AsterRealtimeWorker,
    EvaluationThrottle,
    RealtimeMarketEvent,
    SymbolRegistry,
    liquidation_distance_pct,
)


def test_registry_deduplicates_public_symbol_across_users():
    registry = SymbolRegistry()
    added, removed = registry.replace({"SOLUSDT": ["a", "b"], "BTCUSDT": ["a"]})
    assert added == {"SOLUSDT", "BTCUSDT"}
    assert removed == set()
    assert registry.users_for("solusdt") == ("a", "b")
    assert registry.symbols() == ("BTCUSDT", "SOLUSDT")
    assert registry.tenant_count() == 2


def test_registry_dynamic_add_remove():
    registry = SymbolRegistry()
    registry.replace({"SOLUSDT": ["a"]})
    added, removed = registry.replace({"DOGEUSDT": ["a"], "SOLUSDT": ["b"]})
    assert added == {"DOGEUSDT"}
    assert removed == set()
    added, removed = registry.replace({"DOGEUSDT": ["a"]})
    assert added == set()
    assert removed == {"SOLUSDT"}


def test_mark_price_event_parser_accepts_combined_stream():
    event = AsterRealtimeWorker.parse_event({
        "stream": "solusdt@markPrice@1s",
        "data": {"e": "markPriceUpdate", "E": 1234, "s": "SOLUSDT", "p": "103.52"},
    }, received_at_ms=1300)
    assert event == RealtimeMarketEvent("SOLUSDT", 103.52, 1234, 1300, "solusdt@markPrice@1s")
    assert event.transport_latency_ms == 66


def test_irrelevant_or_invalid_event_is_ignored():
    assert AsterRealtimeWorker.parse_event({"result": None, "id": 1}) is None
    assert AsterRealtimeWorker.parse_event({"s": "SOLUSDT", "p": "0"}) is None


def test_throttle_reacts_immediately_then_coalesces():
    throttle = EvaluationThrottle(minimum_interval=1.0, move_trigger_pct=.02)
    assert throttle.allow("u1", "SOLUSDT", 100.0, now=0.0) is True
    assert throttle.allow("u1", "SOLUSDT", 100.5, now=.2) is False
    assert throttle.allow("u1", "SOLUSDT", 100.5, now=1.1) is True


def test_flat_ticks_are_not_rest_amplified():
    throttle = EvaluationThrottle(minimum_interval=1.0, move_trigger_pct=.02)
    assert throttle.allow("u1", "SOLUSDT", 100.0, now=0.0)
    assert not throttle.allow("u1", "SOLUSDT", 100.001, now=1.1)
    assert throttle.allow("u1", "SOLUSDT", 100.001, now=5.1)


def test_liquidation_distance_is_side_correct_and_not_maintenance_ratio():
    assert round(liquidation_distance_pct(100, 80, "LONG"), 2) == 20.00
    assert round(liquidation_distance_pct(100, 120, "SHORT"), 2) == 20.00
    assert liquidation_distance_pct(100, 0, "LONG") is None


def test_one_public_event_fans_out_to_two_users_without_duplicate_subscription():
    calls = []
    worker = AsterRealtimeWorker(
        load_subscriptions=lambda: {"SOLUSDT": ["a", "b"]},
        evaluate=lambda uid, event: calls.append((uid, event.symbol)) or {"ordersSent": 0},
        execution_enabled=True,
        throttle=EvaluationThrottle(minimum_interval=.1, move_trigger_pct=0),
    )
    worker.registry.replace({"SOLUSDT": ["a", "b"]})
    asyncio.run(worker._evaluate_event(RealtimeMarketEvent("SOLUSDT", 100, 1, 2)))
    assert sorted(calls) == [("a", "SOLUSDT"), ("b", "SOLUSDT")]
    assert worker.registry.symbols() == ("SOLUSDT",)


def test_execution_disabled_never_calls_strategy():
    calls = []
    worker = AsterRealtimeWorker(
        load_subscriptions=lambda: {"SOLUSDT": ["a"]},
        evaluate=lambda uid, event: calls.append(uid),
        execution_enabled=False,
    )
    worker.registry.replace({"SOLUSDT": ["a"]})
    asyncio.run(worker._evaluate_event(RealtimeMarketEvent("SOLUSDT", 100, 1, 2)))
    assert calls == []
    assert worker.metrics.evaluation_skips == 1


class _FakeSocket:
    def __init__(self):
        self.messages = []

    async def send(self, message):
        self.messages.append(json.loads(message))


def test_subscription_messages_use_lowercase_one_second_mark_stream():
    worker = AsterRealtimeWorker(load_subscriptions=lambda: {}, evaluate=lambda *_: {})
    socket = _FakeSocket()
    asyncio.run(worker._send_subscriptions(socket, subscribe=["SOLUSDT", "BTCUSDT"], unsubscribe=["DOGEUSDT"]))
    assert socket.messages[0]["method"] == "SUBSCRIBE"
    assert socket.messages[0]["params"] == ["btcusdt@markPrice@1s", "solusdt@markPrice@1s"]
    assert socket.messages[1]["method"] == "UNSUBSCRIBE"
    assert socket.messages[1]["params"] == ["dogeusdt@markPrice@1s"]


def test_registry_symbols_for_tenant_isolated():
    registry=SymbolRegistry();registry.replace({"SOLUSDT":["a","b"],"BTCUSDT":["a"],"DOGEUSDT":["b"]})
    assert registry.symbols_for("a")== ("BTCUSDT","SOLUSDT")
    assert registry.symbols_for("b")== ("DOGEUSDT","SOLUSDT")
    assert registry.symbols_for("unknown")==()


def test_forced_simple_mode_evaluates_every_received_event_even_when_throttle_would_skip():
    calls=[]
    worker=AsterRealtimeWorker(
        load_subscriptions=lambda:{"SOLUSDT":["simple"]},
        evaluate=lambda uid,event:calls.append((uid,event.mark_price)) or {"ordersSent":0},
        execution_enabled=True,
        throttle=EvaluationThrottle(minimum_interval=60,move_trigger_pct=99),
        force_evaluate=lambda uid,symbol: uid=="simple",
    )
    worker.registry.replace({"SOLUSDT":["simple"]})
    asyncio.run(worker._evaluate_event(RealtimeMarketEvent("SOLUSDT",100,1,2)))
    asyncio.run(worker._evaluate_event(RealtimeMarketEvent("SOLUSDT",100.0001,3,4)))
    assert calls==[("simple",100),("simple",100.0001)]
    assert worker.metrics.evaluation_skips==0
