"""Immutable audit snapshot for manual Close Profits planning; no orders."""
from __future__ import annotations
import csv
import io
import json
from datetime import datetime, timezone


FIELDS = ("capturedAtUtc", "symbol", "side", "quantity", "markPrice", "unrealizedPnl", "hedgeLink", "percentage")


def make_profit_close_snapshot(rows, percentage, hedge_links=None, captured_at=None):
    if percentage not in (25, 50, 75, 100):
        raise ValueError("unsupported percentage")
    when = captured_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        raise ValueError("snapshot timestamp must include timezone")
    at = when.astimezone(timezone.utc).isoformat()
    links = hedge_links or {}
    entries = []
    for row in rows:
        symbol = str(row.get("symbol", "")).strip().upper()
        side = str(row.get("positionSide", row.get("side", ""))).strip().upper()
        if not symbol or side not in ("LONG", "SHORT"):
            continue
        entries.append({
            "capturedAtUtc": at, "symbol": symbol, "side": side,
            "quantity": str(row.get("positionAmt", row.get("quantity", ""))),
            "markPrice": str(row.get("markPrice", "")),
            "unrealizedPnl": str(row.get("unRealizedProfit", row.get("unrealizedPnl", ""))),
            "hedgeLink": "verified" if links.get(symbol) is True else "unverified",
            "percentage": percentage,
        })
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(entries)
    return {"capturedAtUtc": at, "rows": entries, "csv": buffer.getvalue(), "json": json.dumps(entries, separators=(",", ":"), ensure_ascii=False)}
