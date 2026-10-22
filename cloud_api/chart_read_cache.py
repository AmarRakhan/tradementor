"""Per-instance read cache for the read-only Portfolio Koers / Actieve Trades chart feeds.

Why: every open chart screen re-read the SAME Firestore documents every few seconds:
- `/portfolio-chart/events` (every 5 s): up to 1,200 Strategy-2 audit documents of the last 36 h;
- `/portfolio-chart/active-trades` (every 5 s): 320 candle documents;
- `/portfolio-chart` (2x per 45 s): 320/600 candles + 600 (zone ladder) + 400 (day range) + 100 stored closes.
Billing (Kostenaudit 4.0) shows ~14 million Firestore reads per day for four accounts.

What this module does: keep the documents a chart route already read in memory and, on the next request, only
read the documents that can have changed since then (the newest part of the series, with a safety overlap).
The answer a route returns is identical to a full read, because:
- the chart writers (`_persist_portfolio_chart_sample`, `_persist_active_trades_chart_sample`) only ever write the
  bucket of a sample that is at most a few minutes old, which always falls inside the overlap window;
- Strategy-2 audit documents are written by the tick with the tick's own timestamp, also inside the overlap window;
- a periodic full re-read (default 15 minutes) bounds any unforeseen out-of-window change or deletion;
- any error in an incremental read falls back to the original full read.

Scope: presentation only. It is never used by the Strategy-2 tick, the order engine, Auto Hedge, TP or DCA; those
keep calling Firestore directly. Disable completely with env CHART_READ_CACHE_ENABLED=false (exact old behaviour).
This module has no Firestore or exchange imports; readers are injected, so it is unit-testable without network.
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable, Iterable

# One row: (document_id, sort_key, value). sort_key orders the series (bucketMs, or a timestamp in ms).
Row = tuple[str, int, Any]

FULL_REFRESH_SECONDS = 900.0    # re-read the whole window at least every 15 minutes
REUSE_SECONDS = 2.0             # identical requests within 2 s (two tabs, two charts) share one read
MAX_KEYS = 256                  # (account x series) entries kept per instance


def cache_enabled() -> bool:
    return str(os.environ.get("CHART_READ_CACHE_ENABLED", "true")).strip().lower() not in {"0", "false", "no", "off"}


class _Entry:
    __slots__ = ("rows", "limit", "full_at", "read_at", "lock")

    def __init__(self) -> None:
        self.rows: dict[str, tuple[int, Any]] = {}
        self.limit: int | None = 0          # how many newest documents the cached window represents (None = all)
        self.full_at = -1e18
        self.read_at = -1e18
        self.lock = threading.Lock()


class TailRefreshCache:
    """Cache of the newest N documents of an append-mostly series, refreshed from its tail.

    `full(limit)`  -> rows of the newest `limit` documents (limit None = all), any order.
    `tail(since)`  -> rows with sort_key >= since, any order (re-reads the overlap window).
    `get()` returns the newest `limit` rows, newest first, exactly as a direct `order_by(desc).limit(limit)` query.
    """

    def __init__(self, *, overlap: int, full_refresh_seconds: float = FULL_REFRESH_SECONDS,
                 reuse_seconds: float = REUSE_SECONDS, max_keys: int = MAX_KEYS,
                 clock: Callable[[], float] = time.monotonic,
                 enabled: Callable[[], bool] = cache_enabled) -> None:
        self._overlap = int(overlap)
        self._full_refresh = float(full_refresh_seconds)
        self._reuse = float(reuse_seconds)
        self._max_keys = max(1, int(max_keys))
        self._clock = clock
        self._enabled = enabled
        self._entries: "OrderedDict[Hashable, _Entry]" = OrderedDict()
        self._guard = threading.Lock()
        self.stats = {"full": 0, "tail": 0, "reused": 0, "fallback": 0}

    def _entry(self, key: Hashable) -> _Entry:
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                entry = _Entry()
                self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_keys:
                self._entries.popitem(last=False)
            return entry

    def invalidate(self, key: Hashable) -> None:
        with self._guard:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._guard:
            self._entries.clear()

    @staticmethod
    def _covers(cached: int | None, wanted: int | None) -> bool:
        if cached is None:
            return True
        if wanted is None:
            return False
        return cached >= wanted

    @staticmethod
    def _newest(rows: dict[str, tuple[int, Any]], limit: int | None) -> list[Row]:
        ordered = sorted(((doc_id, key, value) for doc_id, (key, value) in rows.items()),
                         key=lambda row: (row[1], row[0]), reverse=True)
        return ordered if limit is None else ordered[:max(0, int(limit))]

    def get(self, key: Hashable, *, limit: int | None, full: Callable[[int | None], Iterable[Row]],
            tail: Callable[[int], Iterable[Row]], keep: Callable[[Row], bool] | None = None) -> list[Row]:
        wanted = None if limit is None else max(1, int(limit))
        if not self._enabled():
            return self._newest({d: (k, v) for d, k, v in full(wanted) if keep is None or keep((d, k, v))}, wanted)
        entry = self._entry(key)
        with entry.lock:
            now = self._clock()
            fresh_window = self._covers(entry.limit, wanted) and now - entry.full_at < self._full_refresh
            if fresh_window and now - entry.read_at < self._reuse:
                self.stats["reused"] += 1
            elif fresh_window and entry.rows:
                newest = max(sort_key for sort_key, _value in entry.rows.values())
                try:
                    changed = list(tail(newest - self._overlap))
                except Exception:  # noqa: BLE001 - presentation cache: any doubt -> original full read
                    self.stats["fallback"] += 1
                    self._load_full(entry, wanted, full, now)
                else:
                    self.stats["tail"] += 1
                    for doc_id, sort_key, value in changed:
                        entry.rows[doc_id] = (int(sort_key), value)
                    entry.read_at = now
            else:
                # First read, expired window, or a caller asking for more history than is cached: one full read of
                # the widest window any caller of this key asked for, so 320- and 600-candle callers share it.
                previous = wanted if entry.limit == 0 else entry.limit
                self._load_full(entry, self._widest(previous, wanted), full, now)
            if keep is not None:
                for doc_id in [d for d, (k, v) in entry.rows.items() if not keep((d, k, v))]:
                    del entry.rows[doc_id]
            if entry.limit is not None:
                # Trim to the represented window, exactly like the direct query's limit would.
                entry.rows = {d: (k, v) for d, k, v in self._newest(entry.rows, entry.limit)}
            return self._newest(entry.rows, wanted)

    @staticmethod
    def _widest(cached: int | None, wanted: int | None) -> int | None:
        if cached is None or wanted is None:
            return None
        return max(cached, wanted)

    def _load_full(self, entry: _Entry, limit: int | None, full: Callable[[int | None], Iterable[Row]],
                   now: float) -> None:
        self.stats["full"] += 1
        rows = {doc_id: (int(sort_key), value) for doc_id, sort_key, value in full(limit)}
        entry.rows, entry.limit, entry.full_at, entry.read_at = rows, limit, now, now


class TtlValueCache:
    """Small per-key TTL cache with explicit invalidation (used for the 100 stored confirmed closes)."""

    def __init__(self, *, ttl_seconds: float, max_keys: int = MAX_KEYS,
                 clock: Callable[[], float] = time.monotonic,
                 enabled: Callable[[], bool] = cache_enabled) -> None:
        self._ttl, self._max_keys, self._clock, self._enabled = float(ttl_seconds), max(1, int(max_keys)), clock, enabled
        self._values: "OrderedDict[Hashable, tuple[float, Any]]" = OrderedDict()
        self._guard = threading.Lock()
        self._locks: dict[Hashable, threading.Lock] = {}

    def get(self, key: Hashable, load: Callable[[], Any]) -> Any:
        if not self._enabled():
            return load()
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            now = self._clock()
            with self._guard:
                hit = self._values.get(key)
            if hit is not None and now - hit[0] < self._ttl:
                return hit[1]
            value = load()
            with self._guard:
                self._values[key] = (now, value)
                self._values.move_to_end(key)
                while len(self._values) > self._max_keys:
                    self._values.popitem(last=False)
            return value

    def invalidate(self, key: Hashable) -> None:
        with self._guard:
            self._values.pop(key, None)
