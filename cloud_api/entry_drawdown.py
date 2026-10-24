"""Build 652/655: gemiddelde max drawdown vanaf instap, per kant (LONG en SHORT). Alleen lezen.

Per afgeronde trade (een cyclus van instap tot volledig gesloten) is de max drawdown hoe ver de koers ná de
instap maximaal tegen de positie in is gelopen, in prijs-% vanaf de gemiddelde instapprijs (zonder hefboom):
- LONG:  (instap - laagste low)  / instap * 100
- SHORT: (hoogste high - instap) / instap * 100
Build 655 (Amar 24-10): alleen gesloten trades. Elke trade krijgt één keer, na het sluiten, zijn definitieve max
drawdown; die verandert daarna nooit meer. Open posities tellen niet mee (een net geopende positie heeft ~0% en
trok het getal mee met de markt). Per kant de mediaan (in de app: gemiddeld) over WINDOW_DAYS, plus dezelfde maat
over de laatste RECENT_DAYS om te zien of een nieuwe strategie minder diep gaat.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

WINDOW_DAYS = 90
RECENT_DAYS = 7
KLINE_LIMIT = 1000
INTERVALS: tuple[tuple[str, int], ...] = (
    ("1m", 60_000), ("5m", 300_000), ("15m", 900_000), ("1h", 3_600_000), ("4h", 14_400_000), ("1d", 86_400_000),
)
GROUP_MAX_SPAN_MS = (KLINE_LIMIT - 2) * 900_000      # posities op één munt delen een lezing tot ~10 dagen (15m)
STALE_OPEN_TRACKER_MS = 2 * 86_400_000               # een open tracker die 2 dagen niet meer gezien is vervalt
MAX_TRACKERS = 4000
MAX_FETCH_ERRORS = 3

Candle = tuple[int, float, float]                     # (open time ms, high, low)
FetchFn = Callable[[str, str, int, int], list[Candle]]


def _f(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number and abs(number) != float("inf") else 0.0


def _i(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def pick_interval(span_ms: int) -> tuple[str, int]:
    """Fijnste interval waarbij de hele periode in één lezing van KLINE_LIMIT candles past."""
    for name, size in INTERVALS:
        if span_ms <= (KLINE_LIMIT - 2) * size:
            return name, size
    return INTERVALS[-1]


def drawdown_pct(side: str, entry: float, worst: float | None) -> float | None:
    if entry <= 0 or worst is None or worst <= 0:
        return None
    if side == "LONG":
        return max(0.0, (entry - worst) / entry * 100.0)
    return max(0.0, (worst - entry) / entry * 100.0)


def median(values: Iterable[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0


# ---- welke posities --------------------------------------------------------------------------------------------

def closed_cycles(records: Iterable[dict[str, Any]], cutoff_ms: int) -> dict[str, dict[str, Any]]:
    """Volledig gesloten cycli uit het tradejournaal, gesloten op of na cutoff_ms."""
    by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        cycle = record.get("cycle") if isinstance(record, dict) else None
        if not isinstance(cycle, dict):
            continue
        key = str(cycle.get("cycleKey") or "")
        side = str(record.get("side") or "").upper()
        opened = _i(cycle.get("openedAtMs"))
        entry = _f(cycle.get("entryPriceAvg"))
        closed_at = _i(record.get("closedAtMs"))
        if not key or side not in {"LONG", "SHORT"} or opened <= 0 or entry <= 0 or closed_at <= 0:
            continue
        row = by_key.setdefault(key, {"key": key, "symbol": str(record.get("symbol") or "").upper(), "side": side,
                                      "openedAtMs": opened, "entry": entry, "endMs": 0, "full": False, "lastClose": 0})
        if closed_at >= row["lastClose"]:
            row["lastClose"] = closed_at
            row["entry"] = entry                      # de laatste sluiting kent alle instappen (DCA) van de cyclus
        row["endMs"] = max(row["endMs"], closed_at)
        row["full"] = row["full"] or bool(record.get("fullClose"))
    result = {}
    for key, row in by_key.items():
        if row["full"] and row["endMs"] >= cutoff_ms and row["symbol"]:
            result[key] = {k: row[k] for k in ("key", "symbol", "side", "openedAtMs", "entry", "endMs")}
    return result


# ---- candles lezen en bijhouden ----------------------------------------------------------------------------------

def _plan_groups(due: list[dict[str, Any]], now_ms: int) -> list[dict[str, Any]]:
    """Posities per munt samen lezen zolang de periode klein genoeg blijft voor een fijn interval."""
    groups: list[dict[str, Any]] = []
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for item in due:
        by_symbol.setdefault(item["symbol"], []).append(item)
    for symbol, items in sorted(by_symbol.items()):
        items.sort(key=lambda x: x["from"])
        current: dict[str, Any] | None = None
        for item in items:
            if current and max(current["to"], item["to"]) - current["from"] <= GROUP_MAX_SPAN_MS:
                current["to"] = max(current["to"], item["to"])
                current["items"].append(item)
                continue
            current = {"symbol": symbol, "from": item["from"], "to": item["to"], "items": [item]}
            groups.append(current)
    # open posities eerst (die veranderen), daarna de oudste gesloten
    groups.sort(key=lambda g: (0 if any(i["open"] for i in g["items"]) else 1, g["from"]))
    return groups


def update_trackers(trackers: dict[str, dict[str, Any]], cycles: dict[str, dict[str, Any]], fetch: FetchFn, *,
                    now_ms: int, max_calls: int, min_refresh_ms: int = 60_000) -> dict[str, Any]:
    """Werk de trackers bij met hoogstens max_calls candle-lezingen. Muteert trackers; geeft een verslag terug."""
    for key, cycle in cycles.items():
        tracker = trackers.get(key)
        if not isinstance(tracker, dict) or tracker.get("side") != cycle["side"]:
            tracker = {"symbol": cycle["symbol"], "side": cycle["side"], "openedAtMs": cycle["openedAtMs"],
                       "worst": None, "coveredUntilMs": 0}
            trackers[key] = tracker
        tracker["entry"] = cycle["entry"]
        tracker["endMs"] = cycle["endMs"]
        tracker["seenAtMs"] = now_ms

    due: list[dict[str, Any]] = []
    for key, cycle in cycles.items():
        tracker = trackers[key]
        target = cycle["endMs"] if cycle["endMs"] else now_ms
        covered = _i(tracker.get("coveredUntilMs"))
        if covered >= target or (cycle["endMs"] is None and covered and target - covered < min_refresh_ms):
            continue
        start = max(cycle["openedAtMs"], covered) if covered else cycle["openedAtMs"]
        due.append({"key": key, "symbol": cycle["symbol"], "from": start, "to": target, "open": cycle["endMs"] is None})

    calls = 0
    errors = 0
    for group in _plan_groups(due, now_ms):
        if calls >= max_calls:
            break
        interval, size = pick_interval(group["to"] - group["from"])
        start = group["from"] - group["from"] % size
        calls += 1
        try:
            candles = fetch(group["symbol"], interval, start, group["to"])
        except Exception:  # noqa: BLE001 - één onleesbare munt stopt de rest niet
            errors += 1
            for item in group["items"]:     # na MAX_FETCH_ERRORS keer: overslaan, zodat het getal ooit af is
                tracker = trackers[item["key"]]
                tracker["fetchErrors"] = _i(tracker.get("fetchErrors")) + 1
                if not item["open"] and tracker["fetchErrors"] >= MAX_FETCH_ERRORS:
                    tracker["coveredUntilMs"] = item["to"]
                    tracker["noData"] = True
            continue
        for item in group["items"]:
            tracker = trackers[item["key"]]
            relevant = [c for c in candles if c[0] + size > item["from"] and c[0] <= item["to"]]
            if not relevant:
                if not item["open"] and tracker.get("worst") is None:
                    tracker["coveredUntilMs"] = item["to"]      # Aster heeft geen candles (bv. delisted): overslaan
                    tracker["noData"] = True
                continue
            if tracker["side"] == "LONG":
                worst = min(c[2] for c in relevant if c[2] > 0)
                old = tracker.get("worst")
                tracker["worst"] = worst if old is None else min(_f(old), worst)
            else:
                worst = max(c[1] for c in relevant)
                old = tracker.get("worst")
                tracker["worst"] = worst if old is None else max(_f(old), worst)
            last_close = max(c[0] for c in relevant) + size
            tracker["coveredUntilMs"] = min(item["to"], last_close) if not item["open"] else min(now_ms, last_close)
            if not item["open"] and last_close >= item["to"]:
                tracker["coveredUntilMs"] = item["to"]
    return {"calls": calls, "errors": errors, "due": len(due)}


def prune_trackers(trackers: dict[str, dict[str, Any]], active_keys: set[str], *, now_ms: int, cutoff_ms: int) -> None:
    for key in list(trackers):
        tracker = trackers[key]
        if key in active_keys:
            continue
        end = _i(tracker.get("endMs"))
        if end and end >= cutoff_ms:
            continue                                   # gesloten binnen het venster: bewaren, ook als het journaal hapert
        if not end and now_ms - _i(tracker.get("seenAtMs")) <= STALE_OPEN_TRACKER_MS:
            continue
        trackers.pop(key, None)
    if len(trackers) > MAX_TRACKERS:
        for key, _ in sorted(trackers.items(), key=lambda kv: _i(kv[1].get("seenAtMs")))[: len(trackers) - MAX_TRACKERS]:
            trackers.pop(key, None)


def summarize(trackers: dict[str, dict[str, Any]], active_keys: set[str], *, now_ms: int,
              recent_days: int = RECENT_DAYS) -> dict[str, Any]:
    """Mediaan max drawdown per kant over de afgeronde trades; ook over alleen de laatste recent_days."""
    recent_from = now_ms - recent_days * 86_400_000
    out: dict[str, Any] = {}
    for side in ("LONG", "SHORT"):
        values: list[float] = []
        recent: list[float] = []
        pending = 0
        for key in active_keys:
            tracker = trackers.get(key) or {}
            if tracker.get("side") != side or not tracker.get("endMs"):
                continue
            if _i(tracker.get("coveredUntilMs")) < _i(tracker.get("endMs")):
                pending += 1
                continue
            dd = drawdown_pct(side, _f(tracker.get("entry")), _f(tracker.get("worst")) or None)
            if dd is None:
                continue
            values.append(dd)
            if _i(tracker.get("endMs")) >= recent_from:
                recent.append(dd)
        value, recent_value = median(values), median(recent)
        out[side.lower()] = {
            "avgMaxDrawdownPct": round(value, 2) if value is not None else None, "count": len(values),
            "recentAvgMaxDrawdownPct": round(recent_value, 2) if recent_value is not None else None,
            "recentCount": len(recent), "pending": pending,
        }
    out["windowDays"] = WINDOW_DAYS
    out["recentDays"] = recent_days
    out["complete"] = out["long"]["pending"] == 0 and out["short"]["pending"] == 0
    return out


def parse_klines(payload: Any) -> list[Candle]:
    rows: list[Candle] = []
    for item in payload if isinstance(payload, list) else []:
        if isinstance(item, (list, tuple)) and len(item) >= 4:
            high, low = _f(item[2]), _f(item[3])
            if high > 0 and low > 0:
                rows.append((_i(item[0]), high, low))
    return rows
