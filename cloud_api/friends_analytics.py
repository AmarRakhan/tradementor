"""Read-only Friends analytics for Amar Crypto Bot 2026.

This module intentionally never calls an exchange and never exposes absolute equity,
balances, USD PnL, wallet data, account identifiers or credentials.
"""
from __future__ import annotations

import hashlib
import math
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Depends, HTTPException, Query
from firebase_admin import auth, firestore
from pydantic import BaseModel, Field

_ALLOWED_PERIODS = {"1D": 1, "7D": 7, "30D": 30, "ALL": 120}
_FRIEND_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_CACHE_SECONDS = 30.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(round(_num(value, default)))
    except (ValueError, OverflowError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _public_friend_id(uid: str) -> str:
    return hashlib.sha256(f"friends-v1:{uid}".encode("utf-8")).hexdigest()[:16]


def _period(value: str) -> str:
    normalized = str(value or "1D").upper()
    if normalized not in _ALLOWED_PERIODS:
        raise HTTPException(422, "Periode moet 1D, 7D, 30D of ALL zijn")
    return normalized


def _datetime_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return None


def _safe_name(record: Any, profile: dict[str, Any]) -> str:
    value = str(getattr(record, "display_name", "") or profile.get("displayName") or "").strip()
    if value:
        return value[:40]
    return f"Trader {_public_friend_id(str(record.uid))[-4:].upper()}"


def _today_return(daily: dict[str, Any]) -> float | None:
    start = _num(daily.get("referenceEquity"))
    last = _num(daily.get("lastObservedEquity"))
    start_flow = _num(daily.get("referenceCashflow"))
    last_flow = _num(daily.get("lastObservedCashflow"))
    if start <= 0 or last <= 0:
        return None
    return ((last - (last_flow - start_flow) - start) / start) * 100.0


def _return_rows(daily: dict[str, Any], period: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in daily.get("history", []) if isinstance(daily.get("history"), list) else []:
        if not isinstance(row, dict):
            continue
        pct = row.get("percentage")
        value = _num(pct, math.nan)
        if math.isfinite(value):
            rows.append({"date": str(row.get("date") or ""), "percentage": value})
    today = _today_return(daily)
    today_key = str(daily.get("lastObservedDate") or "")
    if today is not None:
        rows = [row for row in rows if row["date"] != today_key]
        rows.append({"date": today_key, "percentage": today})
    rows.sort(key=lambda row: row["date"])
    limit = _ALLOWED_PERIODS[period]
    return rows[-limit:] if period != "ALL" else rows[-120:]


def _performance(daily: dict[str, Any], period: str) -> dict[str, Any]:
    rows = _return_rows(daily, period)
    if not rows:
        return {
            "reliable": False, "period": period, "growthPercent": None,
            "averageDailyPercent": None, "winningDaysPercent": None,
            "maxDrawdownPercent": None, "volatilityPercent": None,
            "measuredDays": 0, "sparkline": [],
        }
    returns = [float(row["percentage"]) for row in rows]
    index = 100.0
    peak = index
    drawdown = 0.0
    spark = [0.0]
    for value in returns:
        index *= max(0.000001, 1.0 + value / 100.0)
        peak = max(peak, index)
        if peak > 0:
            drawdown = min(drawdown, (index / peak - 1.0) * 100.0)
        spark.append(round(index - 100.0, 5))
    growth = index - 100.0
    avg = sum(returns) / len(returns)
    winners = sum(value > 0 for value in returns) / len(returns) * 100.0
    volatility = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    return {
        "reliable": True,
        "period": period,
        "growthPercent": round(growth, 4),
        "averageDailyPercent": round(avg, 4),
        "winningDaysPercent": round(winners, 2),
        "maxDrawdownPercent": round(drawdown, 4),
        "volatilityPercent": round(volatility, 4),
        "measuredDays": len(returns),
        "sparkline": spark[-31:],
    }


def _setting(settings: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in settings:
            return settings.get(key)
    return default


def _risk_components(settings: dict[str, Any], sniper: dict[str, Any],
                     performance: dict[str, Any]) -> dict[str, Any]:
    sniper_settings = sniper.get("settings") if isinstance(sniper.get("settings"), dict) else {}
    configured_leverage = max(
        1,
        _int(_setting(settings, "leverage", "minimumLeverage", default=1), 1),
        _int(sniper_settings.get("leverage"), 1) if bool(sniper.get("enabled") or sniper.get("monitor")) else 1,
    )
    leverage_score = _clamp((configured_leverage - 1) / 99.0 * 10.0, 0.0, 10.0)

    long_distance = _num(_setting(settings, "longDcaDistance", "dcaDistance", default=.01), .01)
    short_distance = _num(_setting(settings, "shortDcaDistance", "dcaDistance", default=long_distance), long_distance)
    distance = max(.0001, (long_distance + short_distance) / 2.0)
    distance_pct = distance * 100.0 if distance <= 1 else distance
    max_dca = max(
        _int(_setting(settings, "maxDcaLong", "longMaxDca", "maxDca", default=0)),
        _int(_setting(settings, "maxDcaShort", "shortMaxDca", "maxDca", default=0)),
    )
    multiplier = max(1.0, _num(settings.get("dcaMultiplier"), 1.0))
    proximity = _clamp((1.0 - min(distance_pct, 1.0)) / .9 * 7.0, 0.0, 7.0)
    dca_score = _clamp(proximity + min(max_dca, 10) * .25 + min(multiplier - 1.0, 2.0), 0.0, 10.0)

    maximum_positions = max(
        _int(_setting(settings, "maximumPositions", default=0)),
        _int(_setting(settings, "maximumPairs", default=0)) * 2,
        _int(_setting(settings, "longSlots", default=0)) + _int(_setting(settings, "shortSlots", default=0)),
        _int(sniper_settings.get("maxConcurrent"), 0),
    )
    strategy_budget = _num(_setting(settings, "strategyBudget", default=.5), .5)
    gross_limit = _num(_setting(settings, "maxGrossExposureRatio", default=1.0), 1.0)
    position_score = _clamp(maximum_positions / 40.0 * 5.0 + strategy_budget * 3.0 + gross_limit * 2.0, 0.0, 10.0)

    stop_loss = bool(_setting(settings, "stopLossEnabled", default=False))
    protection = bool(_setting(settings, "protectionEnabled", default=False))
    bollinger = bool(_setting(
        settings,
        "trendBollingerEntryEnabled", "bollingerEntryFilterEnabled",
        "entryBollingerFilterEnabled", "focusV2RequireBollingerMiddle",
        default=False,
    ))
    protection_score = 8.0
    if stop_loss:
        protection_score -= 3.0
    if protection:
        protection_score -= 2.5
    if bollinger:
        protection_score -= 1.5
    protection_score = _clamp(protection_score, 0.0, 10.0)

    drawdown = abs(_num(performance.get("maxDrawdownPercent"), 0.0))
    volatility = abs(_num(performance.get("volatilityPercent"), 0.0))
    historical_score = _clamp(drawdown / 20.0 * 7.0 + volatility / 10.0 * 3.0, 0.0, 10.0)

    frequency_score = 0.0
    measured_days = max(1, _int(performance.get("measuredDays"), 1))
    active_symbols = settings.get("ownedSymbols") if isinstance(settings.get("ownedSymbols"), list) else []
    frequency_score = _clamp(len(active_symbols) / measured_days * 2.0, 0.0, 10.0)

    score = (
        leverage_score * .20
        + dca_score * .18
        + position_score * .18
        + protection_score * .14
        + historical_score * .20
        + frequency_score * .10
    )
    score = round(_clamp(score, 0.0, 10.0), 1)
    label = "Laag" if score <= 3.4 else "Gebalanceerd" if score <= 5.9 else "Verhoogd" if score <= 7.4 else "Agressief"
    return {
        "score": score,
        "label": label,
        "configuredLeverage": configured_leverage,
        "dcaDistancePercent": round(distance_pct, 3),
        "maxDca": max_dca,
        "stopLossEnabled": stop_loss,
        "protectionEnabled": protection,
        "bollingerFilterEnabled": bollinger,
        "components": {
            "leverage": round(leverage_score, 1),
            "dcaAggressiveness": round(dca_score, 1),
            "positionBuildUp": round(position_score, 1),
            "protection": round(10.0 - protection_score, 1),
            "historical": round(historical_score, 1),
        },
    }


def _strategies(settings: dict[str, Any], sniper: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    engine = str(settings.get("engine") or settings.get("strategyKind") or "").lower()
    if "multi" in engine or "zone" in engine or "maximumPositions" in settings:
        result.append({"id": "zone", "name": "Zone Strategy", "accent": "blue"})
    if bool(settings.get("focusV2Enabled")) or str(settings.get("tradingMode") or "").lower() == "focus":
        result.append({"id": "focus", "name": "Aster Focus", "accent": "green"})
    if not result and settings:
        result.append({"id": "aster", "name": "Aster", "accent": "green"})
    if sniper and (sniper.get("enabled") or sniper.get("monitor") or sniper.get("history") or sniper.get("activeTrades")):
        result.append({"id": "sniper", "name": "Sniper", "accent": "purple"})
    return result[:3]


def _safe_settings(settings: dict[str, Any], risk: dict[str, Any], sniper: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {"key": "leverage", "label": "Leverage", "value": f'{risk["configuredLeverage"]}x', "icon": "chart"},
        {"key": "dcaDistance", "label": "DCA afstand", "value": f'{risk["dcaDistancePercent"]:.2f}%', "icon": "bars"},
        {"key": "maxDca", "label": "Maximum DCA", "value": str(risk["maxDca"]), "icon": "layers"},
        {"key": "stopLoss", "label": "Stoploss", "value": "Aan" if risk["stopLossEnabled"] else "Uit", "icon": "shield"},
        {"key": "bollinger", "label": "Bollinger filter", "value": "Aan" if risk["bollingerFilterEnabled"] else "Uit", "icon": "filter"},
        {"key": "autoRestart", "label": "Auto-restart", "value": "Aan" if bool(_setting(settings, "autoRestart", "focusV2AutoRestart", default=False)) else "Uit", "icon": "restart"},
    ]
    long_slots = _int(settings.get("longSlots"))
    short_slots = _int(settings.get("shortSlots"))
    if long_slots or short_slots:
        rows.append({"key": "slots", "label": "Slotverdeling", "value": f"{long_slots}L / {short_slots}S", "icon": "users"})
    sizing = str(settings.get("entrySizingMode") or settings.get("focusSizingMode") or "").lower()
    if sizing:
        rows.append({
            "key": "sizing", "label": "Positie-opbouw",
            "value": "Relatief aan equity" if "equity" in sizing else "Vaste instap",
            "icon": "target",
        })
    tp_mode = str(_setting(settings, "takeProfitMode", "focusV2TakeProfitMode", default="")).upper()
    if tp_mode:
        rows.append({"key": "tpMode", "label": "Take Profit", "value": tp_mode.replace("_", " "), "icon": "target"})
    if sniper and (sniper.get("enabled") or sniper.get("monitor")):
        rows.append({"key": "sniper", "label": "Sniper", "value": "Actief", "icon": "bolt"})
    return rows[:10]


def _learning_points(performance: dict[str, Any], risk: dict[str, Any]) -> list[dict[str, str]]:
    points: list[dict[str, str]] = []
    winners = _num(performance.get("winningDaysPercent"), math.nan)
    if math.isfinite(winners) and winners >= 60:
        points.append({"title": "Consistentie", "text": "Relatief veel gemeten dagen sluiten positief af."})
    if risk["bollingerFilterEnabled"]:
        points.append({"title": "Selectieve entries", "text": "Een Bollinger-filter beperkt instappen tot vooraf gedefinieerde condities."})
    if risk["stopLossEnabled"] or risk["protectionEnabled"]:
        points.append({"title": "Bescherming actief", "text": "De setup gebruikt expliciete bescherming om downside te begrenzen."})
    if risk["maxDca"] > 0:
        points.append({"title": "DCA met vaste grenzen", "text": f'Maximaal {risk["maxDca"]} DCA-stappen binnen de gedeelde setup.'})
    if not points:
        points.append({"title": "Nog onvoldoende data", "text": "Meer meetdagen zijn nodig voor een onderbouwd leerpunt."})
    return points[:3]


def _last_active(record: Any, profile: dict[str, Any]) -> tuple[str | None, str]:
    value = profile.get("updatedAt")
    if isinstance(value, datetime):
        age = (datetime.now(timezone.utc) - value.astimezone(timezone.utc)).total_seconds()
        return _datetime_iso(value), "Online" if age <= 900 else "Recent" if age <= 86400 else "Offline"
    metadata = getattr(record, "user_metadata", None)
    stamp = getattr(metadata, "last_sign_in_timestamp", None) if metadata else None
    if stamp:
        seen = datetime.fromtimestamp(stamp / 1000.0, tz=timezone.utc)
        age = (datetime.now(timezone.utc) - seen).total_seconds()
        return seen.isoformat(), "Recent" if age <= 86400 else "Offline"
    return None, "Offline"


def _friend_record(db: Any, record: Any, requester_uid: str, period: str) -> dict[str, Any]:
    uid = str(record.uid)
    profile = db.collection("users").document(uid).get().to_dict() or {}
    strategy = db.collection("asterStrategy2").document(uid).get().to_dict() or {}
    sniper = db.collection("asterSniper").document(uid).get().to_dict() or {}
    settings = strategy.get("settings") if isinstance(strategy.get("settings"), dict) else {}
    growth = db.collection("users").document(uid).collection("portfolioGrowth").document("aster").get().to_dict() or {}
    daily = growth.get("dailyGrowth") if isinstance(growth.get("dailyGrowth"), dict) else {}
    performance = _performance(daily, period)
    risk = _risk_components(settings, sniper, performance)
    last_active_at, presence = _last_active(record, profile)
    safe_settings = _safe_settings(settings, risk, sniper)
    strategies = _strategies(settings, sniper)

    consistency = (_num(performance.get("winningDaysPercent"), 0.0) / 100.0)
    growth_percent = _num(performance.get("growthPercent"), 0.0)
    drawdown_penalty = abs(_num(performance.get("maxDrawdownPercent"), 0.0)) * .20
    risk_penalty = risk["score"] * .15
    ranking_score = growth_percent + consistency - drawdown_penalty - risk_penalty

    return {
        "friendId": _public_friend_id(uid),
        "isMe": uid == requester_uid,
        "name": _safe_name(record, profile),
        "initial": _safe_name(record, profile)[:1].upper(),
        "presence": presence,
        "lastActiveAt": last_active_at,
        "performance": performance,
        "risk": risk,
        "strategies": strategies,
        "settings": safe_settings,
        "learningPoints": _learning_points(performance, risk),
        "rankingScore": round(ranking_score, 5) if performance["reliable"] else None,
        "dataStatus": "LIVE_EVIDENCE" if performance["reliable"] else "INSUFFICIENT_DATA",
    }


def _all_friends(requester_uid: str, period: str) -> list[dict[str, Any]]:
    key = (requester_uid, period)
    now = time.monotonic()
    cached = _FRIEND_CACHE.get(key)
    if cached and now - cached[0] < _CACHE_SECONDS:
        return [dict(row) for row in cached[1]["traders"]]
    db = firestore.client()
    traders: list[dict[str, Any]] = []
    for record in auth.list_users().iterate_all():
        if getattr(record, "disabled", False):
            continue
        traders.append(_friend_record(db, record, requester_uid, period))
        if len(traders) >= 100:
            break
    ranked = [row for row in traders if row["rankingScore"] is not None]
    ranked.sort(key=lambda row: row["rankingScore"], reverse=True)
    rank_map = {row["friendId"]: index + 1 for index, row in enumerate(ranked)}
    for row in traders:
        row["rank"] = rank_map.get(row["friendId"])
        row.pop("rankingScore", None)
    traders.sort(key=lambda row: (row["rank"] is None, row["rank"] or 9999, row["name"].lower()))
    _FRIEND_CACHE[key] = (now, {"traders": [dict(row) for row in traders]})
    return traders


def _group(traders: list[dict[str, Any]]) -> dict[str, Any]:
    reliable = [row for row in traders if row["performance"]["reliable"]]
    daily = [row["performance"]["averageDailyPercent"] for row in reliable if row["performance"]["averageDailyPercent"] is not None]
    risks = [row["risk"]["score"] for row in traders]
    return {
        "traders": len(traders),
        "averageDailyGrowthPercent": round(sum(daily) / len(daily), 3) if daily else None,
        "averageRiskScore": round(sum(risks) / len(risks), 1) if risks else None,
        "privacy": "Geen absolute portfoliowaarden zichtbaar",
    }


def _find(traders: list[dict[str, Any]], friend_id: str) -> dict[str, Any]:
    friend = next((row for row in traders if row["friendId"] == friend_id), None)
    if not friend:
        raise HTTPException(404, "Trader niet gevonden")
    return friend


class FriendInsightRequest(BaseModel):
    text: str = Field(min_length=3, max_length=280)


def install_friends_routes(app: Any, authenticated_user: Callable[..., Any]) -> None:
    @app.get("/v1/me/friends")
    def friends_overview(period: str = Query("1D"), user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        selected = _period(period)
        traders = _all_friends(str(user["uid"]), selected)
        return {"period": selected, "group": _group(traders), "traders": traders, "privacySafe": True}

    @app.get("/v1/me/friends/compare")
    def friends_compare(period: str = Query("30D"), user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        selected = _period(period)
        traders = _all_friends(str(user["uid"]), selected)
        return {
            "period": selected,
            "traders": [{
                "friendId": row["friendId"], "name": row["name"], "initial": row["initial"],
                "performance": row["performance"], "risk": row["risk"], "strategies": row["strategies"],
            } for row in traders],
            "note": "Rendement en risico worden samen getoond; hogere risicowaarden zijn geen rangorde.",
        }

    @app.get("/v1/me/friends/insights")
    def friends_insights(user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        db = firestore.client()
        rows = []
        try:
            snapshots = db.collection("friendsInsights").order_by("createdAt", direction=firestore.Query.DESCENDING).limit(30).stream()
        except Exception:
            snapshots = db.collection("friendsInsights").limit(30).stream()
        user_map = {_public_friend_id(str(record.uid)): record for record in auth.list_users().iterate_all() if not getattr(record, "disabled", False)}
        for snapshot in snapshots:
            value = snapshot.to_dict() or {}
            friend_id = str(value.get("friendId") or "")
            record = user_map.get(friend_id)
            if not record:
                continue
            profile = db.collection("users").document(str(record.uid)).get().to_dict() or {}
            rows.append({
                "id": snapshot.id,
                "friendId": friend_id,
                "name": _safe_name(record, profile),
                "initial": _safe_name(record, profile)[:1].upper(),
                "text": str(value.get("text") or "")[:280],
                "createdAt": _datetime_iso(value.get("createdAt")),
            })
        rows.sort(key=lambda row: row.get("createdAt") or "", reverse=True)
        return {"insights": rows[:20]}

    @app.post("/v1/me/friends/insights")
    def create_friend_insight(request: FriendInsightRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        uid = str(user["uid"])
        text = " ".join(request.text.strip().split())
        lowered = text.lower()
        forbidden = ("private key", "api key", "secret", "wallet address", "wachtwoord", "password")
        if any(term in lowered for term in forbidden):
            raise HTTPException(422, "Plaats geen account-, wallet- of sleutelgegevens in een inzicht")
        db = firestore.client()
        ref = db.collection("friendsInsights").document()
        now = datetime.now(timezone.utc)
        ref.set({"friendId": _public_friend_id(uid), "text": text, "createdAt": now})
        return {"created": True, "id": ref.id, "text": text, "createdAt": now.isoformat()}

    @app.get("/v1/me/friends/{friend_id}")
    def friend_detail(friend_id: str, period: str = Query("30D"), user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
        selected = _period(period)
        traders = _all_friends(str(user["uid"]), selected)
        friend = _find(traders, friend_id)
        return {
            "period": selected,
            "trader": friend,
            "privacySafe": True,
            "absoluteValuesExposed": False,
            "referencePolicy": "Only normalized performance, settings metadata and risk metrics are shared.",
        }
