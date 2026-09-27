"""Server-authoritative Profit Push Notifications 1.0.

Read-only with respect to trading: this module consumes confirmed exchange
close/Portfolio-TP evidence, persists notification policy/events and delivers
standards-based Web Push.  It never submits, cancels or changes an order.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import base64
import hashlib
import json
import logging
import math
import os
import time
from typing import Any, Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, HTTPException, Query
from google.api_core import exceptions as google_exceptions
from google.cloud import firestore
from pydantic import BaseModel, Field
from pywebpush import WebPushException, webpush


LOGGER = logging.getLogger("tradementor.profit_notifications")
DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "tradeProfitEnabled": True,
    "mode": "SUMMARY",
    "intervalMinutes": 30,
    "minimumProfitUsd": 0.50,
    "portfolioTpEnabled": True,
    "refreshBalancesAtDispatch": True,
}
SUPPORTED_INTERVALS = {15, 30, 60}
MAX_EVENT_QUERY = 2500


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _now_ms() -> int:
    return int(time.time() * 1000)


def _doc_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _money(value: Any, *, signed: bool = False) -> str:
    amount = _number(value)
    prefix = "+" if signed and amount >= 0 else ("-" if amount < 0 else "")
    absolute = abs(amount)
    whole, fraction = f"{absolute:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return prefix + "$" + grouped + "," + fraction


def normalize_settings(source: dict[str, Any] | None) -> dict[str, Any]:
    raw = source if isinstance(source, dict) else {}
    mode = str(raw.get("mode", DEFAULT_SETTINGS["mode"])).upper().strip()
    if mode not in {"EVERY_WIN", "SUMMARY"}:
        mode = "SUMMARY"
    interval = _integer(raw.get("intervalMinutes"), 30)
    if interval not in SUPPORTED_INTERVALS:
        interval = 30
    minimum = max(0.0, min(1_000_000.0, _number(raw.get("minimumProfitUsd"), 0.50)))
    return {
        "enabled": bool(raw.get("enabled", DEFAULT_SETTINGS["enabled"])),
        "tradeProfitEnabled": bool(raw.get("tradeProfitEnabled", DEFAULT_SETTINGS["tradeProfitEnabled"])),
        "mode": mode,
        "intervalMinutes": interval,
        "minimumProfitUsd": round(minimum, 8),
        "portfolioTpEnabled": bool(raw.get("portfolioTpEnabled", DEFAULT_SETTINGS["portfolioTpEnabled"])),
        "refreshBalancesAtDispatch": bool(raw.get("refreshBalancesAtDispatch", DEFAULT_SETTINGS["refreshBalancesAtDispatch"])),
    }


def qualifying_profit(realized_net_pnl: Any, minimum_profit_usd: Any) -> bool:
    pnl = _number(realized_net_pnl)
    threshold = max(0.0, _number(minimum_profit_usd))
    return pnl > 0.0 and pnl + 1e-12 >= threshold


def completed_window_for_event(event_ms: int, interval_minutes: int) -> tuple[int, int]:
    width = max(1, int(interval_minutes)) * 60_000
    start = int(event_ms) // width * width
    return start, start + width


def aggregate_profit_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in events if _number(row.get("realizedNetPnlUsd")) > 0]
    if not eligible:
        return {"count": 0, "totalProfitUsd": 0.0, "best": None}
    best = max(
        eligible,
        key=lambda row: (
            _number(row.get("realizedNetPnlUsd")),
            _integer(row.get("occurredAtMs")),
            str(row.get("eventId", "")),
        ),
    )
    return {
        "count": len(eligible),
        "totalProfitUsd": sum(_number(row.get("realizedNetPnlUsd")) for row in eligible),
        "best": best,
    }


def trade_push_payload(event: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    symbol = str(event.get("symbol", "")).upper() or "TRADE"
    side = str(event.get("side", "")).upper()
    profit = _number(event.get("realizedNetPnlUsd"))
    portfolio = _number(account.get("portfolioValue"))
    available = _number(account.get("available"))
    side_part = f" · {side}" if side in {"LONG", "SHORT"} else ""
    return {
        "type": "trade_profit",
        "eventId": str(event.get("eventId", "")),
        "title": "🏆 Trade gesloten met winst!",
        "body": (
            f"{symbol}{side_part}  {_money(profit, signed=True)}\n"
            f"Portfolio: {_money(portfolio)} · Available: {_money(available)}"
        ),
        "tag": f"amar-profit-{str(event.get('eventId', ''))[:40]}",
        "url": "/",
        "icon": "/tradementor-icon-192.png",
        "badge": "/tradementor-icon-192.png",
        "data": {
            "symbol": symbol,
            "side": side,
            "profitUsd": profit,
            "portfolioValue": portfolio,
            "available": available,
        },
    }


def summary_push_payload(events: list[dict[str, Any]], interval_minutes: int, account: dict[str, Any],
                         window_start_ms: int, window_end_ms: int) -> dict[str, Any]:
    summary = aggregate_profit_events(events)
    best = summary["best"] or {}
    symbol = str(best.get("symbol", "")).upper() or "TRADE"
    side = str(best.get("side", "")).upper()
    side_part = f" {side}" if side in {"LONG", "SHORT"} else ""
    portfolio = _number(account.get("portfolioValue"))
    available = _number(account.get("available"))
    best_profit = _number(best.get("realizedNetPnlUsd"))
    total = _number(summary.get("totalProfitUsd"))
    return {
        "type": "profit_summary",
        "eventId": f"summary:{window_start_ms}:{window_end_ms}",
        "title": f"🏆 Mooiste winst · afgelopen {interval_minutes} min",
        "body": (
            f"{symbol}{side_part} {_money(best_profit, signed=True)}\n"
            f"{summary['count']} winsttrades · {_money(total, signed=True)} totaal\n"
            f"Portfolio nu: {_money(portfolio)} · Available nu: {_money(available)}"
        ),
        "tag": f"amar-profit-summary-{window_end_ms}",
        "url": "/",
        "icon": "/tradementor-icon-192.png",
        "badge": "/tradementor-icon-192.png",
        "data": {
            "symbol": symbol,
            "side": side,
            "bestProfitUsd": best_profit,
            "tradeCount": int(summary["count"]),
            "totalProfitUsd": total,
            "portfolioValue": portfolio,
            "available": available,
            "windowStartMs": window_start_ms,
            "windowEndMs": window_end_ms,
            "intervalMinutes": interval_minutes,
        },
    }


def portfolio_tp_push_payload(event: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    cycle_profit = _number(event.get("cycleProfitUsd"))
    portfolio = _number(account.get("portfolioValue"))
    available = _number(account.get("available"))
    return {
        "type": "portfolio_take_profit",
        "eventId": str(event.get("eventId", "")),
        "title": "🎯 Portfolio Take Profit behaald!",
        "body": (
            f"Doel bereikt · Cycluswinst {_money(cycle_profit, signed=True)}\n"
            f"Portfolio nu: {_money(portfolio)} · Available nu: {_money(available)}"
        ),
        "tag": f"amar-portfolio-tp-{str(event.get('cycleId', ''))[:36]}",
        "url": "/",
        "icon": "/tradementor-icon-192.png",
        "badge": "/tradementor-icon-192.png",
        "data": {
            "cycleId": str(event.get("cycleId", "")),
            "cycleProfitUsd": cycle_profit,
            "portfolioValue": portfolio,
            "available": available,
        },
    }


class NotificationSettingsRequest(BaseModel):
    enabled: bool = False
    tradeProfitEnabled: bool = True
    mode: str = Field(default="SUMMARY", max_length=20)
    intervalMinutes: int = 30
    minimumProfitUsd: float = 0.50
    portfolioTpEnabled: bool = True
    refreshBalancesAtDispatch: bool = True


class PushSubscriptionRequest(BaseModel):
    endpoint: str = Field(min_length=8, max_length=4096)
    p256dh: str = Field(min_length=16, max_length=1024)
    auth: str = Field(min_length=4, max_length=512)
    expirationTime: int | None = None
    platform: str = Field(default="web", max_length=80)
    userAgent: str = Field(default="", max_length=500)


class PushSubscriptionRemoveRequest(BaseModel):
    endpoint: str = Field(min_length=8, max_length=4096)


class ProfitNotificationService:
    def __init__(self, db: Any):
        self.db = db

    def _user(self, uid: str) -> Any:
        return self.db.collection("users").document(str(uid))

    def _settings_ref(self, uid: str) -> Any:
        return self._user(uid).collection("preferences").document("profitNotifications")

    def _events(self, uid: str) -> Any:
        return self._user(uid).collection("notificationEvents")

    def _state_ref(self, uid: str) -> Any:
        return self._user(uid).collection("notificationState").document("profitPush")

    def _metrics_ref(self, uid: str) -> Any:
        return self._user(uid).collection("notificationState").document("metrics")

    def _control_ref(self, uid: str) -> Any:
        return self.db.collection("profitNotificationControls").document(str(uid))

    def _dispatches(self, uid: str) -> Any:
        return self._user(uid).collection("notificationDispatches")

    def _devices(self, uid: str) -> Any:
        return self._user(uid).collection("devices")

    def _metric(self, uid: str, field: str) -> None:
        try:
            self._metrics_ref(uid).set({
                field: firestore.Increment(1),
                "updatedAt": datetime.now(timezone.utc),
            }, merge=True)
        except Exception:
            LOGGER.debug("profit notification metric write failed", exc_info=True)

    def _log(self, event: str, uid: str, **details: Any) -> None:
        LOGGER.info(json.dumps({"event": event, "uidSuffix": str(uid)[-8:], **details}, default=str, sort_keys=True))

    def get_settings(self, uid: str) -> dict[str, Any]:
        stored = self._settings_ref(uid).get().to_dict() or {}
        normalized = normalize_settings(stored)
        normalized["enabledAtMs"] = _integer(stored.get("enabledAtMs"), 0)
        normalized["updatedAtMs"] = _integer(stored.get("updatedAtMs"), 0)
        return normalized

    def subscription_status(self, uid: str) -> dict[str, Any]:
        rows = []
        try:
            rows = [doc.to_dict() or {} for doc in self._devices(uid).where("kind", "==", "webpush").stream()]
        except Exception:
            rows = []
        active = [row for row in rows if bool(row.get("active", True)) and str(row.get("endpoint", "")).startswith("https://")]
        return {"activeSubscriptions": len(active), "deliveryState": "SUBSCRIBED" if active else "NO_ACTIVE_SUBSCRIPTION"}

    def public_settings(self, uid: str) -> dict[str, Any]:
        return {**self.get_settings(uid), **self.subscription_status(uid)}

    def save_settings(self, uid: str, source: dict[str, Any]) -> dict[str, Any]:
        previous = self.get_settings(uid)
        normalized = normalize_settings(source)
        now_ms = _now_ms()
        enabled_at = _integer(previous.get("enabledAtMs"), 0)
        if normalized["enabled"] and (not previous.get("enabled") or enabled_at <= 0):
            enabled_at = now_ms
        payload = {**normalized, "enabledAtMs": enabled_at, "updatedAtMs": now_ms,
                   "updatedAt": datetime.now(timezone.utc), "schemaVersion": 1}
        self._settings_ref(uid).set(payload, merge=True)
        self._control_ref(uid).set({"uid": str(uid), "enabled": normalized["enabled"],
                                    "updatedAtMs": now_ms, "updatedAt": datetime.now(timezone.utc)}, merge=True)
        if previous.get("enabled") and not normalized["enabled"]:
            self._cancel_pending(uid, event_type=None, reason="USER_DISABLED_PUSH")
        elif previous.get("tradeProfitEnabled") and not normalized["tradeProfitEnabled"]:
            self._cancel_pending(uid, event_type="TRADE_PROFIT", reason="USER_DISABLED_TRADE_PROFIT")
        if previous.get("portfolioTpEnabled") and not normalized["portfolioTpEnabled"]:
            self._cancel_pending(uid, event_type="PORTFOLIO_TP", reason="USER_DISABLED_PORTFOLIO_TP")
        self._log("notification settings saved", uid, enabled=normalized["enabled"], mode=normalized["mode"])
        return self.public_settings(uid)

    def _cancel_pending(self, uid: str, *, event_type: str | None, reason: str) -> None:
        try:
            docs = list(self._events(uid).where("status", "==", "PENDING").limit(MAX_EVENT_QUERY).stream())
            pending = []
            for doc in docs:
                row = doc.to_dict() or {}
                if event_type and str(row.get("type")) != event_type:
                    continue
                pending.append(doc.reference)
            for offset in range(0, len(pending), 400):
                batch = self.db.batch()
                for ref in pending[offset:offset + 400]:
                    batch.set(ref, {"status": "CANCELLED", "cancelReason": reason,
                                    "updatedAt": datetime.now(timezone.utc)}, merge=True)
                batch.commit()
        except Exception:
            LOGGER.warning("Unable to cancel pending notification events", exc_info=True)

    def _vapid_ref(self) -> Any:
        return self.db.collection("_internalSettings").document("webPushVapidV1")

    def _load_or_create_vapid(self) -> dict[str, str]:
        ref = self._vapid_ref()
        existing = ref.get().to_dict() or {}
        if existing.get("privatePem") and existing.get("publicKey"):
            return {"privatePem": str(existing["privatePem"]), "publicKey": str(existing["publicKey"])}
        private_key = ec.generate_private_key(ec.SECP256R1())
        private_pem = private_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode("ascii")
        public_bytes = private_key.public_key().public_bytes(serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint)
        public_key = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode("ascii")
        candidate = {"privatePem": private_pem, "publicKey": public_key,
                     "createdAt": datetime.now(timezone.utc), "schemaVersion": 1}
        try:
            ref.create(candidate)
            return {"privatePem": private_pem, "publicKey": public_key}
        except google_exceptions.AlreadyExists:
            winner = ref.get().to_dict() or {}
            if not winner.get("privatePem") or not winner.get("publicKey"):
                raise RuntimeError("Web Push VAPID sleutel is niet volledig opgeslagen")
            return {"privatePem": str(winner["privatePem"]), "publicKey": str(winner["publicKey"])}

    def public_vapid_key(self) -> str:
        return self._load_or_create_vapid()["publicKey"]

    def upsert_subscription(self, uid: str, source: dict[str, Any]) -> dict[str, Any]:
        endpoint = str(source.get("endpoint", "")).strip()
        if not endpoint.startswith("https://"):
            raise ValueError("Push endpoint moet HTTPS gebruiken")
        device_id = "webpush-" + hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:32]
        self._devices(uid).document(device_id).set({
            "kind": "webpush", "endpoint": endpoint,
            "keys": {"p256dh": str(source.get("p256dh", "")), "auth": str(source.get("auth", ""))},
            "expirationTime": source.get("expirationTime"), "platform": str(source.get("platform", "web"))[:80],
            "userAgent": str(source.get("userAgent", ""))[:500], "active": True,
            "updatedAt": datetime.now(timezone.utc), "lastSuccessfulDispatch": None,
        }, merge=True)
        self._log("push subscription registered", uid, deviceId=device_id)
        return {"subscribed": True, "deviceId": device_id, **self.subscription_status(uid)}

    def remove_subscription(self, uid: str, endpoint: str) -> dict[str, Any]:
        device_id = "webpush-" + hashlib.sha256(str(endpoint).strip().encode("utf-8")).hexdigest()[:32]
        self._devices(uid).document(device_id).set({"active": False, "disabledAt": datetime.now(timezone.utc),
                                                    "updatedAt": datetime.now(timezone.utc)}, merge=True)
        return {"removed": True, **self.subscription_status(uid)}

    def _create_event(self, uid: str, event_key: str, payload: dict[str, Any]) -> tuple[str, bool]:
        event_id = _doc_id(event_key)
        reference = self._events(uid).document(event_id)
        try:
            reference.create({**payload, "eventId": event_id, "idempotencyKeyHash": event_id,
                              "status": "PENDING", "createdAt": datetime.now(timezone.utc),
                              "updatedAt": datetime.now(timezone.utc)})
            self._metric(uid, "eventsGenerated")
            self._log("notification event created", uid, type=str(payload.get("type")), eventId=event_id[:12])
            return event_id, True
        except google_exceptions.AlreadyExists:
            self._metric(uid, "dedupePrevented")
            self._log("notification dedupe prevented", uid, eventId=event_id[:12])
            return event_id, False

    def record_trade_event(self, uid: str, *, close_event_id: str, symbol: str, side: str, strategy: str,
                           realized_net_pnl_usd: float, occurred_at_ms: int, captured_portfolio: float,
                           captured_available: float, suppressed_by_portfolio_tp: str = "") -> dict[str, Any]:
        settings = self.get_settings(uid)
        if not settings.get("enabled") or not settings.get("tradeProfitEnabled"):
            self._metric(uid, "eventsFiltered"); return {"accepted": False, "reason": "TRADE_NOTIFICATIONS_DISABLED"}
        enabled_at = _integer(settings.get("enabledAtMs"), 0)
        if enabled_at and int(occurred_at_ms) < enabled_at:
            self._metric(uid, "eventsFiltered"); return {"accepted": False, "reason": "BEFORE_NOTIFICATIONS_ENABLED"}
        if not qualifying_profit(realized_net_pnl_usd, settings.get("minimumProfitUsd")):
            self._metric(uid, "eventsFiltered"); return {"accepted": False, "reason": "NOT_POSITIVE_OR_BELOW_MINIMUM"}
        suppressed = bool(str(suppressed_by_portfolio_tp).strip() and settings.get("portfolioTpEnabled"))
        key = "|".join(("trade", str(strategy), str(symbol).upper(), str(side).upper(), str(close_event_id)))
        event_id, created = self._create_event(uid, key, {
            "type": "TRADE_PROFIT", "closeEventId": str(close_event_id), "symbol": str(symbol).upper(),
            "side": str(side).upper(), "strategy": str(strategy or "Aster"),
            "realizedNetPnlUsd": round(_number(realized_net_pnl_usd), 10), "occurredAtMs": int(occurred_at_ms),
            "capturedPortfolioValue": _number(captured_portfolio), "capturedAvailable": _number(captured_available),
            "deliveryMode": str(settings.get("mode", "SUMMARY")), "intervalMinutes": int(settings.get("intervalMinutes", 30)),
            "suppressedByPortfolioTp": str(suppressed_by_portfolio_tp) if suppressed else "",
            "eligibleForPush": not suppressed, "eligibleForInApp": not suppressed,
        })
        return {"accepted": True, "created": created, "eventId": event_id, "suppressed": suppressed}

    def record_portfolio_tp_event(self, uid: str, *, cycle_id: str, next_cycle_id: str,
                                  cycle_start_equity: float, cycle_end_equity: float,
                                  occurred_at_ms: int) -> dict[str, Any]:
        settings = self.get_settings(uid)
        if not settings.get("enabled") or not settings.get("portfolioTpEnabled"):
            self._metric(uid, "eventsFiltered"); return {"accepted": False, "reason": "PORTFOLIO_TP_NOTIFICATIONS_DISABLED"}
        enabled_at = _integer(settings.get("enabledAtMs"), 0)
        if enabled_at and int(occurred_at_ms) < enabled_at:
            return {"accepted": False, "reason": "BEFORE_NOTIFICATIONS_ENABLED"}
        event_id, created = self._create_event(uid, f"portfolio-tp|{cycle_id}|{int(occurred_at_ms)}", {
            "type": "PORTFOLIO_TP", "cycleId": str(cycle_id), "nextCycleId": str(next_cycle_id),
            "cycleStartEquity": _number(cycle_start_equity), "cycleEndEquity": _number(cycle_end_equity),
            "cycleProfitUsd": _number(cycle_end_equity) - _number(cycle_start_equity),
            "occurredAtMs": int(occurred_at_ms), "eligibleForPush": True, "eligibleForInApp": False,
        })
        return {"accepted": True, "created": created, "eventId": event_id}

    def reconcile_state(self, uid: str) -> dict[str, Any]:
        return self._state_ref(uid).get().to_dict() or {}

    def update_reconcile_state(self, uid: str, **values: Any) -> None:
        self._state_ref(uid).set({**values, "updatedAt": datetime.now(timezone.utc)}, merge=True)

    def recent_trade_events(self, uid: str, after_ms: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        rows = []
        try:
            docs = self._events(uid).order_by("occurredAtMs", direction=firestore.Query.DESCENDING).limit(max(1, min(50, limit))).stream()
            for doc in docs:
                row = doc.to_dict() or {}
                if str(row.get("type")) != "TRADE_PROFIT" or not bool(row.get("eligibleForInApp", True)):
                    continue
                if _integer(row.get("occurredAtMs")) <= int(after_ms):
                    continue
                rows.append({"eventId": str(row.get("eventId", doc.id)), "symbol": str(row.get("symbol", "")),
                    "side": str(row.get("side", "")), "realizedNetPnlUsd": _number(row.get("realizedNetPnlUsd")),
                    "occurredAtMs": _integer(row.get("occurredAtMs")),
                    "capturedPortfolioValue": _number(row.get("capturedPortfolioValue")),
                    "capturedAvailable": _number(row.get("capturedAvailable"))})
        except Exception:
            LOGGER.warning("recent notification feed failed", exc_info=True)
        rows.sort(key=lambda row: (row["occurredAtMs"], row["eventId"]))
        return rows

    def _active_subscriptions(self, uid: str) -> list[tuple[Any, dict[str, Any]]]:
        result = []
        for doc in self._devices(uid).where("kind", "==", "webpush").stream():
            row = doc.to_dict() or {}
            if not bool(row.get("active", True)):
                continue
            endpoint = str(row.get("endpoint", ""))
            keys = row.get("keys") if isinstance(row.get("keys"), dict) else {}
            if endpoint.startswith("https://") and keys.get("p256dh") and keys.get("auth"):
                result.append((doc.reference, row))
        return result

    def _send_payload(self, uid: str, payload: dict[str, Any]) -> dict[str, Any]:
        subscriptions = self._active_subscriptions(uid)
        if not subscriptions:
            self._metric(uid, "pushesFiltered")
            return {"attempted": 0, "accepted": 0, "expired": 0, "errors": 0}
        vapid = self._load_or_create_vapid()
        claims = {"sub": os.getenv("WEB_PUSH_VAPID_SUBJECT", "mailto:notifications@tradementor.app")}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        accepted = expired = errors = 0
        for reference, row in subscriptions:
            keys = row.get("keys") if isinstance(row.get("keys"), dict) else {}
            self._metric(uid, "dispatchAttempted")
            try:
                webpush(subscription_info={"endpoint": str(row.get("endpoint", "")),
                    "keys": {"p256dh": str(keys.get("p256dh", "")), "auth": str(keys.get("auth", ""))}},
                    data=body, vapid_private_key=vapid["privatePem"], vapid_claims=claims, ttl=900)
                accepted += 1
                reference.set({"lastSuccessfulDispatch": datetime.now(timezone.utc), "lastError": "",
                    "active": True, "updatedAt": datetime.now(timezone.utc)}, merge=True)
                self._metric(uid, "dispatchSuccess")
            except WebPushException as exc:
                status = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
                if status in {404, 410}:
                    expired += 1
                    reference.set({"active": False, "expiredAt": datetime.now(timezone.utc),
                        "lastError": f"HTTP {status}", "updatedAt": datetime.now(timezone.utc)}, merge=True)
                    self._metric(uid, "endpointExpired")
                else:
                    errors += 1
                    reference.set({"lastError": f"HTTP {status or 'unknown'}",
                        "updatedAt": datetime.now(timezone.utc)}, merge=True)
                    self._metric(uid, "dispatchFailed")
            except Exception as exc:
                errors += 1
                reference.set({"lastError": type(exc).__name__, "updatedAt": datetime.now(timezone.utc)}, merge=True)
                self._metric(uid, "dispatchFailed")
        self._log("push dispatch finished", uid, type=str(payload.get("type")),
                  accepted=accepted, expired=expired, errors=errors)
        return {"attempted": len(subscriptions), "accepted": accepted, "expired": expired, "errors": errors}

    def _captured_account(self, events: list[dict[str, Any]]) -> dict[str, float]:
        if not events:
            return {"portfolioValue": 0.0, "available": 0.0}
        latest = max(events, key=lambda row: _integer(row.get("occurredAtMs")))
        return {"portfolioValue": _number(latest.get("capturedPortfolioValue", latest.get("cycleEndEquity"))),
                "available": _number(latest.get("capturedAvailable"))}

    def _dispatch_account(self, settings: dict[str, Any], events: list[dict[str, Any]],
                          account_loader: Callable[[], dict[str, Any]] | None) -> dict[str, float]:
        if settings.get("refreshBalancesAtDispatch") and account_loader is not None:
            fresh = account_loader()
            return {"portfolioValue": _number(fresh.get("portfolioValue")), "available": _number(fresh.get("available"))}
        return self._captured_account(events)

    def _mark_events(self, refs: list[Any], status: str, **extra: Any) -> None:
        for offset in range(0, len(refs), 400):
            batch = self.db.batch()
            for reference in refs[offset:offset + 400]:
                batch.set(reference, {"status": status, "updatedAt": datetime.now(timezone.utc), **extra}, merge=True)
            batch.commit()

    def _already_dispatched(self, uid: str, key: str) -> bool:
        return str((self._dispatches(uid).document(_doc_id(key)).get().to_dict() or {}).get("status")) == "SENT"

    def _mark_dispatch(self, uid: str, key: str, result: dict[str, Any], payload_type: str) -> None:
        self._dispatches(uid).document(_doc_id(key)).set({"status": "SENT", "payloadType": payload_type,
            "accepted": int(result.get("accepted", 0)), "attempted": int(result.get("attempted", 0)),
            "sentAt": datetime.now(timezone.utc)}, merge=True)

    def process_pending(self, uid: str, *, account_loader: Callable[[], dict[str, Any]] | None = None,
                        now_ms: int | None = None) -> dict[str, Any]:
        settings = self.get_settings(uid)
        if not settings.get("enabled"):
            return {"processed": 0, "sent": 0, "reason": "DISABLED"}
        now_value = int(now_ms if now_ms is not None else _now_ms())
        docs = list(self._events(uid).where("status", "==", "PENDING").limit(MAX_EVENT_QUERY).stream())
        rows = [(doc.reference, doc.to_dict() or {}) for doc in docs]
        sent = processed = 0

        for reference, row in [item for item in rows if str(item[1].get("type")) == "PORTFOLIO_TP"]:
            if not bool(row.get("eligibleForPush", True)):
                self._mark_events([reference], "FILTERED"); continue
            dispatch_key = f"portfolio-tp:{row.get('eventId', reference.id)}"
            if self._already_dispatched(uid, dispatch_key):
                self._mark_events([reference], "PUSH_SENT", deliveredAtMs=now_value); continue
            result = self._send_payload(uid, portfolio_tp_push_payload(row, self._dispatch_account(settings, [row], account_loader)))
            if result["accepted"] > 0 or result["attempted"] == 0:
                self._mark_dispatch(uid, dispatch_key, result, "portfolio_take_profit")
                self._mark_events([reference], "PUSH_SENT", deliveredAtMs=now_value)
                processed += 1; sent += 1 if result["accepted"] > 0 else 0
                self._metric(uid, "portfolioTpPushDispatched")

        trade_rows = [(reference, row) for reference, row in rows
                      if str(row.get("type")) == "TRADE_PROFIT" and bool(row.get("eligibleForPush", True))]
        for reference, row in [item for item in trade_rows if str(item[1].get("deliveryMode")) == "EVERY_WIN"]:
            dispatch_key = f"trade:{row.get('eventId', reference.id)}"
            if self._already_dispatched(uid, dispatch_key):
                self._mark_events([reference], "PUSH_SENT", deliveredAtMs=now_value); continue
            result = self._send_payload(uid, trade_push_payload(row, self._dispatch_account(settings, [row], account_loader)))
            if result["accepted"] > 0 or result["attempted"] == 0:
                self._mark_dispatch(uid, dispatch_key, result, "trade_profit")
                self._mark_events([reference], "PUSH_SENT", deliveredAtMs=now_value)
                processed += 1; sent += 1 if result["accepted"] > 0 else 0

        grouped: dict[tuple[int, int, int], list[tuple[Any, dict[str, Any]]]] = defaultdict(list)
        for reference, row in trade_rows:
            if str(row.get("deliveryMode")) != "SUMMARY":
                continue
            interval = _integer(row.get("intervalMinutes"), 30)
            interval = interval if interval in SUPPORTED_INTERVALS else 30
            start, end = completed_window_for_event(_integer(row.get("occurredAtMs")), interval)
            if end <= now_value:
                grouped[(interval, start, end)].append((reference, row))

        for (interval, start, end), items in sorted(grouped.items(), key=lambda pair: pair[0][2]):
            references = [reference for reference, _row in items]
            event_rows = [row for _reference, row in items]
            summary = aggregate_profit_events(event_rows)
            if summary["count"] <= 0:
                self._mark_events(references, "FILTERED"); continue
            dispatch_key = f"summary:{interval}:{start}:{end}"
            if self._already_dispatched(uid, dispatch_key):
                self._mark_events(references, "SUMMARY_SENT", deliveredAtMs=now_value); continue
            result = self._send_payload(uid, summary_push_payload(event_rows, interval,
                self._dispatch_account(settings, event_rows, account_loader), start, end))
            if result["accepted"] > 0 or result["attempted"] == 0:
                self._mark_dispatch(uid, dispatch_key, result, "profit_summary")
                self._mark_events(references, "SUMMARY_SENT", deliveredAtMs=now_value)
                processed += len(references); sent += 1 if result["accepted"] > 0 else 0
                self._metric(uid, "summariesGenerated")

        suppressed = [reference for reference, row in rows if str(row.get("type")) == "TRADE_PROFIT"
                      and not bool(row.get("eligibleForPush", True))]
        if suppressed:
            self._mark_events(suppressed, "SUPPRESSED_PORTFOLIO_TP")
        return {"processed": processed, "sent": sent, "pending": max(0, len(rows) - processed)}

    def send_test(self, uid: str) -> dict[str, Any]:
        payload = {"type": "notification_test", "eventId": f"test:{_now_ms()}",
            "title": "🧪 Testmelding · Amar Crypto Bot 2026",
            "body": "Pushmeldingen werken. Dit is alleen een test; er is geen trade uitgevoerd of gesloten.",
            "tag": "amar-profit-test", "url": "/", "icon": "/tradementor-icon-192.png",
            "badge": "/tradementor-icon-192.png", "data": {"test": True}}
        result = self._send_payload(uid, payload)
        if result["attempted"] <= 0:
            raise ValueError("Dit apparaat heeft nog geen actieve pushsubscription.")
        if result["accepted"] <= 0:
            raise RuntimeError("De testmelding kon niet door de pushprovider worden geaccepteerd.")
        return {"sent": True, **result}


def install_profit_notification_routes(app: Any, service: ProfitNotificationService,
                                       authenticated_user: Callable[..., dict[str, Any]]) -> None:
    @app.get("/v1/me/notifications/settings")
    def get_profit_notification_settings(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        return service.public_settings(str(user["uid"]))

    @app.put("/v1/me/notifications/settings")
    def save_profit_notification_settings(request: NotificationSettingsRequest,
                                          user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        return service.save_settings(str(user["uid"]), request.model_dump())

    @app.get("/v1/me/notifications/public-key")
    def profit_notification_public_key(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        del user
        return {"publicKey": service.public_vapid_key()}

    @app.post("/v1/me/notifications/subscriptions")
    def register_profit_notification_subscription(request: PushSubscriptionRequest,
                                                  user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        try:
            return service.upsert_subscription(str(user["uid"]), request.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/v1/me/notifications/subscriptions/remove")
    def remove_profit_notification_subscription(request: PushSubscriptionRemoveRequest,
                                                user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        return service.remove_subscription(str(user["uid"]), request.endpoint)

    @app.post("/v1/me/notifications/test")
    def test_profit_notification(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        try:
            return service.send_test(str(user["uid"]))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/v1/me/notifications/recent")
    def recent_profit_notification_events(after_ms: int = Query(default=0, ge=0),
                                          user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        return {"events": service.recent_trade_events(str(user["uid"]), after_ms=after_ms, limit=20),
                "source": "confirmed-backend-profit-events"}
