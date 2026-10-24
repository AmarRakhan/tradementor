"""Build 652: route voor de gemiddelde max drawdown vanaf instap (Portfolio Snapshot en Auto Hedge-scherm).

Alleen lezen. Aster: één positionRisk per berekening (signed, GET) en publieke klines. Plaatst, wijzigt of annuleert
nooit een order en raakt de trading-tick niet. Firestore: één document per gebruiker.
- users/{uid}/executionControls/entryDrawdown   samenvatting + trackers per positie (JSON)

GET geeft altijd direct de laatst bewaarde samenvatting; is die ouder dan REFRESH_SECONDS, dan start er op de
achtergrond één berekening (per gebruiker nooit twee tegelijk).
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import Depends

import main
import entry_drawdown as ed
import trade_journal_extension as tje

REFRESH_SECONDS = 180
MAX_KLINE_CALLS = 60                 # per berekening; klines zijn publiek en licht (gewicht 2-5)
KLINE_PAUSE_SECONDS = 0.05

_running: set[str] = set()
_running_guard = threading.Lock()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _doc(uid: str):
    return main.user_reference({"uid": uid}).collection("executionControls").document("entryDrawdown")


def _read(uid: str) -> dict[str, Any]:
    row = _doc(uid).get().to_dict() or {}
    for field, default in (("summaryJson", "{}"), ("trackersJson", "{}")):
        try:
            row[field[:-4]] = json.loads(row.pop(field, "") or default)
        except ValueError:
            row[field[:-4]] = {}
    return row


def _fetch_klines(client: httpx.Client) -> ed.FetchFn:
    def fetch(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[ed.Candle]:
        response = client.get("/fapi/v1/klines", params={"symbol": symbol, "interval": interval,
                                                         "startTime": start_ms, "endTime": end_ms, "limit": ed.KLINE_LIMIT})
        response.raise_for_status()
        time.sleep(KLINE_PAUSE_SECONDS)
        return ed.parse_klines(response.json())
    return fetch


def _journal_cycles(store: tje.FirestoreJournalStore, symbols: set[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for symbol in sorted(symbols):
        try:
            result[symbol] = store.symbol_state(symbol).get("cycles") or {}
        except Exception:  # noqa: BLE001
            result[symbol] = {}
    return result


def compute(uid: str) -> dict[str, Any]:
    now = _now_ms()
    cutoff = now - ed.WINDOW_DAYS * 86_400_000
    stored = _read(uid)
    trackers: dict[str, dict[str, Any]] = stored.get("trackers") if isinstance(stored.get("trackers"), dict) else {}
    store = tje.FirestoreJournalStore(uid)

    query = store._records().where("closedAtMs", ">=", cutoff)  # noqa: SLF001 - zelfde collectie, enkelvoudige index
    records = [store.decode(snap.to_dict() or {}) for snap in query.stream()]
    cycles = ed.closed_cycles(records, cutoff)

    unknown: set[str] = set()
    positions: list[dict[str, Any]] = []
    try:
        positions = [row for row in tje._client({"uid": uid}).position_risk() if isinstance(row, dict)]  # noqa: SLF001
    except Exception:  # noqa: BLE001 - zonder Aster-sleutel of bij een storing tellen alleen de gesloten posities
        positions = []
    symbols = {str(row.get("symbol") or "").upper() for row in positions if abs(ed._f(row.get("positionAmt"))) > 0}  # noqa: SLF001
    strategy = store.strategy_doc() or {}
    open_found, unknown = ed.open_cycles(positions, _journal_cycles(store, symbols),
                                         strategy.get("multiBbPositions") if isinstance(strategy, dict) else None)
    # een gesloten cyclus met dezelfde sleutel als een open positie kan niet; open wint (nieuwste waarheid)
    cycles.update(open_found)
    if unknown:
        try:   # het journaal leest die munten bij de volgende achtergrondstap opnieuw, dan is het instapmoment bekend
            store._control_ref().set({"dirtySymbols": main.firestore.ArrayUnion(sorted(unknown))}, merge=True)  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass

    with httpx.Client(base_url="https://fapi.asterdex.com", timeout=15.0) as client:
        report = ed.update_trackers(trackers, cycles, _fetch_klines(client), now_ms=now, max_calls=MAX_KLINE_CALLS)
    active = set(cycles)
    ed.prune_trackers(trackers, active, now_ms=now, cutoff_ms=cutoff)
    summary = ed.summarize(trackers, active, unknown_open=len(unknown))
    summary.update({"windowDays": ed.WINDOW_DAYS, "computedAtMs": now,
                    "complete": report["due"] <= report["calls"] and not report["errors"]})
    _doc(uid).set({"summaryJson": json.dumps(summary, sort_keys=True), "trackersJson": json.dumps(trackers, sort_keys=True),
                   "computedAtMs": now, "updatedAt": datetime.now(timezone.utc)})
    return summary


def _compute_in_background(uid: str) -> None:
    with _running_guard:
        if uid in _running:
            return
        _running.add(uid)

    def run() -> None:
        try:
            compute(uid)
        except Exception:  # noqa: BLE001 - de volgende aanvraag probeert het opnieuw
            pass
        finally:
            with _running_guard:
                _running.discard(uid)

    threading.Thread(target=run, name=f"entry-drawdown-{uid[:8]}", daemon=True).start()


@main.app.get("/v1/me/aster/entry-drawdown")
def entry_drawdown(user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    """Gemiddelde max drawdown vanaf instap per kant. Antwoordt direct; ververst op de achtergrond."""
    uid = str(user["uid"])
    stored = _read(uid)
    summary = stored.get("summary") if isinstance(stored.get("summary"), dict) else {}
    age_ms = _now_ms() - int(stored.get("computedAtMs") or 0)
    refreshing = False
    if age_ms > REFRESH_SECONDS * 1000 or not summary.get("complete", False) and age_ms > 30_000:
        _compute_in_background(uid)
        refreshing = True
    with _running_guard:
        refreshing = refreshing or uid in _running
    empty = {"avgMaxDrawdownPct": None, "count": 0, "openCount": 0, "closedCount": 0, "pending": 0}
    return {
        "long": summary.get("long") or empty, "short": summary.get("short") or empty,
        "windowDays": summary.get("windowDays", ed.WINDOW_DAYS), "computedAtMs": summary.get("computedAtMs"),
        "complete": bool(summary.get("complete")), "refreshing": refreshing,
    }
