"""Realtime Aster market-data orchestration for active Strategy-2 positions.

Public mark-price data is shared per symbol across tenants. This module never
submits an exchange order itself: an injected evaluation callback must pass each
candidate event through the existing Strategy-2 lease/queue/idempotency gates.
REST remains authoritative for reconciliation and order/account truth.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import json
import logging
import math
import random
import threading
import time
from typing import Any, Callable, Iterable

from websockets.asyncio.client import connect


ASTER_STREAM_URL = "wss://fstream.asterdex.com/stream"
MAX_STREAMS_PER_CONNECTION = 200
STALE_AFTER_SECONDS = 20.0
SUBSCRIPTION_REFRESH_SECONDS = 5.0
HEALTH_PERSIST_SECONDS = 30.0
ACCOUNT_MIN_EVALUATION_INTERVAL_SECONDS = 1.0
ACCOUNT_PRICE_MOVE_TRIGGER_PCT = 0.02

logger = logging.getLogger("tradementor.aster_realtime")


@dataclass(frozen=True)
class RealtimeMarketEvent:
    symbol: str
    mark_price: float
    event_time_ms: int
    received_at_ms: int
    stream: str = ""

    @property
    def transport_latency_ms(self) -> int:
        if self.event_time_ms <= 0:
            return 0
        return max(0, self.received_at_ms - self.event_time_ms)

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "markPrice": self.mark_price,
            "eventTimeMs": self.event_time_ms,
            "receivedAtMs": self.received_at_ms,
            "transportLatencyMs": self.transport_latency_ms,
        }


@dataclass
class RealtimeMetrics:
    started_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    connected: bool = False
    connection_count: int = 0
    reconnect_count: int = 0
    stale_disconnects: int = 0
    incoming_events: int = 0
    ignored_events: int = 0
    evaluation_attempts: int = 0
    evaluation_skips: int = 0
    orders_observed: int = 0
    errors: int = 0
    last_event_at_ms: int = 0
    last_connect_at_ms: int = 0
    last_error: str = ""
    evaluation_latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=500))

    def snapshot(self, *, subscriptions: int, tenants: int) -> dict[str, Any]:
        values = sorted(self.evaluation_latencies_ms)
        average = sum(values) / len(values) if values else 0.0
        p95 = values[min(len(values) - 1, math.ceil(len(values) * .95) - 1)] if values else 0.0
        return {
            "connected": self.connected,
            "connectionCount": self.connection_count,
            "reconnectCount": self.reconnect_count,
            "staleDisconnects": self.stale_disconnects,
            "subscriptions": subscriptions,
            "tenants": tenants,
            "incomingEvents": self.incoming_events,
            "ignoredEvents": self.ignored_events,
            "evaluationAttempts": self.evaluation_attempts,
            "evaluationSkips": self.evaluation_skips,
            "ordersObserved": self.orders_observed,
            "errors": self.errors,
            "lastEventAtMs": self.last_event_at_ms,
            "lastConnectAtMs": self.last_connect_at_ms,
            "lastError": self.last_error[-300:],
            "averageEvaluationLatencyMs": round(average, 2),
            "p95EvaluationLatencyMs": round(p95, 2),
            "startedAtMs": self.started_at_ms,
        }


class SymbolRegistry:
    """Thread-safe many-user -> one-public-symbol subscription registry."""

    def __init__(self) -> None:
        self._by_symbol: dict[str, set[str]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _clean_symbol(value: Any) -> str:
        symbol = str(value or "").upper().strip()
        return symbol if symbol and symbol.replace("_", "").isalnum() else ""

    def replace(self, mapping: dict[str, Iterable[str]]) -> tuple[set[str], set[str]]:
        normalized: dict[str, set[str]] = {}
        for symbol, uids in mapping.items():
            clean = self._clean_symbol(symbol)
            members = {str(uid).strip() for uid in uids if str(uid).strip()}
            if clean and members:
                normalized[clean] = members
        with self._lock:
            old = set(self._by_symbol)
            new = set(normalized)
            self._by_symbol = normalized
        return new - old, old - new

    def users_for(self, symbol: str) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._by_symbol.get(str(symbol).upper(), set())))

    def symbols(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._by_symbol))

    def tenant_count(self) -> int:
        with self._lock:
            return len({uid for members in self._by_symbol.values() for uid in members})


class EvaluationThrottle:
    """Coalesce ticks without forgetting a move that arrived during cooldown.

    ``_last_price`` deliberately means last *evaluated* price, not last observed
    price. A move that occurs inside the account cooldown therefore remains dirty
    and is evaluated as soon as the next account slot becomes available.
    """

    def __init__(self, minimum_interval: float = ACCOUNT_MIN_EVALUATION_INTERVAL_SECONDS,
                 move_trigger_pct: float = ACCOUNT_PRICE_MOVE_TRIGGER_PCT) -> None:
        self.minimum_interval = max(.1, float(minimum_interval))
        self.move_trigger_pct = max(0.0, float(move_trigger_pct))
        self._last_account_eval: dict[str, float] = {}
        self._last_price: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def allow(self, uid: str, symbol: str, price: float, now: float | None = None) -> bool:
        stamp = time.monotonic() if now is None else float(now)
        key = (uid, symbol.upper())
        with self._lock:
            prior_price = self._last_price.get(key)
            last_eval = self._last_account_eval.get(uid, -1e12)
            elapsed = stamp - last_eval
            if elapsed < self.minimum_interval:
                return False
            moved = prior_price is None or prior_price <= 0 or abs(price / prior_price - 1.0) * 100 >= self.move_trigger_pct
            if not moved and elapsed < max(self.minimum_interval, 5.0):
                return False
            self._last_account_eval[uid] = stamp
            self._last_price[key] = price
            return True


class AsterRealtimeWorker:
    """One shared Aster public stream with dynamic active-position subscriptions."""

    def __init__(
        self,
        *,
        load_subscriptions: Callable[[], dict[str, Iterable[str]]],
        evaluate: Callable[[str, RealtimeMarketEvent], dict[str, Any] | None],
        persist_health: Callable[[dict[str, Any]], None] | None = None,
        stream_url: str = ASTER_STREAM_URL,
        refresh_seconds: float = SUBSCRIPTION_REFRESH_SECONDS,
        stale_after_seconds: float = STALE_AFTER_SECONDS,
        execution_enabled: bool = True,
        throttle: EvaluationThrottle | None = None,
    ) -> None:
        self.load_subscriptions = load_subscriptions
        self.evaluate = evaluate
        self.persist_health = persist_health
        self.stream_url = stream_url
        self.refresh_seconds = max(1.0, float(refresh_seconds))
        self.stale_after_seconds = max(5.0, float(stale_after_seconds))
        self.execution_enabled = bool(execution_enabled)
        self.registry = SymbolRegistry()
        self.metrics = RealtimeMetrics()
        self.throttle = throttle or EvaluationThrottle()
        self._stop = asyncio.Event()
        self._subscription_version = 0
        self._health_lock = threading.Lock()
        self._last_health_persist = 0.0
        self._latest_lock = threading.RLock()
        self._latest_by_symbol: dict[str, RealtimeMarketEvent] = {}

    def stop(self) -> None:
        self._stop.set()

    def health(self) -> dict[str, Any]:
        return self.metrics.snapshot(subscriptions=len(self.registry.symbols()), tenants=self.registry.tenant_count())

    def latest(self, symbols: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
        allowed = None if symbols is None else {str(symbol).upper() for symbol in symbols}
        with self._latest_lock:
            return {symbol: event.public_dict() for symbol, event in self._latest_by_symbol.items()
                    if allowed is None or symbol in allowed}

    @staticmethod
    def parse_event(payload: Any, received_at_ms: int | None = None) -> RealtimeMarketEvent | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        stream = str(payload.get("stream", ""))
        symbol = str(data.get("s", data.get("symbol", ""))).upper().strip()
        raw_price = data.get("p", data.get("markPrice"))
        try:
            price = float(raw_price)
            event_ms = int(data.get("E", data.get("eventTime", 0)) or 0)
        except (TypeError, ValueError):
            return None
        if not symbol or not math.isfinite(price) or price <= 0:
            return None
        return RealtimeMarketEvent(symbol, price, event_ms, received_at_ms or int(time.time() * 1000), stream)

    def _refresh_registry(self) -> tuple[set[str], set[str]]:
        try:
            mapping = self.load_subscriptions()
            if not isinstance(mapping, dict):
                raise TypeError("subscription loader must return a mapping")
            added, removed = self.registry.replace(mapping)
            if len(self.registry.symbols()) > MAX_STREAMS_PER_CONNECTION:
                raise RuntimeError(f"Aster realtime subscription cap exceeded: {len(self.registry.symbols())}>{MAX_STREAMS_PER_CONNECTION}")
            if added or removed:
                self._subscription_version += 1
            return added, removed
        except Exception as exc:
            self.metrics.errors += 1
            self.metrics.last_error = f"subscription refresh: {exc}"
            logger.exception("Aster realtime subscription refresh failed")
            return set(), set()

    async def _evaluate_event(self, event: RealtimeMarketEvent) -> None:
        users = self.registry.users_for(event.symbol)
        if not users:
            self.metrics.ignored_events += 1
            return
        for uid in users:
            if not self.execution_enabled:
                self.metrics.evaluation_skips += 1
                continue
            if not self.throttle.allow(uid, event.symbol, event.mark_price):
                self.metrics.evaluation_skips += 1
                continue
            self.metrics.evaluation_attempts += 1
            started = time.monotonic()
            try:
                result = await asyncio.to_thread(self.evaluate, uid, event)
                if isinstance(result, dict):
                    self.metrics.orders_observed += max(0, int(result.get("ordersSent", 0) or 0))
            except Exception as exc:
                self.metrics.errors += 1
                self.metrics.last_error = f"evaluation {uid}/{event.symbol}: {exc}"
                logger.exception("Aster realtime evaluation failed for uid=%s symbol=%s", uid, event.symbol)
            finally:
                self.metrics.evaluation_latencies_ms.append((time.monotonic() - started) * 1000)

    async def _send_subscriptions(self, websocket: Any, *, subscribe: Iterable[str] = (), unsubscribe: Iterable[str] = ()) -> None:
        for method, symbols in (("SUBSCRIBE", subscribe), ("UNSUBSCRIBE", unsubscribe)):
            params = [f"{symbol.lower()}@markPrice@1s" for symbol in sorted(set(symbols))]
            if not params:
                continue
            await websocket.send(json.dumps({"method": method, "params": params, "id": int(time.time() * 1000) % 2_000_000_000}))

    def _persist_health_if_due(self, *, force: bool = False) -> None:
        if self.persist_health is None:
            return
        now = time.monotonic()
        with self._health_lock:
            if not force and now - self._last_health_persist < HEALTH_PERSIST_SECONDS:
                return
            self._last_health_persist = now
        try:
            self.persist_health(self.health())
        except Exception as exc:
            self.metrics.errors += 1
            self.metrics.last_error = f"health persist: {exc}"

    async def _connection(self) -> None:
        self._refresh_registry()
        async with connect(self.stream_url, ping_interval=None, close_timeout=5, max_queue=512) as websocket:
            self.metrics.connected = True
            self.metrics.connection_count += 1
            self.metrics.last_connect_at_ms = int(time.time() * 1000)
            await self._send_subscriptions(websocket, subscribe=self.registry.symbols())
            seen_version = self._subscription_version
            last_message = time.monotonic()
            last_refresh = 0.0
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_refresh >= self.refresh_seconds:
                    before = set(self.registry.symbols())
                    added, removed = self._refresh_registry()
                    if self._subscription_version != seen_version:
                        await self._send_subscriptions(websocket, subscribe=added, unsubscribe=removed)
                        seen_version = self._subscription_version
                    last_refresh = now
                    if not before and not self.registry.symbols():
                        self._persist_health_if_due()
                try:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    if self.registry.symbols() and time.monotonic() - last_message > self.stale_after_seconds:
                        self.metrics.stale_disconnects += 1
                        raise ConnectionError("Aster realtime stream became stale")
                    self._persist_health_if_due()
                    continue
                last_message = time.monotonic()
                try:
                    payload = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    self.metrics.ignored_events += 1
                    continue
                event = self.parse_event(payload)
                if event is None:
                    self.metrics.ignored_events += 1
                    continue
                self.metrics.incoming_events += 1
                self.metrics.last_event_at_ms = event.received_at_ms
                with self._latest_lock:
                    self._latest_by_symbol[event.symbol] = event
                await self._evaluate_event(event)
                self._persist_health_if_due()

    async def run(self) -> None:
        backoff = 1.0
        first = True
        while not self._stop.is_set():
            try:
                await self._connection()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.metrics.connected = False
                self.metrics.errors += 1
                self.metrics.last_error = str(exc)
                if not first:
                    self.metrics.reconnect_count += 1
                logger.warning("Aster realtime disconnected: %s", exc)
                self._persist_health_if_due(force=True)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff + random.random() * min(1.0, backoff / 4))
                except asyncio.TimeoutError:
                    pass
                backoff = min(30.0, backoff * 2.0)
            finally:
                first = False
        self.metrics.connected = False
        self._persist_health_if_due(force=True)


def liquidation_distance_pct(mark_price: float, liquidation_price: float, side: str) -> float | None:
    """Actual mark-to-liquidation distance; maintenance ratio is intentionally unrelated."""
    try:
        mark = float(mark_price)
        liquidation = float(liquidation_price)
    except (TypeError, ValueError):
        return None
    direction = str(side).upper()
    if mark <= 0 or liquidation <= 0 or direction not in {"LONG", "SHORT"}:
        return None
    distance = ((mark - liquidation) / mark * 100.0 if direction == "LONG"
                else (liquidation - mark) / mark * 100.0)
    return max(0.0, distance) if math.isfinite(distance) else None
