"""Keep the per-account confirmed fill-activity cache warm for the read-only Portfolio Koers chart.

Chart moneybags and LONG/SHORT entry labels are built from confirmed Aster fill activity. Until #738 that activity was
filled ONLY when the user's app happened to call `/v1/me/aster/closed-trades` (the "Trades gesloten" flip card or the
TP detail hydration) on the same Cloud Run instance. After a deploy, an instance restart or on a second instance the
cache is empty, and an account without recent Strategy-2 audit events then shows no labels at all (issue #738).

This helper lets the chart routes fill that cache themselves when it is missing or older than WARM_MAX_AGE_SECONDS.

Live refresh (22-10-2026): a pure age limit meant a close made right now (Close Profits round, manual Close, TP) only
appeared after up to 10 minutes. The chart routes therefore also pass an account fingerprint taken from the account
snapshot they already read (wallet balance + number of open positions). Every fill changes the wallet balance
(realized PnL and/or commission), so a NEWER snapshot with a different fingerprint triggers a refresh, bounded by
CHANGE_BACKOFF_SECONDS per account. No extra exchange call is needed to detect the change.

It never places, changes or cancels an order, never changes chart presentation, and a failing history fetch never
breaks the chart: it simply returns whatever cache exists.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

WARM_MAX_AGE_SECONDS = 600.0     # refresh confirmed fill activity for the chart at most every 10 minutes when idle
RETRY_BACKOFF_SECONDS = 120.0    # after an age-driven attempt wait before trying again for that account
CHANGE_BACKOFF_SECONDS = 45.0    # a detected account change refreshes at most this often per account

Fingerprint = tuple[int, Any]    # (snapshot captured at ms, comparable account value)


class ClosedTradesWarmup:
    def __init__(self, cache: dict[str, tuple], lock: threading.RLock, loader: Callable[[dict[str, Any]], Any], *,
                 clock: Callable[[], float] = time.monotonic, max_age: float = WARM_MAX_AGE_SECONDS,
                 backoff: float = RETRY_BACKOFF_SECONDS, change_backoff: float = CHANGE_BACKOFF_SECONDS) -> None:
        self._cache, self._lock, self._loader, self._clock = cache, lock, loader, clock
        self._max_age, self._backoff, self._change_backoff = max_age, backoff, change_backoff
        self._attempts: dict[str, float] = {}
        self._inflight: set[str] = set()
        self._fingerprints: dict[str, Fingerprint] = {}
        self._pending: set[str] = set()

    def _account_changed(self, uid: str, fingerprint: Fingerprint | None) -> bool:
        """Record the newest fingerprint; True only when a NEWER snapshot shows a different account value."""
        if fingerprint is None:
            return False
        captured_ms, value = fingerprint
        known = self._fingerprints.get(uid)
        if known is not None and captured_ms <= known[0]:
            return False  # an older or equal snapshot (e.g. another route's) never counts as a change
        self._fingerprints[uid] = fingerprint
        return known is not None and value != known[1]

    def ensure(self, uid: str, user: dict[str, Any], fingerprint: Fingerprint | None = None) -> tuple | None:
        """Return the account's cache entry, loading it first when missing, stale or the account changed."""
        now = self._clock()
        with self._lock:
            cached = self._cache.get(uid)
            if self._account_changed(uid, fingerprint):
                self._pending.add(uid)   # kept until a refresh starts, so a change inside the backoff is not lost
            pending = uid in self._pending
            if cached and now - cached[0] < self._max_age and not pending:
                return cached
            if uid in self._inflight:
                return cached
            last = self._attempts.get(uid)
            limit = self._change_backoff if pending else self._backoff
            if last is not None and now - last < limit:
                return cached
            self._attempts[uid] = now
            self._inflight.add(uid)
            self._pending.discard(uid)
        try:
            self._loader(user)
        except Exception:  # noqa: BLE001 - presentation-only: the chart must render even without fill history
            pass
        finally:
            with self._lock:
                self._inflight.discard(uid)
        with self._lock:
            return self._cache.get(uid)


def account_fingerprint(snapshot: dict[str, Any] | None, captured_ms: int) -> Fingerprint | None:
    """Fingerprint of an Aster account snapshot that changes with every fill (wallet balance + open positions)."""
    if not isinstance(snapshot, dict) or captured_ms <= 0:
        return None
    wallet = snapshot.get("walletBalance")
    if wallet in (None, ""):
        return None
    try:
        wallet_cents = round(float(wallet), 4)
        positions = int(float(snapshot.get("activePositions", 0) or 0))
    except (TypeError, ValueError):
        return None
    return int(captured_ms), (wallet_cents, positions)
