"""Fail-closed manual-close coordination for Aster Dynamic Hedge.

This module never submits orders. It locks Dynamic Hedge before a user-driven
close and only releases to ADOPTING after exchange truth proves that no
unintended side changed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import math


class ManualActionMismatch(RuntimeError):
    pass


def _n(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def position_quantities(rows: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    result: dict[tuple[str, str], float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper().strip()
        side = str(row.get("positionSide", row.get("side", ""))).upper().strip()
        qty = abs(_n(row.get("positionAmt", row.get("quantity"))))
        if symbol and side in {"LONG", "SHORT"} and qty > 0:
            result[(symbol, side)] = qty
    return result


def _serial(values: dict[tuple[str, str], float]) -> list[dict[str, Any]]:
    return [
        {"symbol": symbol, "side": side, "quantity": qty}
        for (symbol, side), qty in sorted(values.items())
    ]


def validate_manual_close_scope(
    before_rows: list[dict[str, Any]],
    after_rows: list[dict[str, Any]],
    scope: str,
    *,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    normalized = str(scope).upper().strip()
    if normalized not in {"LONG", "SHORT", "ALL"}:
        raise ValueError("Manual close scope moet LONG, SHORT of ALL zijn")
    before = position_quantities(before_rows)
    after = position_quantities(after_rows)
    changed: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        b = before.get(key, 0.0)
        a = after.get(key, 0.0)
        allowed = normalized == "ALL" or key[1] == normalized
        eps = max(tolerance, b * 1e-9, a * 1e-9)
        if not allowed and abs(a - b) > eps:
            raise ManualActionMismatch(
                f"Onbedoelde {key[1]}-wijziging op {key[0]}: {b:.12g} -> {a:.12g}"
            )
        if allowed and a > b + eps:
            raise ManualActionMismatch(
                f"Manual close heeft {key[1]}-exposure verhoogd op {key[0]}: {b:.12g} -> {a:.12g}"
            )
        if abs(a - b) > eps:
            changed.append({"symbol": key[0], "side": key[1], "before": b, "after": a})
    return {
        "scope": normalized,
        "before": _serial(before),
        "after": _serial(after),
        "changed": changed,
        "validated": True,
    }


@dataclass
class ManualActionGuard:
    active: bool
    scope: str
    before_rows: list[dict[str, Any]]


def begin_manual_action(control_ref: Any, scope: str, before_rows: list[dict[str, Any]]) -> ManualActionGuard:
    stored = control_ref.get().to_dict() or {}
    normalized = str(scope).upper().strip()
    if not bool(stored.get("enabled", False)):
        return ManualActionGuard(False, normalized, list(before_rows))
    now = datetime.now(timezone.utc)
    control_ref.set({
        "ownershipState": "MANUAL_ACTION_LOCK",
        "manualAction": {
            "scope": normalized,
            "status": "LOCKED",
            "before": _serial(position_quantities(before_rows)),
            "startedAt": now,
        },
        "lastAction": "MANUAL_ACTION_LOCK",
        "lastActionAt": now,
        "lastReason": f"Handmatige {normalized}-sluiting actief; Dynamic Hedge is gepauzeerd tot exchange-reconciliatie",
        "updatedAt": now,
    }, merge=True)
    return ManualActionGuard(True, normalized, list(before_rows))


def complete_manual_action(control_ref: Any, guard: ManualActionGuard | None, after_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if guard is None or not guard.active:
        return None
    now = datetime.now(timezone.utc)
    try:
        proof = validate_manual_close_scope(guard.before_rows, after_rows, guard.scope)
    except Exception as exc:
        control_ref.set({
            "ownershipState": "MANUAL_ACTION_LOCK",
            "manualAction": {"scope": guard.scope, "status": "MISMATCH", "failedAt": now, "reason": str(exc)[:500]},
            "lastAction": "MANUAL_CLOSE_MISMATCH",
            "lastActionAt": now,
            "lastReason": str(exc)[:500],
            "updatedAt": now,
        }, merge=True)
        raise
    control_ref.set({
        "ownershipState": "ADOPTING",
        "stableReads": 0,
        "positionFingerprint": "",
        "manualAction": {"scope": guard.scope, "status": "EXCHANGE_CONFIRMED", "proof": proof, "completedAt": now},
        "lastAction": "MANUAL_CLOSE_CONFIRMED",
        "lastActionAt": now,
        "lastReason": "Handmatige sluiting side-safe bevestigd; Dynamic Hedge adopteert eerst de nieuwe exchange-state",
        "updatedAt": now,
    }, merge=True)
    return proof


def fail_manual_action(control_ref: Any, guard: ManualActionGuard | None, reason: str) -> None:
    if guard is None or not guard.active:
        return
    now = datetime.now(timezone.utc)
    control_ref.set({
        "ownershipState": "MANUAL_ACTION_LOCK",
        "manualAction": {"scope": guard.scope, "status": "UNCERTAIN", "failedAt": now, "reason": str(reason)[:500]},
        "lastAction": "MANUAL_CLOSE_UNCERTAIN",
        "lastActionAt": now,
        "lastReason": str(reason)[:500],
        "updatedAt": now,
    }, merge=True)
