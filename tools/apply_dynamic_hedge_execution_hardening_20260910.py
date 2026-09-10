from pathlib import Path

PATH = Path("cloud_api/aster_dynamic_hedge_execution.py")
text = PATH.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"Expected Dynamic Hedge execution marker missing: {old[:180]!r}")
    text = text.replace(old, new, 1)


replace_once(
'''def _plan_profitable_reduction(client: Any, uid: str, positions: list[dict[str, Any]], side: str, reason: str) -> dict[str, Any] | None:\n''',
'''def _plan_profitable_reduction(client: Any, uid: str, positions: list[dict[str, Any]], side: str, reason: str, *, maximum_notional_usd: float | None = None) -> dict[str, Any] | None:\n''')
replace_once(
'''    for row in candidates:\n        try:\n            evidence = _close_evidence(client, uid, row, reason)\n''',
'''    for row in candidates:\n        row_notional=_notional(row)\n        if maximum_notional_usd is not None and row_notional > max(0.0, float(maximum_notional_usd)) * 1.001:\n            continue\n        try:\n            evidence = _close_evidence(client, uid, row, reason)\n''')
replace_once(
'''        if hedge_side:\n            action = _plan_profitable_reduction(client, uid, positions, hedge_side, "DYNAMIC_HEDGE_ABOVE_TARGET")\n        reason = "HEDGE_ABOVE_DYNAMIC_TARGET"\n''',
'''        if hedge_side:\n            dominant_value=max(long_value,short_value); hedge_value=min(long_value,short_value)\n            maximum_close=max(0.0,hedge_value-dominant_value*target[1]/100.0)\n            action = _plan_profitable_reduction(client, uid, positions, hedge_side, "DYNAMIC_HEDGE_ABOVE_TARGET", maximum_notional_usd=maximum_close)\n        reason = "HEDGE_ABOVE_DYNAMIC_TARGET"\n''')
replace_once(
'''    owner = str(stored.get("ownershipState", "ADOPTING")).upper()\n    if owner != "DYNAMIC_HEDGE_ACTIVE":\n        return {"handled": True, "ordersSent": 0, "status": "waiting", "action": "HOLD", "reason": f"ownership_{owner.lower()}"}\n    pending = _pending_result(control_ref, client, positions)\n    if pending is not None:\n        return {"handled": True, **pending}\n''',
'''    owner = str(stored.get("ownershipState", "ADOPTING")).upper()\n    # A previously submitted Dynamic Hedge intent is reconciled from exchange\n    # truth before ownership-state gating. This permits safe recovery from a\n    # 503/restart while still preventing any second POST.\n    pending = _pending_result(control_ref, client, positions)\n    if pending is not None:\n        return {"handled": True, **pending}\n    if owner != "DYNAMIC_HEDGE_ACTIVE":\n        return {"handled": True, "ordersSent": 0, "status": "waiting", "action": "HOLD", "reason": f"ownership_{owner.lower()}"}\n''')

PATH.write_text(text, encoding="utf-8")
print("Dynamic Hedge execution hardening installed")
