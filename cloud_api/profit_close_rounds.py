"""Close Profits 2.1 — resumable, server-recorded Close Profits rounds.

A round is the user's one confirmed press of the green Close Profits button. It is stored on the server with one
item per SHORT. Every item is closed through the EXISTING individual close route (same guards, Auto Hedge lease,
profit check and durable marker) with a FIXED idempotency key per item and attempt:

    round:{round_id}:{symbol}:{attempt}

so a request that is repeated after a lost response is recognised instead of placing a second order, and an item
that is DONE is never closed again in the same round. A new round is only possible after the previous one is
FINISHED or ABANDONED.

When the outcome of an earlier attempt is unknown, the round first asks Aster (read-only GET of the deterministic
client order id) before deciding anything:

    FILLED                                  -> DONE
    NEW / PARTIALLY_FILLED / unreadable     -> NEEDS_CHECK (never re-ordered; the user decides)
    does not exist (after a grace period)   -> retried with attempt + 1
    CANCELED/REJECTED/EXPIRED without fill  -> retried with attempt + 1

A NEEDS_CHECK item does not block the other symbols. Two consecutive system errors pause the round (PAUSED,
resumable). This module has no FastAPI or Google imports: everything external is injected through ``RoundEnv`` so
the same code runs against the in-memory model, the Firestore emulator and production.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

PERCENTAGES = {25, 50, 75, 100}
MIN_OPEN_PNL_USD = 0.5
ROUND_LEASE = timedelta(seconds=330)          # longer than one request may run (Cloud Run timeout 300 s)
STALE_ATTEMPT = timedelta(seconds=330)        # a "prepared" attempt older than this died with its request
NOT_FOUND_GRACE = timedelta(seconds=60)       # Aster must have had time to show an accepted order
MAX_ATTEMPTS = 4
MAX_BUSY_RETRIES = 3
MAX_CONSECUTIVE_SYSTEM_ERRORS = 2
MAX_ITEMS = 200

ITEM_TERMINAL = {"DONE", "SKIPPED", "NEEDS_CHECK"}
ROUND_TERMINAL = {"FINISHED", "ABANDONED"}
ACTIVE_DOC = "_active"
COLLECTION = "asterProfitCloseRounds"

# Exact pre-order refusals of the individual route (no order was sent). Anything else is never guessed.
_TOO_SMALL = (
    re.compile(r"de gekozen gedeeltelijke sluiting is te klein voor dit contract", re.I),
    re.compile(r"past niet binnen de Aster contractregels: (Order ligt onder de minimale Aster-(hoeveelheid|orderwaarde)"
               r"|Hoeveelheid en marktprijs moeten positief zijn)\s*$", re.I),
)
_COVERAGE = re.compile(r"^[A-Z0-9]+: sluiting van [0-9.eE+-]+ SHORT zou Auto Hedge-dekking onder de gereserveerde "
                       r"[0-9.eE+-]+ brengen$")
_SKIP_EXACT = {
    "Open winst is niet meer boven de ingestelde grens; geen order geplaatst": "not_profitable",
    "De geselecteerde positie bestaat niet meer; actuele posities worden opnieuw opgehaald": "position_gone",
    "De positiegrootte is gewijzigd; controleer de actuele positie en bevestig opnieuw": "size_changed",
    "De gekozen gedeeltelijke sluiting rondt af naar de volledige positie; kies 100%": "rounds_to_full",
}
_UNCONFIRMED_EARLIER = ("Vorige sluiting van dit symbool is nog niet bevestigd; controleer Aster en gebruik de "
                        "individuele Close-knop")
_BUSY = {
    "Auto Hedge verwerkt momenteel dezelfde accountstatus; probeer de sluiting zo opnieuw",
    "De account-lease is verlopen voordat de sluiting kon starten; er is niets geplaatst, probeer opnieuw",
}


class RoundError(Exception):
    """Maps to an HTTP error in the router; never raised after an order may have been sent."""

    def __init__(self, status_code: int, detail: str, round_view: dict[str, Any] | None = None):
        super().__init__(detail)
        self.status_code, self.detail, self.round_view = status_code, detail, round_view


@dataclass
class RoundEnv:
    """Everything the engine needs from the outside world."""
    db: Any                                        # Firestore client (or the in-memory model)
    transactional: Callable[[Callable], Callable]  # firestore.transactional
    already_exists: type                           # google_exceptions.AlreadyExists
    http_exception: type                           # the route's HTTPException type (status_code, detail)
    close_route: Callable[..., dict[str, Any]]     # main.close_one_aster_position(symbol, request, user)
    make_request: Callable[..., Any]               # builds an AsterManualCloseRequest
    client_for: Callable[[dict[str, Any]], Any]    # read-only Aster client: position_risk / exchange info / query_order
    plan: Callable[[list, int, dict], dict]        # build_profit_close_plan(rows, pct, filters) for SHORT selection
    filters: Callable[[dict], dict]                # filters_from_aster_exchange_info
    client_order_id: Callable[..., str]            # aster_execution.client_order_id
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


# ------------------------------------------------------------------------------------------------------------ helpers
def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return None


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def item_key(round_id: str, symbol: str, attempt: int) -> str:
    return f"round:{round_id}:{symbol}:{attempt}"


def intent_hash(uid: str, key: str) -> str:
    # Identical to the individual route: intent document id and the source of the Aster client order id.
    return hashlib.sha256(f"{uid}:{key}".encode()).hexdigest()


def close_client_order_id(env: RoundEnv, hash_value: str) -> str:
    # Identical to the route + execute_leg_once: id_prefix tm-manual-{hash[:18]}, action close, side short.
    return env.client_order_id(f"tm-manual-{hash_value[:18]}", "close", "short")


def _user_ref(env: RoundEnv, uid: str) -> Any:
    return env.db.collection("users").document(uid)


def _rounds(env: RoundEnv, uid: str) -> Any:
    return _user_ref(env, uid).collection(COLLECTION)


def _intent_ref(env: RoundEnv, uid: str, hash_value: str) -> Any:
    return _user_ref(env, uid).collection("asterManualCloseIntents").document(hash_value)


def _guard_ref(env: RoundEnv, uid: str, symbol: str, hash_value: str) -> Any:
    return (_user_ref(env, uid).collection("asterManualCloseOrderGuards").document(f"{symbol}__SHORT")
            .collection("intents").document(hash_value))


def _counts(items: list[dict[str, Any]]) -> dict[str, int]:
    out = {"total": len(items), "done": 0, "skipped": 0, "needsCheck": 0, "remaining": 0}
    for item in items:
        status = item.get("status")
        if status == "DONE":
            out["done"] += 1
        elif status == "SKIPPED":
            out["skipped"] += 1
        elif status == "NEEDS_CHECK":
            out["needsCheck"] += 1
        else:
            out["remaining"] += 1
    return out


def view(round_id: str, data: dict[str, Any] | None) -> dict[str, Any] | None:
    """JSON-safe public view; no lease tokens."""
    if not data:
        return None
    items = [{
        "symbol": item.get("symbol"), "side": "SHORT", "expectedQuantity": item.get("expectedQuantity"),
        "status": item.get("status"), "reason": item.get("reason"), "detail": item.get("detail"),
        "attempt": item.get("attempt", 0), "closedSize": item.get("closedSize"),
        "updatedAt": _iso(item.get("updatedAt")),
    } for item in data.get("items", [])]
    return {
        "roundId": round_id, "status": data.get("status"), "percentage": data.get("percentage"),
        "items": items, "counts": _counts(data.get("items", [])), "pauseReason": data.get("pauseReason"),
        "createdAt": _iso(data.get("createdAt")), "updatedAt": _iso(data.get("updatedAt")),
        "finishedAt": _iso(data.get("finishedAt")),
    }


def _next_item(items: list[dict[str, Any]]) -> int | None:
    for index, item in enumerate(items):
        if item.get("status") not in ITEM_TERMINAL:
            return index
    return None


# ------------------------------------------------------------------------------------------------------------ queries
def get_active(env: RoundEnv, uid: str) -> dict[str, Any] | None:
    pointer = _rounds(env, uid).document(ACTIVE_DOC).get().to_dict() or {}
    round_id = str(pointer.get("roundId") or "")
    if not round_id:
        return None
    data = _rounds(env, uid).document(round_id).get().to_dict()
    if not data or data.get("status") in ROUND_TERMINAL:
        return None
    return view(round_id, data)


def get_round(env: RoundEnv, uid: str, round_id: str) -> dict[str, Any]:
    if not round_id or round_id == ACTIVE_DOC:
        raise RoundError(404, "Ronde niet gevonden")
    data = _rounds(env, uid).document(round_id).get().to_dict()
    if not data:
        raise RoundError(404, "Ronde niet gevonden")
    return view(round_id, data)


# ------------------------------------------------------------------------------------------------------------ create
def create_round(env: RoundEnv, user: dict[str, Any], *, percentage: int, idempotency_key: str,
                 targets: list[dict[str, Any]]) -> dict[str, Any]:
    """Store the confirmed preview as a round. Only SHORTs that the server's own fresh plan still selects are kept;
    the user's confirmed quantity is the expected (full) quantity the route re-validates before any order."""
    uid = str(user["uid"])
    if percentage not in PERCENTAGES:
        raise RoundError(422, "Sluitpercentage moet 25, 50, 75 of 100 zijn")
    if not targets or len(targets) > MAX_ITEMS:
        raise RoundError(422, "Geen geldige posities in de bevestigde preview")
    round_id = intent_hash(uid, f"profit-close-round:{idempotency_key}")[:24]
    round_ref = _rounds(env, uid).document(round_id)
    existing = round_ref.get().to_dict()
    if existing:                                   # same confirmation sent again (lost response): same round
        return {"created": False, "round": view(round_id, existing)}

    try:
        client = env.client_for(user)
        rows = list(client.position_risk())
        plan = env.plan(rows, percentage, env.filters(client.public_exchange_info()))
    except Exception as exc:
        raise RoundError(502, "Aster-posities of contractregels niet betrouwbaar beschikbaar; er is niets gestart") from exc
    planned = {str(item.get("symbol", "")).upper() for item in plan.get("selected", [])
               if str(item.get("side", "")).upper() == "SHORT"}
    now = env.now()
    items, seen = [], set()
    for target in targets:
        symbol = str(target.get("symbol", "")).upper().strip()
        side = str(target.get("side", "SHORT")).upper().strip()
        try:
            quantity = abs(float(target.get("quantity")))
        except (TypeError, ValueError):
            quantity = 0.0
        if not re.fullmatch(r"[A-Z0-9]{2,30}", symbol) or side != "SHORT" or symbol in seen:
            continue
        seen.add(symbol)
        base = {"symbol": symbol, "expectedQuantity": quantity, "attempt": 0, "busyRetries": 0, "updatedAt": now}
        if not quantity > 0:
            items.append({**base, "status": "SKIPPED", "reason": "invalid_quantity"})
        elif symbol not in planned:
            items.append({**base, "status": "SKIPPED", "reason": "no_longer_eligible"})
        else:
            items.append({**base, "status": "PENDING"})
    if not items:
        raise RoundError(422, "Geen geldige posities in de bevestigde preview")

    data = {
        "status": "RUNNING", "percentage": percentage, "items": items, "createdAt": now, "updatedAt": now,
        "consecutiveSystemErrors": 0, "lease": {"token": "", "until": now},
        "idempotencyKeyHash": hashlib.sha256(idempotency_key.encode()).hexdigest(),
    }
    if _next_item(items) is None:
        data.update({"status": "FINISHED", "finishedAt": now})
    active_ref = _rounds(env, uid).document(ACTIVE_DOC)

    @env.transactional
    def reserve(txn):
        pointer = active_ref.get(transaction=txn).to_dict() or {}
        current_id = str(pointer.get("roundId") or "")
        if current_id and current_id != round_id:
            current = _rounds(env, uid).document(current_id).get(transaction=txn).to_dict()
            if current and current.get("status") not in ROUND_TERMINAL:
                return ("busy", current_id, current)
        same = round_ref.get(transaction=txn).to_dict()
        if same:
            return ("same", round_id, same)
        txn.set(round_ref, data)
        if data["status"] not in ROUND_TERMINAL:
            txn.set(active_ref, {"roundId": round_id, "updatedAt": now})
        return ("created", round_id, data)

    try:
        outcome, rid, stored = reserve(env.db.transaction())
    except Exception as exc:
        # Contention (Firestore gives up after its retries) or a transient store error: never guess. Re-read and
        # answer from what is actually stored; nothing was ordered either way.
        pointer = active_ref.get().to_dict() or {}
        current_id = str(pointer.get("roundId") or "")
        current = _rounds(env, uid).document(current_id).get().to_dict() if current_id else None
        if current_id == round_id and current:
            return {"created": False, "round": view(round_id, current)}
        if current and current.get("status") not in ROUND_TERMINAL:
            raise RoundError(409, "Er loopt nog een Close Profits-ronde; hervat of sluit die eerst af",
                             view(current_id, current)) from exc
        raise RoundError(503, "Close Profits kon niet starten; er is niets gesloten, probeer opnieuw") from exc
    if outcome == "busy":
        raise RoundError(409, "Er loopt nog een Close Profits-ronde; hervat of sluit die eerst af", view(rid, stored))
    return {"created": outcome == "created", "round": view(rid, stored)}


# ------------------------------------------------------------------------------------------------------------ lease
def _acquire(env: RoundEnv, uid: str, round_id: str) -> tuple[str | None, dict[str, Any] | None]:
    ref = _rounds(env, uid).document(round_id)
    token = secrets.token_hex(16)

    @env.transactional
    def take(txn):
        data = ref.get(transaction=txn).to_dict()
        if not data:
            return None, None
        if data.get("status") in ROUND_TERMINAL:
            return None, data
        now = env.now()
        lease = data.get("lease") or {}
        until = _utc(lease.get("until"))
        if lease.get("token") and until and until > now:
            return None, data
        txn.set(ref, {"lease": {"token": token, "until": now + ROUND_LEASE}, "updatedAt": now}, merge=True)
        return token, data

    return take(env.db.transaction())


def _commit(env: RoundEnv, uid: str, round_id: str, token: str, mutate: Callable[[dict[str, Any]], None]) -> dict:
    """Apply `mutate` to the stored round under OUR lease and release it. Abandon by the user always wins."""
    ref = _rounds(env, uid).document(round_id)
    active_ref = _rounds(env, uid).document(ACTIVE_DOC)

    @env.transactional
    def write(txn):
        data = ref.get(transaction=txn).to_dict() or {}
        pointer = active_ref.get(transaction=txn).to_dict() or {}    # all reads before any write (Firestore)
        lease = data.get("lease") or {}
        if lease.get("token") == token:
            if data.get("status") not in ROUND_TERMINAL:
                mutate(data)
            now = env.now()
            data["updatedAt"] = now
            data["lease"] = {"token": "", "until": now}
            if data.get("status") not in ROUND_TERMINAL:
                if data.get("abandonRequested"):
                    data["status"], data["finishedAt"] = "ABANDONED", now
                elif _next_item(data.get("items", [])) is None:
                    data["status"], data["finishedAt"] = "FINISHED", now
            txn.set(ref, data)
            if data.get("status") in ROUND_TERMINAL and pointer.get("roundId") == round_id:
                txn.set(active_ref, {"roundId": "", "updatedAt": now})
        return data

    last: Exception | None = None
    for _ in range(3):                         # an item result must not be lost to transient contention
        try:
            return write(env.db.transaction())
        except Exception as exc:               # if all fail, the lease expires and the next advance re-reads the
            last = exc                         # attempt's own intent document (confirmed_closed -> DONE): no double
    raise RoundError(503, "Voortgang tijdelijk niet opgeslagen; de ronde gaat verder na de volgende stap") from last


# ------------------------------------------------------------------------------------------------------------ outcome
def _status_of(exc: Exception) -> tuple[int, str]:
    return int(getattr(exc, "status_code", 500) or 500), str(getattr(exc, "detail", exc))


def _classify_refusal(detail: str) -> tuple[str, str] | None:
    """Pre-order refusal -> (item status, reason). None = not a known pre-order refusal."""
    if any(pattern.search(detail) for pattern in _TOO_SMALL):
        return "SKIPPED", "too_small"
    if _COVERAGE.match(detail):
        return "SKIPPED", "auto_hedge_coverage"
    if detail in _SKIP_EXACT:
        return "SKIPPED", _SKIP_EXACT[detail]
    if detail == _UNCONFIRMED_EARLIER:
        return "NEEDS_CHECK", "earlier_close_unconfirmed"
    return None


def _reconcile(env: RoundEnv, user: dict[str, Any], symbol: str, hash_value: str,
               intent: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """An attempt whose order MAY have reached Aster: ask Aster, read-only, before anything else.
    Returns (decision, extra) with decision in DONE | NEEDS_CHECK | RETRY | WAIT."""
    started = _utc(intent.get("orderStartedAt")) or _utc(intent.get("createdAt"))
    cid = close_client_order_id(env, hash_value)
    try:
        order = env.client_for(user).query_order(symbol, cid) or {}
    except Exception as exc:
        text = str(exc)
        if "-2013" in text or "Order does not exist" in text:
            if started is None or env.now() - started < NOT_FOUND_GRACE:
                return "WAIT", {"detail": "Aster toont de order nog niet; even wachten"}
            return "RETRY", {"reason": "order_not_found_on_aster"}
        return "NEEDS_CHECK", {"reason": "aster_query_failed", "detail": "Orderstatus bij Aster niet leesbaar"}
    status = str(order.get("status", "")).upper()
    try:
        executed = float(order.get("executedQty") or 0)
    except (TypeError, ValueError):
        executed = -1.0
    if status == "FILLED":
        return "DONE", {"reason": "confirmed_by_aster_query", "closedSize": executed if executed > 0 else None}
    if status in {"CANCELED", "REJECTED", "EXPIRED"} and executed == 0:
        return "RETRY", {"reason": f"order_{status.lower()}_without_fill"}
    return "NEEDS_CHECK", {"reason": "order_not_final", "detail": f"Aster-orderstatus {status or 'onbekend'}"}


def _mark_guard(env: RoundEnv, uid: str, symbol: str, hash_value: str) -> None:
    """The attempt is resolved (filled, or proven absent): it must no longer block this symbol's next close."""
    try:
        _guard_ref(env, uid, symbol, hash_value).set({"status": "confirmed_closed"}, merge=True)
    except Exception:
        pass


def _process(env: RoundEnv, user: dict[str, Any], round_id: str, item: dict[str, Any],
             percentage: int) -> tuple[dict[str, Any], str]:
    """Advance ONE item by one step. Returns (item patch, kind) with kind ok | system | pause | wait."""
    uid = str(user["uid"])
    symbol = str(item["symbol"])
    attempt = int(item.get("attempt", 0))
    key = item_key(round_id, symbol, attempt)
    hash_value = intent_hash(uid, key)
    now = env.now()
    retry = {"status": "PENDING", "attempt": attempt + 1, "updatedAt": now}
    if attempt >= MAX_ATTEMPTS:
        return {"status": "NEEDS_CHECK", "reason": "too_many_attempts", "updatedAt": now}, "ok"

    previous = _intent_ref(env, uid, hash_value).get().to_dict()
    if previous:                                              # this exact attempt already reached the route
        state = str(previous.get("status", ""))
        if state == "confirmed_closed":
            return {"status": "DONE", "reason": "confirmed_closed", "closedSize": previous.get("closedQuantity"),
                    "updatedAt": now}, "ok"
        if previous.get("orderMayHaveBeenSent"):
            if state == "prepared":
                started = _utc(previous.get("orderStartedAt")) or _utc(previous.get("createdAt"))
                if started and now - started < STALE_ATTEMPT:
                    return {"status": "IN_PROGRESS", "updatedAt": now}, "wait"
            decision, extra = _reconcile(env, user, symbol, hash_value, previous)
            if decision == "WAIT":
                return {"status": "UNCERTAIN", **extra, "updatedAt": now}, "wait"
            if decision == "DONE":
                _mark_guard(env, uid, symbol, hash_value)
                return {"status": "DONE", **extra, "updatedAt": now}, "ok"
            if decision == "RETRY":
                _mark_guard(env, uid, symbol, hash_value)
                return {**retry, **extra}, "ok"
            return {"status": "NEEDS_CHECK", **extra, "updatedAt": now}, "ok"
        # No order was sent for this attempt.
        if state == "prepared":
            created = _utc(previous.get("createdAt"))
            if created and now - created < STALE_ATTEMPT:
                return {"status": "IN_PROGRESS", "updatedAt": now}, "wait"
            return {**retry, "reason": "attempt_died_before_order"}, "system"
        classified = _classify_refusal(str(previous.get("detail", "")))
        if state == "blocked_hedge_lock":
            return {"status": "SKIPPED", "reason": classified[1] if classified else "auto_hedge_lock",
                    "detail": previous.get("detail"), "updatedAt": now}, "ok"
        if classified:
            return {"status": classified[0], "reason": classified[1], "detail": previous.get("detail"),
                    "updatedAt": now}, "ok"
        return {**retry, "reason": "earlier_attempt_failed_before_order"}, "system"

    # 2.0 parity (the browser's fresh check before EVERY close, now on the server): the SHORT must appear exactly
    # once in a reliable position snapshot right before the route is called. Missing -> skipped; duplicate or
    # contradictory rows -> NEEDS_CHECK; unreadable snapshot -> system error. No order in any of these cases.
    try:
        rows = env.client_for(user).position_risk()
        if not isinstance(rows, list):
            raise ValueError("position snapshot is not a list")
        matches = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("position row is not an object")
            if (str(row.get("symbol", "")).upper() == symbol and str(row.get("positionSide", "")).upper() == "SHORT"
                    and abs(float(row.get("positionAmt") or 0)) > 0):
                matches.append(row)
    except Exception as exc:
        return {**retry, "reason": "positions_unreadable", "detail": str(exc)[:200]}, "system"
    if not matches:
        return {"status": "SKIPPED", "reason": "position_gone", "updatedAt": now}, "ok"
    if len(matches) > 1:
        return {"status": "NEEDS_CHECK", "reason": "position_ambiguous",
                "detail": f"{len(matches)} SHORT-regels voor {symbol} in de positiedata", "updatedAt": now}, "ok"

    request = env.make_request(
        confirm=True, side="SHORT", expected_quantity=float(item["expectedQuantity"]), percentage=percentage,
        idempotency_key=key, min_open_pnl_usd=MIN_OPEN_PNL_USD, bulk_series=True,
    )
    try:
        result = env.close_route(symbol, request, user)
        return {"status": "DONE", "reason": "closed", "closedSize": (result or {}).get("closedSize"),
                "updatedAt": env.now()}, "ok"
    except Exception as exc:                                  # the route's own HTTPException or anything else
        code, detail = _status_of(exc)
    after = _intent_ref(env, uid, hash_value).get().to_dict() or {}
    if after.get("orderMayHaveBeenSent"):
        decision, extra = _reconcile(env, user, symbol, hash_value, after)
        if decision == "DONE":
            _mark_guard(env, uid, symbol, hash_value)
            return {"status": "DONE", **extra, "updatedAt": env.now()}, "ok"
        if decision == "RETRY":
            _mark_guard(env, uid, symbol, hash_value)
            return {**retry, **extra}, "ok"
        if decision == "WAIT":
            return {"status": "UNCERTAIN", "detail": detail, "updatedAt": env.now()}, "wait"
        return {"status": "NEEDS_CHECK", **extra, "updatedAt": env.now()}, "ok"
    if after.get("status") == "blocked_hedge_lock":             # Auto Hedge lock refused before any order
        classified = _classify_refusal(detail)
        return {"status": "SKIPPED", "reason": classified[1] if classified else "auto_hedge_lock", "detail": detail,
                "updatedAt": env.now()}, "ok"
    if code == 423:
        return {**retry, "reason": "execution_disabled", "detail": detail}, "pause"
    if detail in _BUSY:
        busy = int(item.get("busyRetries", 0)) + 1
        if busy > MAX_BUSY_RETRIES:
            return {"status": "SKIPPED", "reason": "account_busy", "detail": detail, "busyRetries": busy,
                    "updatedAt": env.now()}, "ok"
        return {**retry, "reason": "account_busy", "busyRetries": busy}, "wait"
    classified = _classify_refusal(detail)
    if classified:
        return {"status": classified[0], "reason": classified[1], "detail": detail, "updatedAt": env.now()}, "ok"
    if code == 409 and not after:                             # refused before the intent existed (e.g. duplicate)
        return {**retry, "reason": "refused_before_intent", "detail": detail}, "system"
    return {**retry, "reason": "system_error", "detail": detail}, "system"


# ------------------------------------------------------------------------------------------------------------ advance
def advance(env: RoundEnv, user: dict[str, Any], round_id: str) -> dict[str, Any]:
    """Process at most one item. Safe to call repeatedly and concurrently (one caller holds the round lease)."""
    uid = str(user["uid"])
    if not round_id or round_id == ACTIVE_DOC:
        raise RoundError(404, "Ronde niet gevonden")
    token, data = _acquire(env, uid, round_id)
    if data is None:
        raise RoundError(404, "Ronde niet gevonden")
    if token is None:
        return {"busy": data.get("status") not in ROUND_TERMINAL, "round": view(round_id, data)}
    index = _next_item(data.get("items", []))
    if index is None:
        stored = _commit(env, uid, round_id, token, lambda d: None)
        return {"busy": False, "round": view(round_id, stored)}
    item = dict(data["items"][index])
    try:
        patch, kind = _process(env, user, round_id, item, int(data.get("percentage", 25)))
    except Exception as exc:                                  # engine-level failure: nothing decided, stay put
        patch, kind = {"reason": "round_engine_error", "detail": str(exc)[:200]}, "system"

    def mutate(d: dict[str, Any]) -> None:
        items = d.get("items", [])
        if index < len(items) and items[index].get("symbol") == item["symbol"]:
            items[index] = {**items[index], **patch}
        if d.get("status") == "PAUSED":
            d["status"] = "RUNNING"
            d.pop("pauseReason", None)
        if kind == "system":
            d["consecutiveSystemErrors"] = int(d.get("consecutiveSystemErrors", 0)) + 1
            if d["consecutiveSystemErrors"] >= MAX_CONSECUTIVE_SYSTEM_ERRORS:
                d["status"], d["pauseReason"] = "PAUSED", "system_errors"
        elif kind == "pause":
            d["status"], d["pauseReason"] = "PAUSED", "execution_disabled"
        elif kind == "ok":
            d["consecutiveSystemErrors"] = 0

    stored = _commit(env, uid, round_id, token, mutate)
    return {"busy": False, "waiting": kind == "wait", "round": view(round_id, stored)}


def resume(env: RoundEnv, user: dict[str, Any], round_id: str) -> dict[str, Any]:
    """PAUSED -> RUNNING (the next advance retries the same item)."""
    uid = str(user["uid"])
    token, data = _acquire(env, uid, round_id)
    if data is None:
        raise RoundError(404, "Ronde niet gevonden")
    if token is None:
        return {"busy": data.get("status") not in ROUND_TERMINAL, "round": view(round_id, data)}

    def mutate(d: dict[str, Any]) -> None:
        if d.get("status") == "PAUSED":
            d["status"], d["consecutiveSystemErrors"] = "RUNNING", 0
            d.pop("pauseReason", None)

    return {"busy": False, "round": view(round_id, _commit(env, uid, round_id, token, mutate))}


def abandon(env: RoundEnv, user: dict[str, Any], round_id: str) -> dict[str, Any]:
    """The user closes the round: remaining items are never processed. An item whose order is already underway
    (lease held) finishes; its result is still recorded, but no next item is started."""
    uid = str(user["uid"])
    ref = _rounds(env, uid).document(round_id)
    active_ref = _rounds(env, uid).document(ACTIVE_DOC)

    @env.transactional
    def close(txn):
        data = ref.get(transaction=txn).to_dict()
        pointer = active_ref.get(transaction=txn).to_dict() or {}    # all reads before any write (Firestore)
        if not data:
            return None
        if data.get("status") in ROUND_TERMINAL:
            return data
        now = env.now()
        lease = data.get("lease") or {}
        until = _utc(lease.get("until"))
        if lease.get("token") and until and until > now:
            data["abandonRequested"] = True
            txn.set(ref, {"abandonRequested": True, "updatedAt": now}, merge=True)
            return data
        data.update({"status": "ABANDONED", "finishedAt": now, "updatedAt": now})
        txn.set(ref, {"status": "ABANDONED", "finishedAt": now, "updatedAt": now}, merge=True)
        if pointer.get("roundId") == round_id:
            txn.set(active_ref, {"roundId": "", "updatedAt": now})
        return data

    data = close(env.db.transaction())
    if data is None:
        raise RoundError(404, "Ronde niet gevonden")
    return {"round": view(round_id, data), "pending": bool(data.get("abandonRequested")) and
            data.get("status") not in ROUND_TERMINAL}
