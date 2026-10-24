"""Trade journal routes (build 648): fast Trade Historie list, bounded background sync, full export for an agent.

Registered from ``withdraw_app`` (the production entrypoint). Read-only towards Aster: income, allOrders and
userTrades only; it never places, changes or cancels an order and never touches the trading tick.

Firestore (per user, document reads/writes only; the only query is one single-field order_by on closedAtMs):
- users/{uid}/asterTradeJournal/{id}              one record per closing order
- users/{uid}/tradeJournalSymbols/{SYMBOL}        fill cursor + open position cycles per symbol
- users/{uid}/tradeJournalFunding/{YYYY-MM}       FUNDING_FEE per symbol, per month
- users/{uid}/tradeSettingsVersions/{id}          settings snapshot each time the settings changed
- users/{uid}/executionControls/tradeJournal      sync cursors, known symbols, open-position contexts
- users/{uid}/executionControls/tradeJournalSettings  hash of the newest settings version
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, HTTPException, Query, Request

import main
import trade_journal as tj

SYNC_MIN_INTERVAL_SECONDS = 3.0        # per account; the app waits between steps anyway
INSTANCE_CALLS_PER_MINUTE = 60         # all journal Aster calls on one instance together
SETTINGS_ROUTES = {
    ("PUT", "/v1/me/aster/strategy2/settings"),
    ("POST", "/v1/me/aster/strategy2/portfolio-cycle/reset"),
    ("PUT", "/v1/me/aster/position-loss-auto-hedge"),
    ("PUT", "/v1/me/aster/position-loss-auto-hedge/short-recovery"),
    ("PUT", "/v1/me/aster/profit-sweep-settings"),
    ("PUT", "/v1/me/aster/dynamic-hedge/enabled"),
}

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_last_sync: dict[str, float] = {}
_call_times: deque[float] = deque()
_call_guard = threading.Lock()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _user_lock(uid: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(uid, threading.Lock())


def _instance_budget(max_calls: int) -> int:
    """How many Aster calls this step may make without the instance passing its per-minute journal budget."""
    now = time.monotonic()
    with _call_guard:
        while _call_times and now - _call_times[0] > 60.0:
            _call_times.popleft()
        return max(0, min(max_calls, INSTANCE_CALLS_PER_MINUTE - len(_call_times)))


def _spend(calls: int) -> None:
    now = time.monotonic()
    with _call_guard:
        _call_times.extend([now] * max(0, calls))


def _to_ms(value: Any) -> int:
    if isinstance(value, datetime):
        return int(value.astimezone(timezone.utc).timestamp() * 1000)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


class FirestoreJournalStore:
    """tj.JournalStore on Firestore. JSON strings for free-form maps (Firestore forbids nested arrays)."""

    def __init__(self, uid: str) -> None:
        self.uid = uid
        self.user = main.user_reference({"uid": uid})

    # control ---------------------------------------------------------------------------------------------------
    def _control_ref(self):
        return self.user.collection("executionControls").document("tradeJournal")

    def control(self) -> dict[str, Any]:
        row = self._control_ref().get().to_dict() or {}
        try:
            row["contexts"] = json.loads(row.pop("contextsJson", "") or "{}")
        except ValueError:
            row["contexts"] = {}
        try:
            row["symbolErrors"] = json.loads(row.pop("symbolErrorsJson", "") or "{}")
        except ValueError:
            row["symbolErrors"] = {}
        return row

    def save_control(self, patch: dict[str, Any]) -> None:
        data = dict(patch)
        data["contextsJson"] = json.dumps(data.pop("contexts", {}) or {}, sort_keys=True, default=str)
        data["symbolErrorsJson"] = json.dumps(data.pop("symbolErrors", {}) or {}, sort_keys=True, default=str)
        data["updatedAt"] = datetime.now(timezone.utc)
        self._control_ref().set(data, merge=True)

    # per symbol ------------------------------------------------------------------------------------------------
    def _symbol_ref(self, symbol: str):
        return self.user.collection("tradeJournalSymbols").document(symbol.upper())

    def symbol_state(self, symbol: str) -> dict[str, Any]:
        row = self._symbol_ref(symbol).get().to_dict() or {}
        try:
            row["cycles"] = json.loads(row.pop("cyclesJson", "") or "{}")
        except ValueError:
            row["cycles"] = {}
        return row

    def save_symbol_state(self, symbol: str, state: dict[str, Any]) -> None:
        data = dict(state)
        data["cyclesJson"] = json.dumps(data.pop("cycles", {}) or {}, sort_keys=True, default=str)
        self._symbol_ref(symbol).set(data)

    # records ---------------------------------------------------------------------------------------------------
    def _records(self):
        return self.user.collection("asterTradeJournal")

    @staticmethod
    def _encode(record: dict[str, Any]) -> dict[str, Any]:
        data = dict(record)
        for field in ("context", "autoHedgePair", "cycle", "closeReason"):
            data[f"{field}Json"] = json.dumps(data.pop(field, None), sort_keys=True, default=str)
        data["storedAt"] = datetime.now(timezone.utc)
        return data

    @staticmethod
    def decode(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        for field in ("context", "autoHedgePair", "cycle", "closeReason"):
            raw = data.pop(f"{field}Json", None)
            try:
                data[field] = json.loads(raw) if raw else None
            except ValueError:
                data[field] = None
        data.pop("storedAt", None)
        return data

    def save_records(self, records: list[dict[str, Any]]) -> None:
        for start in range(0, len(records), 400):
            batch = main.db.batch()
            for record in records[start:start + 400]:
                batch.set(self._records().document(record["id"]), self._encode(record))
            batch.commit()

    def recent_records(self, limit: int) -> list[dict[str, Any]]:
        query = self._records().order_by("closedAtMs", direction=main.firestore.Query.DESCENDING).limit(limit)
        return [self.decode(snap.to_dict() or {}) for snap in query.stream()]

    def all_records(self) -> list[dict[str, Any]]:
        return [self.decode(snap.to_dict() or {}) for snap in self._records().stream()]

    # bot state (read-only) -------------------------------------------------------------------------------------
    def strategy_doc(self) -> dict[str, Any]:
        if not hasattr(self, "_strategy"):
            self._strategy = main.aster_strategy2_reference(self.uid).get().to_dict() or {}
        return self._strategy

    def auto_hedge_doc(self) -> dict[str, Any]:
        return main.db.collection("asterPositionLossAutoHedge").document(self.uid).get().to_dict() or {}

    def dynamic_hedge_doc(self) -> dict[str, Any]:
        return self.user.collection("asterDynamicHedge").document("control").get().to_dict() or {}

    def controls_doc(self) -> dict[str, Any]:
        return self.user.collection("executionControls").document("aster").get().to_dict() or {}

    def pair_doc(self, symbol: str) -> dict[str, Any]:
        return (main.db.collection("asterPositionLossAutoHedge").document(self.uid)
                .collection("pairs").document(symbol.upper()).get().to_dict() or {})

    def stored_symbols(self) -> set[str]:
        symbols: set[str] = set()
        for name, limit in (("asterClosedTrades", 5000), ("asterRealizedEvents", 5000)):
            for snap in self.user.collection(name).select(["symbol"]).limit(limit).stream():
                symbol = str((snap.to_dict() or {}).get("symbol", "")).upper().strip()
                if symbol:
                    symbols.add(symbol)
        return symbols

    # settings --------------------------------------------------------------------------------------------------
    def _settings_pointer(self):
        return self.user.collection("executionControls").document("tradeJournalSettings")

    def latest_settings_hash(self) -> str | None:
        return (self._settings_pointer().get().to_dict() or {}).get("hash")

    def save_settings_version(self, version: dict[str, Any]) -> None:
        data = {key: value for key, value in version.items() if key != "settings"}
        data["settingsJson"] = json.dumps(version.get("settings"), sort_keys=True, default=str)
        data["recordedAt"] = datetime.now(timezone.utc)
        self.user.collection("tradeSettingsVersions").document(version["id"]).set(data)
        self._settings_pointer().set({"hash": version["hash"], "versionId": version["id"],
                                      "effectiveFromMs": version["effectiveFromMs"]})

    def settings_versions(self) -> list[dict[str, Any]]:
        rows = []
        for snap in self.user.collection("tradeSettingsVersions").stream():
            row = snap.to_dict() or {}
            try:
                row["settings"] = json.loads(row.pop("settingsJson", "") or "null")
            except ValueError:
                row["settings"] = None
            row.pop("recordedAt", None)
            rows.append(row)
        return rows

    def config_history(self) -> list[dict[str, Any]]:
        rows = []
        for snap in main.aster_strategy2_reference(self.uid).collection("configHistory").stream():
            row = snap.to_dict() or {}
            rows.append({"timestampMs": _to_ms(row.get("timestamp")), "version": row.get("version"),
                         "newValue": row.get("newValue"), "source": row.get("source")})
        return rows

    # funding ---------------------------------------------------------------------------------------------------
    def merge_funding(self, events: dict[str, dict[str, float]]) -> None:
        by_month: dict[str, dict[str, dict[str, float]]] = {}
        for symbol, rows in events.items():
            for at, amount in rows.items():
                month = datetime.fromtimestamp(int(at) / 1000, tz=timezone.utc).strftime("%Y-%m")
                by_month.setdefault(month, {}).setdefault(symbol, {})[str(at)] = amount
        for month, symbols in by_month.items():
            self.user.collection("tradeJournalFunding").document(month).set({"events": symbols}, merge=True)

    def funding(self) -> dict[str, dict[str, float]]:
        merged: dict[str, dict[str, float]] = {}
        for snap in self.user.collection("tradeJournalFunding").stream():
            for symbol, rows in ((snap.to_dict() or {}).get("events") or {}).items():
                if isinstance(rows, dict):
                    merged.setdefault(symbol, {}).update(rows)
        return merged


def _client(user: dict[str, Any]) -> Any:
    secret = main.load_aster_secret(user)
    return main.AsterV3Client(signer_address=secret.signer_address,
                              sign_message=main.local_eip712_signer(secret), live_authorized=False)


def _status(control: dict[str, Any]) -> dict[str, Any]:
    known = set(control.get("knownSymbols") or [])
    read = set(control.get("readSymbols") or []) & known
    return {
        "backfillComplete": bool(control.get("backfillComplete")),
        "upToDate": bool(control.get("backfillComplete")) and not control.get("dirtySymbols"),
        "lastSyncAt": tj.iso_utc(int(control.get("lastSyncAtMs") or 0) or None),
        "progress": {"symbolsRead": len(read), "symbolsTotal": len(known),
                     "percent": round(100.0 * len(read) / len(known), 1) if known else 0.0},
    }


@main.app.get("/v1/me/aster/trade-journal/recent")
def trade_journal_recent(limit: int = Query(default=100, ge=1, le=300),
                         user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    """Firestore only (no Aster call): the newest journal records for the Trade Historie card."""
    store = FirestoreJournalStore(str(user["uid"]))
    rows = [tj.list_row(record) for record in store.recent_records(limit)]
    return {"rows": rows, **_status(store.control())}


@main.app.post("/v1/me/aster/trade-journal/sync")
def trade_journal_sync(user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    """One bounded, resumable sync step. The app repeats it until complete."""
    uid = str(user["uid"])
    lock = _user_lock(uid)
    if not lock.acquire(blocking=False):
        raise HTTPException(429, "Historie wordt al bijgewerkt")
    try:
        since = time.monotonic() - _last_sync.get(uid, 0.0)
        if since < SYNC_MIN_INTERVAL_SECONDS:
            raise HTTPException(429, "Even wachten tussen twee stappen")
        budget = _instance_budget(tj.MAX_CALLS_PER_SYNC)
        if budget < 3:
            raise HTTPException(429, "Aster-budget voor de historie is even op; probeer zo opnieuw")
        _last_sync[uid] = time.monotonic()
        store = FirestoreJournalStore(uid)
        try:
            result = tj.sync_step(store, _client(user), now_ms=_now_ms(), max_calls=budget)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - shown as text in the app, never a 500 page
            raise HTTPException(503, f"Historie kon nu niet worden bijgewerkt: {str(exc)[:160]}") from exc
        _spend(int(result.get("asterCalls") or 0))
        return result
    finally:
        lock.release()


@main.app.get("/v1/me/aster/trade-journal/export")
def trade_journal_export(user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    """Every journal record plus the settings timeline, as one JSON document for an agent."""
    uid = str(user["uid"])
    store = FirestoreJournalStore(uid)
    control = store.control()
    timeline = tj.build_settings_timeline(store.settings_versions(), store.config_history())
    return tj.build_export(
        store.all_records(), timeline, store.funding(), uid_hint=uid, generated_ms=_now_ms(),
        sync_state=control, app_build=os.getenv("TRADEMENTOR_SOURCE_COMMIT", "")[:12] or "onbekend",
    )


def capture_settings_for(uid: str, reason: str) -> bool:
    return tj.capture_settings(FirestoreJournalStore(uid), _now_ms(), reason=reason)


@main.app.middleware("http")
async def _trade_journal_settings_capture(request: Request, call_next):
    """After a successful settings save, record a settings version. Never changes or delays a failed response."""
    response = await call_next(request)
    route = (request.method.upper(), request.url.path.rstrip("/"))
    if route not in SETTINGS_ROUTES or response.status_code >= 300:
        return response
    try:
        claims = main.authenticated_user(request.headers.get("authorization"))
        await _run_in_thread(capture_settings_for, str(claims["uid"]), f"{route[0]} {route[1]}")
    except Exception:  # noqa: BLE001 - the save itself already succeeded; a missed version is caught by the next sync
        pass
    return response


async def _run_in_thread(fn, *args):
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(fn, *args)
