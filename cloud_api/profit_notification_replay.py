"""Deterministic, exchange-free notification policy replay.

Used in CI/QA only. It models notification selection/windowing and never imports
an exchange client or any execution primitive.
"""
from __future__ import annotations

from typing import Any

from profit_notifications import aggregate_profit_events, completed_window_for_event, qualifying_profit


def replay_profit_events(
    events: list[dict[str, Any]],
    *,
    mode: str = "SUMMARY",
    interval_minutes: int = 30,
    minimum_profit_usd: float = 0.50,
    now_ms: int,
) -> dict[str, Any]:
    seen: set[str] = set()
    qualifying: list[dict[str, Any]] = []
    duplicates = 0
    for event in sorted(events, key=lambda row: (int(row.get("occurredAtMs", 0)), str(row.get("eventId", "")))):
        event_id = str(event.get("eventId", ""))
        if event_id in seen:
            duplicates += 1
            continue
        seen.add(event_id)
        if not qualifying_profit(event.get("realizedNetPnlUsd"), minimum_profit_usd):
            continue
        qualifying.append(dict(event))

    if str(mode).upper() == "EVERY_WIN":
        return {
            "pushCount": len(qualifying),
            "duplicates": duplicates,
            "qualifyingCount": len(qualifying),
            "summaries": [],
        }

    windows: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for event in qualifying:
        start, end = completed_window_for_event(int(event.get("occurredAtMs", 0)), interval_minutes)
        if end > int(now_ms):
            continue
        windows.setdefault((start, end), []).append(event)

    summaries = []
    for (start, end), rows in sorted(windows.items()):
        summary = aggregate_profit_events(rows)
        summaries.append({
            "startMs": start,
            "endMs": end,
            "count": summary["count"],
            "totalProfitUsd": summary["totalProfitUsd"],
            "bestEventId": str((summary["best"] or {}).get("eventId", "")),
            "bestProfitUsd": float((summary["best"] or {}).get("realizedNetPnlUsd", 0.0)),
        })
    return {
        "pushCount": len(summaries),
        "duplicates": duplicates,
        "qualifyingCount": len(qualifying),
        "summaries": summaries,
    }


def replay_portfolio_tp(events: list[dict[str, Any]]) -> dict[str, Any]:
    seen_cycles: set[str] = set()
    pushes = []
    duplicates = 0
    for event in events:
        cycle_id = str(event.get("cycleId", "")).strip()
        if not cycle_id or cycle_id in seen_cycles:
            if cycle_id:
                duplicates += 1
            continue
        seen_cycles.add(cycle_id)
        pushes.append({
            "cycleId": cycle_id,
            "cycleProfitUsd": float(event.get("cycleEndEquity", 0.0)) - float(event.get("cycleStartEquity", 0.0)),
        })
    return {"pushCount": len(pushes), "duplicates": duplicates, "pushes": pushes}
