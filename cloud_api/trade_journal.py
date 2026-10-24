"""Trade journal (build 648): a complete, exchange-proven history of every closing order, for export to an agent.

Pure logic only: no Firestore, no FastAPI, no network. The extension (``trade_journal_extension``) supplies a store
and a read-only Aster client; this module never places, changes or cancels an order.

One journal record = one closing ORDER (all its fills together) on one position side. Every record carries:
- the exchange facts (fill ids, quantity, average exit price, realized PnL, commission, time);
- the position cycle it closed (opened at, average entry, entry quantity, DCA count, first entry order);
- who closed it, read from the order's own clientOrderId prefix (TP, Portfolio TP, Auto Hedge, Close Profits, ...);
- full or partial close (a hedge afbouw step is partial, the last step closes the leg);
- the bot context seen while the position was open (seat/zone role, spike entry, leverage) when it was captured;
- references to the settings versions active at open and at close.

Nothing is estimated: a value that is not known stays ``None`` and the export explains why.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol
from zoneinfo import ZoneInfo

JOURNAL_SCHEMA = "tradementor.trade-journal.v1"
EPSILON = 1e-9
FILL_PAGE_LIMIT = 1000
ORDER_PAGE_LIMIT = 1000
INCOME_PAGE_LIMIT = 1000
BACKFILL_DAYS = 180                      # Aster keeps fill history for about six months
MAX_CALLS_PER_SYNC = 12                  # Aster REST calls per sync step; the trading bot shares the same IP quota
PAIR_SNAPSHOT_WINDOW_MS = 30 * 60_000    # attach the Auto Hedge pair state only to closes seen within 30 minutes
CONTEXT_RETENTION_MS = 14 * 86_400_000   # keep an unseen open-position context this long for its later close
FUNDING_BACKFILL_DAYS = 30               # funding is history-heavy (every symbol, several times a day): 30 days back
INCOME_CHECK_INTERVAL_MS = 60_000        # discovery of new closes at most once a minute (income weighs heavy at Aster)
FUNDING_CHECK_INTERVAL_MS = 600_000      # funding after the backfill: at most every 10 minutes
ERROR_RETRY_MS = 3_600_000               # an unreadable symbol is retried at most once per hour
AMSTERDAM = ZoneInfo("Europe/Amsterdam")

# clientOrderId prefix -> (code, label for an opening order, label for a closing order). Longest prefix wins.
_PREFIXES: list[tuple[str, str, str, str]] = [
    ("mbb-ptp-", "PORTFOLIO_TP", "Portfolio take profit", "Portfolio take profit"),
    ("mbb-tp-", "TAKE_PROFIT", "Take profit", "Take profit (per pair)"),
    ("mbb-open-", "BOT_ENTRY", "Instap door de bot (prijszone/seat of Extreme Spike)", "Sluiting via instaporder"),
    ("mbb-dca-", "DCA", "DCA-bijkoop", "Sluiting via DCA-order"),
    ("mbb-sl-", "STOP_LOSS", "Stop loss", "Stop loss"),
    ("mbb-pll-exit-", "PROFIT_LOCK_EXIT", "Profit Lock Ladder", "Profit Lock Ladder (uitstap)"),
    ("mbb-pll-", "PROFIT_LOCK", "Profit Lock Ladder", "Profit Lock Ladder"),
    ("mbb-smart-rescue-", "SMART_RESCUE", "Smart Rescue DCA", "Smart Rescue"),
    ("mbb-asym-close-", "ASYM_HEDGE_CLOSE", "Asymmetrische hedge", "Asymmetrische hedge gesloten"),
    ("mbb-asym-", "ASYM_HEDGE", "Asymmetrische hedge geopend", "Asymmetrische hedge"),
    ("plah2-", "AUTO_HEDGE", "Auto Hedge geplaatst of terughedgen",
     "Auto Hedge: hedge afbouwen (SHORT Recovery-stap) of correctie naar 1:1"),
    ("tm-manual-", "APP_CLOSE", "Handmatige order in de app", "Close Profits of handmatige Close in de app"),
    ("tm-eh-", "EMERGENCY_HEDGE", "Portfolio noodhedge", "Portfolio noodhedge"),
    ("tmhr-", "HEDGE_RECOVERY", "Hedge Recovery (handmatig)", "Hedge Recovery (handmatig)"),
    ("lhs-", "LEGACY_HEDGE_SCALE", "Legacy Hedge Recovery", "Legacy Hedge Recovery"),
    ("dh-", "DYNAMIC_HEDGE", "Dynamische hedge", "Dynamische hedge"),
    ("mg-", "MONEY_GRABBER", "Money Grabber", "Money Grabber"),
    ("sn-", "SNIPER", "Sniper", "Sniper"),
    ("snc-", "SNIPER", "Sniper", "Sniper"),
    ("s3", "STRATEGY_3", "Strategy 3", "Strategy 3"),
    ("s2", "STRATEGY_2", "Strategy 2 (oude engine)", "Strategy 2 (oude engine)"),
    ("slot-", "STRATEGY_2", "Strategy 2 (oude engine)", "Strategy 2 (oude engine)"),
    ("focus-", "STRATEGY_2", "Strategy 2 Focus (oude engine)", "Strategy 2 Focus (oude engine)"),
    ("reopen-", "STRATEGY_2", "Strategy 2 heropening (oude engine)", "Strategy 2 (oude engine)"),
    ("autoclose-", "LIQUIDATION", "Liquidatie door Aster", "Liquidatie door Aster"),
    ("adl_autoclose", "ADL", "Auto-deleveraging door Aster", "Auto-deleveraging door Aster"),
    ("web_", "EXCHANGE_MANUAL", "Handmatig op Aster (web)", "Handmatig op Aster (web)"),
    ("ios_", "EXCHANGE_MANUAL", "Handmatig op Aster (app)", "Handmatig op Aster (app)"),
    ("android_", "EXCHANGE_MANUAL", "Handmatig op Aster (app)", "Handmatig op Aster (app)"),
    ("electron_", "EXCHANGE_MANUAL", "Handmatig op Aster (desktop)", "Handmatig op Aster (desktop)"),
]
_PREFIXES.sort(key=lambda item: len(item[0]), reverse=True)


def classify_order(client_order_id: str | None, *, closing: bool) -> dict[str, Any]:
    """Who placed this order, read from its own clientOrderId. Unknown stays explicitly unknown."""
    cid = str(client_order_id or "").strip()
    if not cid:
        return {"code": "ORDER_NOT_AVAILABLE", "label": "Order niet (meer) bekend bij Aster; bron onbekend", "proven": False}
    lowered = cid.lower()
    for prefix, code, open_label, close_label in _PREFIXES:
        if lowered.startswith(prefix):
            return {"code": code, "label": close_label if closing else open_label, "proven": True}
    return {"code": "OTHER", "label": "Onbekende bron (geen bekende bot-prefix)", "proven": False}


def _num(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result and abs(result) != float("inf") else 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def iso_utc(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def iso_local(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=AMSTERDAM).isoformat()


def normalize_fill(raw: dict[str, Any]) -> dict[str, Any] | None:
    """One Aster fill in a stable shape, or None when it cannot be used safely."""
    if not isinstance(raw, dict):
        return None
    fill_id = _int(raw.get("id", raw.get("tradeId")))
    symbol = str(raw.get("symbol", "")).upper().strip()
    side = str(raw.get("positionSide", "")).upper().strip()
    order_side = str(raw.get("side", "")).upper().strip()
    if not order_side and "buyer" in raw:
        order_side = "BUY" if bool(raw.get("buyer")) else "SELL"
    qty = abs(_num(raw.get("qty", raw.get("quantity"))))
    price = _num(raw.get("price"))
    time_ms = _int(raw.get("time", raw.get("updateTime")))
    if fill_id <= 0 or not symbol or side not in {"LONG", "SHORT"} or order_side not in {"BUY", "SELL"}:
        return None
    if qty <= 0 or price <= 0 or time_ms <= 0:
        return None
    quote = abs(_num(raw.get("quoteQty", raw.get("quoteQuantity")))) or qty * price
    return {
        "id": fill_id, "orderId": str(raw.get("orderId", raw.get("orderID", ""))).strip(),
        "symbol": symbol, "side": side, "orderSide": order_side, "qty": qty, "price": price, "quote": quote,
        "realizedPnl": _num(raw.get("realizedPnl", raw.get("realizedProfit"))),
        "commission": abs(_num(raw.get("commission"))),
        "commissionAsset": str(raw.get("commissionAsset", "")).upper(),
        "maker": bool(raw.get("maker")) if "maker" in raw else None, "time": time_ms,
        "increases": (side == "LONG" and order_side == "BUY") or (side == "SHORT" and order_side == "SELL"),
    }


def trim_partial_tail(fills: list[dict[str, Any]], page_limit: int = FILL_PAGE_LIMIT) -> tuple[list[dict[str, Any]], bool]:
    """A full page may cut an order in half. Drop the fills of its last order so the next page re-reads them whole.

    Returns (usable fills, page_was_complete). A page with fewer rows than the limit is the end of the history.
    """
    ordered = sorted(fills, key=lambda row: row["id"])
    if len(fills) < page_limit:
        return ordered, True
    if not ordered:
        return ordered, True
    last_order = ordered[-1]["orderId"]
    trimmed = [row for row in ordered if row["orderId"] != last_order or not last_order]
    if not trimmed:          # one order fills the entire page: keep it, nothing better is possible
        return ordered, False
    return trimmed, False


def _new_cycle(symbol: str, side: str, fill: dict[str, Any], order_cids: dict[str, str]) -> dict[str, Any]:
    cid = order_cids.get(fill["orderId"], "")
    return {
        "cycleKey": f"{symbol}|{side}|{fill['id']}", "openedAtMs": fill["time"], "exposure": 0.0,
        "entryQty": 0.0, "entryNotional": 0.0, "entryCommission": 0.0, "increaseCount": 0,
        "firstEntryOrderId": fill["orderId"], "firstEntryClientOrderId": cid or None,
        "entryReason": classify_order(cid, closing=False), "entryOrderIds": [],
        "closedQty": 0.0, "realizedPnl": 0.0, "closeCount": 0,
    }


def process_fills(
    symbol: str,
    fills: Iterable[dict[str, Any]],
    cycles: dict[str, Any],
    order_cids: dict[str, str],
    *,
    contexts: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Walk normalized fills (ascending id) through the position cycles of one symbol.

    ``cycles`` is the persisted open-cycle state per side ("LONG"/"SHORT"); a copy is returned updated.
    ``contexts`` maps side -> captured bot context of the cycle that was open (from the strategy state).
    """
    state: dict[str, Any] = {side: dict(value) for side, value in (cycles or {}).items() if isinstance(value, dict)}
    contexts = contexts or {}
    records: dict[tuple[str, str], dict[str, Any]] = {}
    for fill in sorted(fills, key=lambda row: row["id"]):
        side = fill["side"]
        cycle = state.get(side)
        if fill["increases"]:
            if cycle is None or _num(cycle.get("exposure")) <= EPSILON:
                cycle = _new_cycle(symbol, side, fill, order_cids)
                state[side] = cycle
            cycle["exposure"] = _num(cycle.get("exposure")) + fill["qty"]
            cycle["entryQty"] = _num(cycle.get("entryQty")) + fill["qty"]
            cycle["entryNotional"] = _num(cycle.get("entryNotional")) + fill["quote"]
            cycle["entryCommission"] = _num(cycle.get("entryCommission")) + fill["commission"]
            order_ids = list(cycle.get("entryOrderIds") or [])
            if fill["orderId"] and fill["orderId"] not in order_ids:
                order_ids.append(fill["orderId"])
                cycle["increaseCount"] = int(cycle.get("increaseCount", 0)) + 1
            cycle["entryOrderIds"] = order_ids[-60:]
            continue

        key = (side, fill["orderId"] or f"fill-{fill['id']}")
        record = records.get(key)
        if record is None:
            known_cycle = cycle is not None and _num(cycle.get("exposure")) > EPSILON
            cid = order_cids.get(fill["orderId"], "")
            record = _open_record(symbol, side, fill, cid, cycle if known_cycle else None,
                                  contexts.get(side) if known_cycle else None)
            records[key] = record
            if known_cycle:
                cycle["closeCount"] = int(cycle.get("closeCount", 0)) + 1
        _add_close_fill(record, fill)
        if cycle is not None and _num(cycle.get("exposure")) > EPSILON:
            applied = min(fill["qty"], _num(cycle.get("exposure")))
            cycle["exposure"] = max(0.0, _num(cycle.get("exposure")) - applied)
            cycle["closedQty"] = _num(cycle.get("closedQty")) + applied
            cycle["realizedPnl"] = _num(cycle.get("realizedPnl")) + fill["realizedPnl"]
            record["exposureAfter"] = cycle["exposure"]
            if cycle["exposure"] <= max(EPSILON, _num(cycle.get("entryQty")) * 1e-9):
                record["exposureAfter"] = 0.0
                record["fullClose"] = True
                state.pop(side, None)
    finished = [_finish_record(record) for record in records.values()]
    return sorted(finished, key=lambda row: (row["closedAtMs"], row["side"])), state


def _open_record(symbol: str, side: str, fill: dict[str, Any], cid: str, cycle: dict[str, Any] | None,
                 context: Any) -> dict[str, Any]:
    exposure_before = _num(cycle.get("exposure")) if cycle else None
    entry_qty = _num(cycle.get("entryQty")) if cycle else 0.0
    cycle_snapshot = None
    if cycle:
        cycle_snapshot = {
            "cycleKey": cycle.get("cycleKey"), "openedAtMs": _int(cycle.get("openedAtMs")),
            "entryQty": entry_qty, "entryNotionalUsd": _num(cycle.get("entryNotional")),
            "entryPriceAvg": (_num(cycle.get("entryNotional")) / entry_qty) if entry_qty > 0 else None,
            "entryCommissionUsd": _num(cycle.get("entryCommission")),
            "entryOrders": int(cycle.get("increaseCount", 0)),
            "dcaCount": max(0, int(cycle.get("increaseCount", 0)) - 1),
            "firstEntryOrderId": cycle.get("firstEntryOrderId"),
            "firstEntryClientOrderId": cycle.get("firstEntryClientOrderId"),
            "entryReason": cycle.get("entryReason") or classify_order(cycle.get("firstEntryClientOrderId"), closing=False),
            "closedQtyBefore": _num(cycle.get("closedQty")), "realizedPnlBeforeUsd": _num(cycle.get("realizedPnl")),
            "closesBefore": int(cycle.get("closeCount", 0)),
        }
    return {
        "symbol": symbol, "side": side, "closeOrderId": fill["orderId"] or None,
        "closeClientOrderId": cid or None, "closeReason": classify_order(cid, closing=True),
        "firstFillAtMs": fill["time"], "closedAtMs": fill["time"], "fillIds": [], "quantity": 0.0,
        "exitNotionalUsd": 0.0, "realizedPnlUsd": 0.0, "closeCommissionUsd": 0.0, "commissionAssets": [],
        "maker": None, "exposureBefore": exposure_before, "exposureAfter": None, "fullClose": False,
        "cycle": cycle_snapshot, "context": context if isinstance(context, dict) else None,
    }


def _add_close_fill(record: dict[str, Any], fill: dict[str, Any]) -> None:
    record["fillIds"].append(fill["id"])
    record["quantity"] += fill["qty"]
    record["exitNotionalUsd"] += fill["quote"]
    record["realizedPnlUsd"] += fill["realizedPnl"]
    record["closeCommissionUsd"] += fill["commission"]
    if fill["commissionAsset"] and fill["commissionAsset"] not in record["commissionAssets"]:
        record["commissionAssets"].append(fill["commissionAsset"])
    if fill["maker"] is not None:
        record["maker"] = fill["maker"] if record["maker"] is None else (record["maker"] and fill["maker"])
    record["closedAtMs"] = max(record["closedAtMs"], fill["time"])
    record["firstFillAtMs"] = min(record["firstFillAtMs"], fill["time"])


def _finish_record(record: dict[str, Any]) -> dict[str, Any]:
    qty = record["quantity"]
    record["exitPriceAvg"] = record["exitNotionalUsd"] / qty if qty > 0 else None
    record["id"] = hashlib.sha256(
        f"{record['symbol']}|{record['side']}|{record['closeOrderId'] or record['fillIds'][0]}".encode()
    ).hexdigest()[:32]
    cycle = record.get("cycle")
    before = record.get("exposureBefore")
    record["closedFraction"] = (min(1.0, qty / before) if before else None)
    record["closeType"] = "FULL" if record["fullClose"] else ("PARTIAL" if cycle else "UNKNOWN_CYCLE")
    if cycle and cycle.get("entryPriceAvg"):
        entry_avg = cycle["entryPriceAvg"]
        entry_value = entry_avg * qty
        share = min(1.0, qty / cycle["entryQty"]) if cycle.get("entryQty") else 0.0
        entry_fee_share = cycle["entryCommissionUsd"] * share
        record["entryValueClosedUsd"] = entry_value
        record["entryCommissionShareUsd"] = entry_fee_share
        record["netPnlAfterFeesUsd"] = record["realizedPnlUsd"] - record["closeCommissionUsd"] - entry_fee_share
        record["returnOnEntryValuePct"] = (record["realizedPnlUsd"] / entry_value * 100.0) if entry_value > 0 else None
        record["durationMs"] = max(0, record["closedAtMs"] - cycle["openedAtMs"])
        leverage = _num((record.get("context") or {}).get("leverage"))
        if leverage >= 1:
            record["marginUsd"] = entry_value / leverage
            record["returnOnMarginPct"] = record["realizedPnlUsd"] / record["marginUsd"] * 100.0 if record["marginUsd"] > 0 else None
        else:
            record["marginUsd"] = None
            record["returnOnMarginPct"] = None
    else:
        for field in ("entryValueClosedUsd", "entryCommissionShareUsd", "netPnlAfterFeesUsd", "returnOnEntryValuePct",
                      "durationMs", "marginUsd", "returnOnMarginPct"):
            record[field] = None
    for field in ("quantity", "exitNotionalUsd", "realizedPnlUsd", "closeCommissionUsd"):
        record[field] = round(record[field], 12)
    return record


# ---- bot context of open positions --------------------------------------------------------------------------

_CONTEXT_KEYS = {
    "cycleId", "cycleStartedAtMs", "leverage", "dcaCount", "soldierRole", "zoneMission", "zoneId", "zoneIndex",
    "zoneLow", "zoneHigh", "seatIndex", "seatZone", "entryMode", "entryReason", "entryPlan", "entrySizingMode",
    "entrySizingMultiplier", "entryMarginUsd", "entryNotionalUsd", "entryPortfolioEquity", "entryFilterMode",
    "spikeEntry", "spikeEventId", "spikePeakPct", "spikeHedgedAtMs", "spikeTakeProfit", "botManaged",
    "adoptedExisting", "manualOrExchangeReconciledAtMs", "lastKnownEntry",
}


def _jsonable(value: Any, depth: int = 0) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if depth > 3:
        return None
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v, depth + 1) for v in list(value)[:40]]
    return str(value)


def position_context(row: dict[str, Any]) -> dict[str, Any] | None:
    """The bot's own state of an open position, reduced to what explains the trade (no runtime bookkeeping)."""
    if not isinstance(row, dict):
        return None
    picked = {}
    for key, value in row.items():
        lowered = str(key).lower()
        if key in _CONTEXT_KEYS or lowered.startswith(("zone", "seat", "spike", "soldier")):
            picked[str(key)] = _jsonable(value)
    if not picked:
        return None
    encoded = json.dumps(picked, sort_keys=True, default=str)
    if len(encoded) > 6000:                       # never let one odd row blow up a document
        picked = {k: v for k, v in picked.items() if len(json.dumps(v, default=str)) < 600}
    return picked


def contexts_from_strategy(strategy_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Open-position contexts keyed "SYMBOL|SIDE" from the multi-BB position map."""
    rows = strategy_doc.get("multiBbPositions") if isinstance(strategy_doc, dict) else None
    result: dict[str, dict[str, Any]] = {}
    for key, row in (rows or {}).items() if isinstance(rows, dict) else []:
        if "|" not in str(key):
            continue
        symbol, side = str(key).rsplit("|", 1)
        side = side.upper()
        if side not in {"LONG", "SHORT"}:
            continue
        context = position_context(row)
        if context:
            result[f"{symbol.upper()}|{side}"] = context
    return result


def merge_contexts(stored: dict[str, Any], seen: dict[str, dict[str, Any]], now_ms: int) -> dict[str, Any]:
    """Keep the latest context per position; an unseen one stays for a while so its later close can use it."""
    merged: dict[str, Any] = {}
    for key, entry in (stored or {}).items():
        if isinstance(entry, dict) and now_ms - _int(entry.get("lastSeenMs")) <= CONTEXT_RETENTION_MS:
            merged[key] = entry
    for key, context in seen.items():
        previous = merged.get(key) if isinstance(merged.get(key), dict) else {}
        same_cycle = previous and (previous.get("context") or {}).get("cycleId") == context.get("cycleId")
        merged[key] = {
            "context": context,
            "firstSeenMs": _int(previous.get("firstSeenMs")) if same_cycle else now_ms,
            "lastSeenMs": now_ms,
        }
    return merged


def context_for_cycle(entry: Any, cycle: dict[str, Any] | None) -> dict[str, Any] | None:
    """Only use a stored context for the cycle it was seen in (seen after that cycle opened)."""
    if not isinstance(entry, dict) or not cycle:
        return None
    opened = _int(cycle.get("openedAtMs"))
    if _int(entry.get("lastSeenMs")) + 60_000 < opened:
        return None
    started = _int((entry.get("context") or {}).get("cycleStartedAtMs"))
    if started and opened and abs(started - opened) > 6 * 3_600_000 and started > opened:
        return None   # the bot's cycle started long after this exchange cycle: a different position
    return entry.get("context")


_PAIR_KEYS = (
    "status", "phase", "mode", "protectedSide", "hedgeSide", "pairCycleId", "triggerAt", "triggerPnl",
    "triggerThresholdUsd", "triggerReason", "currentHedgeQty", "currentProtectedQty", "rehedgeEnabled",
    "shortRecovery", "longRecovery", "stepsReached", "lastReason", "updatedAt", "closedAt",
)


def pair_snapshot(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, dict) or not row:
        return None
    picked = {key: _jsonable(row.get(key)) for key in _PAIR_KEYS if key in row}
    return picked or None


# ---- settings versions ------------------------------------------------------------------------------------------

_AUTO_HEDGE_KEYS = (
    "enabled", "thresholdUsd", "thresholdShortUsd", "thresholdLongUsd", "shortRecoveryPlan", "longRecoveryPlan",
    "rehedgeEnabled", "rehedgePercent", "workerEnabled", "mode",
)


def settings_snapshot(strategy_doc: dict[str, Any] | None, auto_hedge_doc: dict[str, Any] | None,
                      dynamic_hedge_doc: dict[str, Any] | None, controls_doc: dict[str, Any] | None) -> dict[str, Any]:
    strategy = (strategy_doc or {}).get("settings") if isinstance((strategy_doc or {}).get("settings"), dict) else {}
    auto = auto_hedge_doc or {}
    return {
        "strategy": _jsonable(strategy),
        "strategyConfigVersion": _int((strategy_doc or {}).get("configVersion")) or None,
        "autoHedge": {key: _jsonable(auto.get(key)) for key in _AUTO_HEDGE_KEYS if key in auto},
        "dynamicHedgeEnabled": (dynamic_hedge_doc or {}).get("enabled") if dynamic_hedge_doc else None,
        "profitSparen": _jsonable((controls_doc or {}).get("profitSweep")) if isinstance((controls_doc or {}).get("profitSweep"), dict) else None,
    }


def settings_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()[:24]


def build_settings_timeline(versions: list[dict[str, Any]], config_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge full snapshots (from build 648) with the older strategy-only configHistory into one ordered timeline."""
    timeline: list[dict[str, Any]] = []
    for row in versions or []:
        at = _int(row.get("effectiveFromMs"))
        if at and isinstance(row.get("settings"), dict):
            timeline.append({"id": str(row.get("id") or row.get("hash") or at), "effectiveFromMs": at,
                             "source": "volledige momentopname (build 648+)", "complete": True,
                             "settings": row["settings"]})
    for row in config_history or []:
        at = _int(row.get("timestampMs"))
        value = row.get("newValue")
        if at and isinstance(value, dict):
            timeline.append({"id": f"cfg-{at}-{_int(row.get('version'))}", "effectiveFromMs": at,
                             "source": f"strategie-instellingen (configHistory v{_int(row.get('version'))})",
                             "complete": False, "settings": {"strategy": _jsonable(value)}})
    timeline.sort(key=lambda row: (row["effectiveFromMs"], 0 if row["complete"] else 1))
    return timeline


def settings_at(timeline: list[dict[str, Any]], at_ms: int | None) -> dict[str, Any] | None:
    """The settings in force at a moment: strategy from the newest entry, the rest only from full snapshots."""
    if not at_ms:
        return None
    strategy_entry = None
    full_entry = None
    for entry in timeline:
        if entry["effectiveFromMs"] > at_ms:
            break
        if "strategy" in entry["settings"]:
            strategy_entry = entry
        if entry["complete"]:
            full_entry = entry
    if strategy_entry is None and full_entry is None:
        return None
    return {
        "strategyVersionId": strategy_entry["id"] if strategy_entry else None,
        "fullSnapshotId": full_entry["id"] if full_entry else None,
        "complete": bool(full_entry and (strategy_entry is None or strategy_entry is full_entry
                                         or strategy_entry["effectiveFromMs"] <= full_entry["effectiveFromMs"])),
    }


def key_settings(timeline: list[dict[str, Any]], ref: dict[str, Any] | None, side: str) -> dict[str, Any] | None:
    """The handful of values an agent asks about first, for the side of this trade."""
    if not ref:
        return None
    by_id = {entry["id"]: entry for entry in timeline}
    strategy = (by_id.get(ref.get("strategyVersionId")) or {}).get("settings", {}).get("strategy") or {}
    full = (by_id.get(ref.get("fullSnapshotId")) or {}).get("settings") or {}
    if ref.get("strategyVersionId") == ref.get("fullSnapshotId"):
        strategy = full.get("strategy") or strategy
    long_side = side == "LONG"
    auto = full.get("autoHedge") or {}
    return {
        "takeProfitMode": strategy.get("takeProfitMode"),
        "takeProfit": strategy.get("longTakeProfitValue" if long_side else "shortTakeProfitValue", strategy.get("takeProfit")),
        "portfolioTpPercent": strategy.get("portfolioTpPercent"),
        "leverage": strategy.get("leverage", strategy.get("minimumLeverage")),
        "entryMarginUsd": strategy.get("entryMarginLongUsd" if long_side else "entryMarginShortUsd"),
        "maxDca": strategy.get("maxDcaLong" if long_side else "maxDcaShort"),
        "dcaDistance": strategy.get("longDcaDistance" if long_side else "shortDcaDistance"),
        "entryFilterMode": strategy.get("entryFilterMode"),
        "priceZoneSeats": strategy.get("priceZoneSeats"),
        "autoHedgeEnabled": auto.get("enabled") if auto else None,
        "autoHedgeTriggerUsd": (auto.get("thresholdUsd") if long_side else auto.get("thresholdShortUsd")) if auto else None,
        "hedgeAfbouwPlan": (auto.get("shortRecoveryPlan") if long_side else auto.get("longRecoveryPlan")) if auto else None,
        "profitSparen": full.get("profitSparen"),
    }


# ---- funding ---------------------------------------------------------------------------------------------------

def funding_events(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """FUNDING_FEE income grouped symbol -> {timeMs: amount}. Aster does not say which hedge side paid."""
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, dict) or str(row.get("incomeType", "")).upper() != "FUNDING_FEE":
            continue
        symbol = str(row.get("symbol", "")).upper()
        at = _int(row.get("time"))
        if symbol and at:
            bucket = result.setdefault(symbol, {})
            bucket[str(at)] = round(bucket.get(str(at), 0.0) + _num(row.get("income")), 12)
    return result


def funding_in_window(events: dict[str, float] | None, start_ms: int | None, end_ms: int | None,
                      coverage_from_ms: int | None = None) -> float | None:
    """Funding on this symbol while the trade was open; None when the window starts before funding was recorded."""
    if not start_ms or not end_ms or not coverage_from_ms or start_ms < coverage_from_ms:
        return None
    if not events:
        return 0.0
    return round(sum(amount for at, amount in events.items() if start_ms <= _int(at) <= end_ms), 12)


# ---- sync ------------------------------------------------------------------------------------------------------

class JournalStore(Protocol):
    def control(self) -> dict[str, Any]: ...
    def save_control(self, patch: dict[str, Any]) -> None: ...
    def symbol_state(self, symbol: str) -> dict[str, Any]: ...
    def save_symbol_state(self, symbol: str, state: dict[str, Any]) -> None: ...
    def save_records(self, records: list[dict[str, Any]]) -> None: ...
    def strategy_doc(self) -> dict[str, Any]: ...
    def auto_hedge_doc(self) -> dict[str, Any]: ...
    def dynamic_hedge_doc(self) -> dict[str, Any]: ...
    def controls_doc(self) -> dict[str, Any]: ...
    def pair_doc(self, symbol: str) -> dict[str, Any]: ...
    def latest_settings_hash(self) -> str | None: ...
    def save_settings_version(self, version: dict[str, Any]) -> None: ...
    def stored_symbols(self) -> set[str]: ...
    def merge_funding(self, events: dict[str, dict[str, float]]) -> None: ...


def capture_settings(store: JournalStore, now_ms: int, *, reason: str) -> bool:
    """Write a new settings version when anything changed. Firestore only; never an Aster call."""
    snapshot = settings_snapshot(store.strategy_doc(), store.auto_hedge_doc(), store.dynamic_hedge_doc(),
                                 store.controls_doc())
    digest = settings_hash(snapshot)
    if digest == store.latest_settings_hash():
        return False
    store.save_settings_version({"id": f"{now_ms}-{digest[:10]}", "hash": digest, "effectiveFromMs": now_ms,
                                 "reason": reason, "settings": snapshot})
    return True


def sync_step(store: JournalStore, client: Any, *, now_ms: int, max_calls: int = MAX_CALLS_PER_SYNC) -> dict[str, Any]:
    """One bounded step: discover symbols, read new fills per symbol from its cursor, write journal records.

    Read-only towards Aster (income, allOrders, userTrades). Resumable: every cursor lives in the store.
    """
    calls = 0
    control = dict(store.control() or {})
    capture_settings(store, now_ms, reason="sync")
    strategy = store.strategy_doc()
    contexts = merge_contexts(control.get("contexts") or {}, contexts_from_strategy(strategy), now_ms)

    known = set(control.get("knownSymbols") or [])
    read_once = set(control.get("readSymbols") or [])
    dirty = set(control.get("dirtySymbols") or [])
    if not control.get("seeded"):
        known |= {s for s in store.stored_symbols() if s}
        dirty |= known
        control["seeded"] = True
    for key in contexts:
        known.add(key.split("|", 1)[0])

    floor_ms = now_ms - BACKFILL_DAYS * 86_400_000
    try:
        # 1) which symbols realized something since the last step
        cursor = max(_int(control.get("incomeCursorMs")) or floor_ms, floor_ms)
        income_due = now_ms - _int(control.get("incomeCheckedAtMs")) >= INCOME_CHECK_INTERVAL_MS
        for _ in range(3 if income_due else 0):
            if calls >= max_calls:
                break
            control["incomeCheckedAtMs"] = now_ms
            rows = client.income_history(income_type="REALIZED_PNL", start_time=cursor, limit=INCOME_PAGE_LIMIT)
            calls += 1
            newest = cursor
            for row in rows or []:
                symbol = str(row.get("symbol", "")).upper() if isinstance(row, dict) else ""
                if symbol:
                    known.add(symbol)
                    dirty.add(symbol)
                newest = max(newest, _int(row.get("time")) if isinstance(row, dict) else 0)
            if len(rows or []) < INCOME_PAGE_LIMIT:
                cursor = max(newest + 1, cursor)
                break
            if newest <= cursor:            # a full page within one millisecond: step past it
                cursor += 1
                break
            cursor = newest
        control["incomeCursorMs"] = cursor

        # 2) funding, so a trade can show what its symbol paid or received while it was open
        funding_floor = now_ms - FUNDING_BACKFILL_DAYS * 86_400_000
        if not _int(control.get("fundingCoverageFromMs")):
            control["fundingCoverageFromMs"] = funding_floor
        fcursor = max(_int(control.get("fundingCursorMs")) or funding_floor, _int(control.get("fundingCoverageFromMs")))
        funding_due = (not control.get("fundingBackfilled")
                       or now_ms - _int(control.get("fundingCheckedAtMs")) >= FUNDING_CHECK_INTERVAL_MS)
        if calls < max_calls and funding_due:
            control["fundingCheckedAtMs"] = now_ms
            rows = client.income_history(income_type="FUNDING_FEE", start_time=fcursor, limit=INCOME_PAGE_LIMIT)
            calls += 1
            grouped = funding_events(rows or [])
            if grouped:
                store.merge_funding(grouped)
            newest = max([_int(r.get("time")) for r in rows or [] if isinstance(r, dict)] or [fcursor])
            fcursor = newest + 1 if len(rows or []) < INCOME_PAGE_LIMIT else max(newest, fcursor + 1)
            control["fundingCursorMs"] = fcursor
            if len(rows or []) < INCOME_PAGE_LIMIT:
                control["fundingBackfilled"] = True

    except Exception as exc:  # noqa: BLE001
        if not _looks_rate_limited(str(exc)):
            raise
        control.update({"contexts": contexts, "lastSyncAtMs": now_ms, "knownSymbols": sorted(known),
                        "dirtySymbols": sorted(dirty), "readSymbols": sorted(read_once)})
        store.save_control(control)
        return {"complete": False, "backfillComplete": bool(control.get("backfillComplete")),
                "recordsWritten": 0, "asterCalls": calls, "rateLimited": True,
                "unreadableSymbols": [], "progress": {"symbolsRead": len(read_once & known), "symbolsTotal": len(known),
                "percent": round(100.0 * len(read_once & known) / (len(known) or 1), 1)}, "pendingSymbols": None}

    # 3) fills per symbol: new activity first, then the one-time backfill
    errors = {k: v for k, v in (control.get("symbolErrors") or {}).items() if isinstance(v, dict)}
    retry_after = {s for s, e in errors.items() if now_ms - _int(e.get("atMs")) < ERROR_RETRY_MS}
    queue = [s for s in sorted(dirty) + sorted(known - dirty - read_once) if s not in retry_after]
    written = 0
    pair_reads = 0
    rate_limited = False
    for symbol in queue:
        if calls + 2 > max_calls:
            break
        state = dict(store.symbol_state(symbol) or {})
        last_id = _int(state.get("lastTradeId"))
        try:
            orders = client.all_orders(symbol, limit=ORDER_PAGE_LIMIT)
            calls += 1
            raw = client.user_trades(symbol, from_id=(last_id + 1) if last_id else 0, limit=FILL_PAGE_LIMIT)
            calls += 1
        except Exception as exc:  # noqa: BLE001 - one unreadable symbol must not stop the journal
            calls += 1
            message = str(exc)[:240]
            if _looks_rate_limited(message):
                rate_limited = True
                break
            errors[symbol] = {"atMs": now_ms, "message": message}
            read_once.add(symbol)
            continue
        errors.pop(symbol, None)
        cids = {str(o.get("orderId")): str(o.get("clientOrderId") or o.get("origClientOrderId") or "")
                for o in orders or [] if isinstance(o, dict) and o.get("orderId") is not None}
        known_cids = dict(state.get("orderCids") or {})
        known_cids.update({k: v for k, v in cids.items() if v})
        fills = [f for f in (normalize_fill(r) for r in raw or []) if f and f["symbol"] == symbol]
        fills, complete = trim_partial_tail(fills, FILL_PAGE_LIMIT) if len(raw or []) >= FILL_PAGE_LIMIT else (sorted(fills, key=lambda r: r["id"]), True)
        cycles = dict(state.get("cycles") or {})
        side_contexts = {side: context_for_cycle(contexts.get(f"{symbol}|{side}"), cycles.get(side))
                         for side in ("LONG", "SHORT")}
        records, cycles = process_fills(symbol, fills, cycles, known_cids, contexts=side_contexts)
        if records and any(now_ms - r["closedAtMs"] <= PAIR_SNAPSHOT_WINDOW_MS for r in records) and pair_reads < 6:
            snapshot = pair_snapshot(store.pair_doc(symbol))
            pair_reads += 1
            for record in records:
                if now_ms - record["closedAtMs"] <= PAIR_SNAPSHOT_WINDOW_MS:
                    record["autoHedgePair"] = snapshot
        for record in records:
            record.setdefault("autoHedgePair", None)
            record["syncedAtMs"] = now_ms
        if records:
            store.save_records(records)
            written += len(records)
        # keep only the client ids of orders that may still produce fills (open cycles), bounded
        open_ids = {oid for cycle in cycles.values() for oid in (cycle.get("entryOrderIds") or [])}
        recent = dict(list(known_cids.items())[-400:])
        recent.update({k: v for k, v in known_cids.items() if k in open_ids})
        new_last = max([f["id"] for f in fills] or [last_id])
        store.save_symbol_state(symbol, {"lastTradeId": new_last, "cycles": cycles, "orderCids": recent,
                                         "syncedAtMs": now_ms, "complete": complete})
        read_once.add(symbol)
        if complete:
            dirty.discard(symbol)
        else:
            dirty.add(symbol)

    pending = sorted((dirty | (known - read_once)) - set(errors))
    backfilled = not (known - read_once) and bool(control.get("fundingBackfilled"))
    control.update({
        "knownSymbols": sorted(known), "readSymbols": sorted(read_once), "dirtySymbols": sorted(dirty),
        "contexts": contexts, "lastSyncAtMs": now_ms, "symbolErrors": errors,
        "backfillComplete": bool(control.get("backfillComplete")) or backfilled,
    })
    store.save_control(control)
    total = len(known) or 1
    return {
        "complete": control["backfillComplete"] and not pending, "backfillComplete": control["backfillComplete"], "recordsWritten": written, "asterCalls": calls,
        "rateLimited": rate_limited, "unreadableSymbols": sorted(errors),
        "progress": {"symbolsRead": len(read_once & known), "symbolsTotal": len(known),
                     "percent": round(100.0 * len(read_once & known) / total, 1) if known else 100.0},
        "pendingSymbols": len(pending),
    }


def _looks_rate_limited(message: str) -> bool:
    lowered = message.lower()
    return any(token in lowered for token in ("tijdelijk geblokkeerd", "429", "-1003", "banned until", "too many requests"))


# ---- export ----------------------------------------------------------------------------------------------------

FIELD_GUIDE = {
    "symbol / side": "Aster perpetual en de positiekant die gesloten werd (LONG of SHORT, hedge mode).",
    "closedAt / openedAt": "Tijd van de laatste fill van de sluitorder / van de eerste instapfill van deze positiecyclus. UTC (Z) en Amsterdam-tijd.",
    "closeReason": "Wie de order plaatste, afgeleid uit de eigen clientOrderId van de order bij Aster. 'proven=false' = niet vast te stellen.",
    "entryReason": "Wie de eerste instaporder van de cyclus plaatste (zelfde methode).",
    "closeType": "FULL = positiekant daarna 0; PARTIAL = deel gesloten (bv. een afbouwstap); UNKNOWN_CYCLE = opening niet in de beschikbare Aster-historie.",
    "quantity / exitPriceAvg / exitNotionalUsd": "Gesloten hoeveelheid, gemiddelde uitstapprijs en uitstapwaarde van deze order.",
    "entryPriceAvg / entryQty": "Gemiddelde instapprijs en totale instaphoeveelheid van de cyclus tot aan deze sluiting (incl. DCA).",
    "realizedPnlUsd": "Gerealiseerde PnL volgens Aster (zonder fees).",
    "closeCommissionUsd / entryCommissionShareUsd": "Fee van deze sluitorder / evenredig deel van de instapfees (exacte verdeling naar hoeveelheid).",
    "netPnlAfterFeesUsd": "realizedPnlUsd − closeCommissionUsd − entryCommissionShareUsd. Funding staat apart.",
    "fundingSymbolUsd": "Som van FUNDING_FEE op dit symbool tussen opening en sluiting. Aster splitst funding niet per hedge-kant: bij een hedge-pair is dit beide kanten samen. null = trade opende vóór coverage.fundingRecordedFrom.",
    "returnOnEntryValuePct / returnOnMarginPct": "PnL t.o.v. instapwaarde van het gesloten deel / t.o.v. marge (alleen als de hefboom van de positie bekend was).",
    "dcaCount": "Aantal extra instaporders na de eerste.",
    "context": "Wat de bot zelf over de open positie wist (seat/zone-rol, spike-instap, hefboom, cycleId). Alleen vastgelegd terwijl de app de historie bijwerkte; anders null.",
    "autoHedgePair": "Auto Hedge-pairstatus vlak na de sluiting (stappen afbouw, beschermde kant). Alleen als de sluiting binnen 30 min werd gezien.",
    "settingsAtOpen / settingsAtClose": "Verwijzing naar settingsVersions + de belangrijkste waarden. Vóór build 648 zijn alleen strategie-instellingen (configHistory) bekend; Auto Hedge/Profit Sparen daarvoor: niet vastgelegd.",
}


def build_export(records: list[dict[str, Any]], timeline: list[dict[str, Any]],
                 funding: dict[str, dict[str, float]], *, uid_hint: str, generated_ms: int,
                 sync_state: dict[str, Any], app_build: str) -> dict[str, Any]:
    trades = []
    for record in sorted(records, key=lambda r: _int(r.get("closedAtMs")), reverse=True):
        cycle = record.get("cycle") or {}
        opened = _int(cycle.get("openedAtMs")) or None
        open_ref = settings_at(timeline, opened)
        close_ref = settings_at(timeline, _int(record.get("closedAtMs")))
        trades.append({
            "id": record.get("id"), "symbol": record.get("symbol"), "side": record.get("side"),
            "openedAt": iso_utc(opened), "openedAtLocal": iso_local(opened),
            "closedAt": iso_utc(_int(record.get("closedAtMs"))), "closedAtLocal": iso_local(_int(record.get("closedAtMs"))),
            "durationMinutes": round(record["durationMs"] / 60000, 1) if record.get("durationMs") is not None else None,
            "closeType": record.get("closeType"), "closedFraction": record.get("closedFraction"),
            "closeReason": record.get("closeReason"), "entryReason": cycle.get("entryReason"),
            "quantity": record.get("quantity"), "entryPriceAvg": cycle.get("entryPriceAvg"),
            "exitPriceAvg": record.get("exitPriceAvg"), "entryQtyCycle": cycle.get("entryQty"),
            "exitNotionalUsd": record.get("exitNotionalUsd"), "entryValueClosedUsd": record.get("entryValueClosedUsd"),
            "marginUsd": record.get("marginUsd"), "realizedPnlUsd": record.get("realizedPnlUsd"),
            "closeCommissionUsd": record.get("closeCommissionUsd"),
            "entryCommissionShareUsd": record.get("entryCommissionShareUsd"),
            "netPnlAfterFeesUsd": record.get("netPnlAfterFeesUsd"),
            "fundingSymbolUsd": funding_in_window((funding or {}).get(str(record.get("symbol"))), opened,
                                                  _int(record.get("closedAtMs")),
                                                  _int(sync_state.get("fundingCoverageFromMs")) or None),
            "returnOnEntryValuePct": record.get("returnOnEntryValuePct"),
            "returnOnMarginPct": record.get("returnOnMarginPct"),
            "dcaCount": cycle.get("dcaCount"), "exposureBefore": record.get("exposureBefore"),
            "exposureAfter": record.get("exposureAfter"), "maker": record.get("maker"),
            "context": record.get("context"), "autoHedgePair": record.get("autoHedgePair"),
            "settingsAtOpen": {"ref": open_ref, "key": key_settings(timeline, open_ref, str(record.get("side")))},
            "settingsAtClose": {"ref": close_ref, "key": key_settings(timeline, close_ref, str(record.get("side")))},
            "exchange": {
                "closeOrderId": record.get("closeOrderId"), "closeClientOrderId": record.get("closeClientOrderId"),
                "fillIds": record.get("fillIds"), "commissionAssets": record.get("commissionAssets"),
                "firstEntryOrderId": cycle.get("firstEntryOrderId"),
                "firstEntryClientOrderId": cycle.get("firstEntryClientOrderId"),
                "cycleKey": cycle.get("cycleKey"),
            },
        })
    total = sum(_num(t["realizedPnlUsd"]) for t in trades)
    fees = sum(_num(t["closeCommissionUsd"]) + _num(t["entryCommissionShareUsd"]) for t in trades)
    full = [t for t in trades if t["closeType"] == "FULL"]
    by_reason: dict[str, dict[str, Any]] = {}
    for trade in trades:
        code = (trade["closeReason"] or {}).get("code", "ORDER_NOT_AVAILABLE")
        bucket = by_reason.setdefault(code, {"label": (trade["closeReason"] or {}).get("label"), "count": 0, "realizedPnlUsd": 0.0})
        bucket["count"] += 1
        bucket["realizedPnlUsd"] = round(bucket["realizedPnlUsd"] + _num(trade["realizedPnlUsd"]), 8)
    return {
        "schema": JOURNAL_SCHEMA,
        "generatedAt": iso_utc(generated_ms), "generatedAtLocal": iso_local(generated_ms),
        "app": {"name": "TradeMentor / Amar Crypto Bot", "build": app_build, "exchange": "Aster perpetuals (hedge mode)"},
        "account": {"uidSuffix": uid_hint[-6:] if uid_hint else None},
        "readMe": ("Elke regel in 'trades' is één sluitorder op één positiekant, bevestigd door Aster-fills. "
                   "Een gedeeltelijke sluiting (bv. hedge afbouwen) is een eigen regel met closeType PARTIAL. "
                   "Ontbrekende waarden zijn null en worden nooit geschat. Gebruik 'fieldGuide' voor de betekenis van velden."),
        "fieldGuide": FIELD_GUIDE,
        "coverage": {
            "historyComplete": bool(sync_state.get("backfillComplete")),
            "symbols": len(sync_state.get("knownSymbols") or []),
            "asterHistoryLimitDays": BACKFILL_DAYS,
            "contextCapturedSince": "build 648 (alleen terwijl de app de historie bijwerkte)",
            "fundingRecordedFrom": iso_utc(_int(sync_state.get("fundingCoverageFromMs")) or None),
            "fullSettingsSnapshotsSince": next((iso_utc(e["effectiveFromMs"]) for e in timeline if e["complete"]), None),
        },
        "summary": {
            "trades": len(trades), "fullCloses": len(full), "partialCloses": len(trades) - len(full),
            "realizedPnlUsd": round(total, 8), "feesUsd": round(fees, 8),
            "netAfterFeesUsd": round(sum(_num(t["netPnlAfterFeesUsd"]) for t in trades if t["netPnlAfterFeesUsd"] is not None), 8),
            "winningCloses": sum(1 for t in trades if _num(t["realizedPnlUsd"]) > 0),
            "losingCloses": sum(1 for t in trades if _num(t["realizedPnlUsd"]) < 0),
            "byCloseReason": by_reason,
            "firstClosedAt": trades[-1]["closedAt"] if trades else None, "lastClosedAt": trades[0]["closedAt"] if trades else None,
        },
        "settingsVersions": [{"id": e["id"], "effectiveFrom": iso_utc(e["effectiveFromMs"]),
                              "effectiveFromLocal": iso_local(e["effectiveFromMs"]), "source": e["source"],
                              "complete": e["complete"], "settings": e["settings"]} for e in timeline],
        "trades": trades,
    }


def list_row(record: dict[str, Any]) -> dict[str, Any]:
    """The light shape the Trade Historie card shows (same field names as the old closed-trades rows)."""
    cycle = record.get("cycle") or {}
    return {
        "id": record.get("id"), "symbol": record.get("symbol"), "side": record.get("side"),
        "closedAt": iso_utc(_int(record.get("closedAtMs"))), "openedAt": iso_utc(_int(cycle.get("openedAtMs")) or None),
        "realizedPnlUsd": record.get("realizedPnlUsd"), "marginUsd": record.get("marginUsd"),
        "exitPrice": record.get("exitPriceAvg"), "entryPrice": cycle.get("entryPriceAvg"),
        "closeType": record.get("closeType"), "closeReason": (record.get("closeReason") or {}).get("label"),
        "closeReasonCode": (record.get("closeReason") or {}).get("code"), "dcaCount": cycle.get("dcaCount"),
    }
