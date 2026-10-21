"""Keep the per-account confirmed fill-activity cache warm for the read-only Portfolio Koers chart.

Chart moneybags and LONG/SHORT entry labels are built from `_aster_closed_trades_cache`, which until now was filled
ONLY when the user's app happened to call `/v1/me/aster/closed-trades` (the "Trades gesloten" flip card or the TP
detail hydration) on the same Cloud Run instance. After a deploy, an instance restart or on a second instance the cache
is empty, and an account without recent Strategy-2 audit events then shows no labels at all (issue #738: "cold cache
never self-refreshes through chart route").

This helper lets the chart routes fill that cache through the SAME existing loader (`aster_closed_trades`, read-only,
`live_authorized=False`) when it is missing or older than WARM_MAX_AGE_SECONDS. It never places, changes or cancels an
order, never changes chart presentation, and a failing history fetch never breaks the chart: it simply returns
whatever cache exists. A per-account backoff and an in-flight guard keep Aster's shared-IP quota protected.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

WARM_MAX_AGE_SECONDS = 600.0     # refresh confirmed fill activity for the chart at most every 10 minutes
RETRY_BACKOFF_SECONDS = 120.0    # after an attempt (success or failure) wait before trying again for that account


class ClosedTradesWarmup:
    def __init__(self, cache: dict[str, tuple], lock: threading.RLock, loader: Callable[[dict[str, Any]], Any], *,
                 clock: Callable[[], float] = time.monotonic, max_age: float = WARM_MAX_AGE_SECONDS,
                 backoff: float = RETRY_BACKOFF_SECONDS) -> None:
        self._cache, self._lock, self._loader, self._clock = cache, lock, loader, clock
        self._max_age, self._backoff = max_age, backoff
        self._attempts: dict[str, float] = {}
        self._inflight: set[str] = set()

    def ensure(self, uid: str, user: dict[str, Any]) -> tuple | None:
        """Return the account's cache entry, loading it first when missing or stale (bounded, fail-open)."""
        now = self._clock()
        with self._lock:
            cached = self._cache.get(uid)
            if cached and now - cached[0] < self._max_age:
                return cached
            last = self._attempts.get(uid)
            if uid in self._inflight or (last is not None and now - last < self._backoff):
                return cached
            self._attempts[uid] = now
            self._inflight.add(uid)
        try:
            self._loader(user)
        except Exception:  # noqa: BLE001 - presentation-only: the chart must render even without fill history
            pass
        finally:
            with self._lock:
                self._inflight.discard(uid)
        with self._lock:
            return self._cache.get(uid)
