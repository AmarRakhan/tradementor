from pathlib import Path

ENGINE = Path('cloud_api/aster_strategy2_focus_trailing.py')
LEGACY_TEST = Path('cloud_api/test_aster_strategy2_focus_trailing.py')
text = ENGINE.read_text(encoding='utf-8')


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'expected exactly one match, got {count}: {old[:150]!r}')
    text = text.replace(old, new, 1)


# Simple mode is explicitly LONG-primary, regardless of stale/legacy slot direction.
replace_once(
'''    primary_side = str(existing_state.get("primarySide", "") or _slot_side(settings, symbol)).upper()\n    if primary_side not in {"LONG", "SHORT"}:\n        primary_side = "LONG"''',
'''    simple_requested = bool(getattr(settings, "focus_v2_simple_mode_enabled", False))\n    primary_side = "LONG" if simple_requested else str(existing_state.get("primarySide", "") or _slot_side(settings, symbol)).upper()\n    if primary_side not in {"LONG", "SHORT"}:\n        primary_side = "LONG"''')

# A DCA that filled while its hedge failed is repaired before ANY further DCA/TP/release work.
anchor = '''    # Primary-only OR initial start-hedge phase: DCA #1 moves on every fresh extreme.\n'''
pending = '''    # Hard invariant: a confirmed LONG DCA is not complete until SHORT equals total LONG.\n    # This recovery path runs before normal DCA/release/TP logic, so a second DCA\n    # cannot start while the hedge synchronization is pending.\n    if simple_flow and str(state.get("cycleStatus", "")) == "DCA_HEDGE_SYNC_PENDING":\n        target_qty = primary_qty\n        qty_tolerance = max(1e-12, target_qty * 0.001)\n        missing_qty = max(0.0, target_qty - hedge_qty)\n        if missing_qty <= qty_tolerance:\n            state.update({\n                "hedgeState": HEDGE_ACTIVE if hedge_qty > qty_tolerance else HEDGE_OFF,\n                "cycleStatus": "HEDGED" if hedge_qty > qty_tolerance else "LONG_ONLY",\n                "lastAction": "DCA_HEDGE_SYNC_CONFIRMED",\n                "lastReason": "pending DCA-hedge sync door actuele Aster-quantities bevestigd",\n                "hedgeTargetQty": target_qty,\n            })\n            _persist(ref, state, owned)\n            _audit(ref, "FOCUS_DCA_HEDGE_SYNC_CONFIRMED", cycleId=state.get("cycleId"), symbol=symbol, longQty=primary_qty, shortQty=hedge_qty)\n            return {"status": "executed", "action": "DCA_HEDGE_SYNC_CONFIRMED", "symbol": symbol, "ordersSent": 0}\n\n        if order_budget is not None and order_budget < 1:\n            reason = {"reason": "ORDER_BUDGET_HEDGE_SYNC", "requiredShortQty": missing_qty, "longQty": primary_qty, "shortQty": hedge_qty, "orderBudget": order_budget}\n            _audit(ref, "FOCUS_DCA_BLOCKED", cycleId=state.get("cycleId"), symbol=symbol, **reason)\n            return {"status": "budget-exhausted", "action": "DCA_HEDGE_SYNC_PENDING", "ordersSent": 0, **reason}\n\n        leverage = _resolved_leverage(client, settings, symbol, primary_row)\n        required_notional = missing_qty * mark\n        required_margin = required_notional / max(1, leverage)\n        available = _finite(account.get("availableBalance"))\n        equity = _finite(account.get("totalMarginBalance"), _finite(account.get("totalWalletBalance")))\n        maint = _finite(account.get("totalMaintMargin")) / equity if equity > 0 else 1.0\n        liq = _finite((primary_row or {}).get("liquidationPrice"))\n        liq_distance = abs(mark - liq) / mark if liq > 0 else 1.0\n        if required_margin > available or maint >= settings.emergency_margin_ratio or liq_distance < 0.05:\n            block_reason = "INSUFFICIENT_MARGIN" if required_margin > available else ("EMERGENCY_MARGIN_RATIO" if maint >= settings.emergency_margin_ratio else "LIQUIDATION_DISTANCE")\n            reason = {\n                "reason": block_reason, "requiredShortQty": missing_qty, "requiredMargin": required_margin,\n                "availableMargin": available, "maintenanceRatio": maint, "liquidationDistance": liq_distance,\n                "longQty": primary_qty, "shortQty": hedge_qty,\n            }\n            _audit(ref, "FOCUS_DCA_BLOCKED", cycleId=state.get("cycleId"), symbol=symbol, **reason)\n            return {"status": "waiting", "action": "DCA_HEDGE_SYNC_PENDING", "ordersSent": 0, **reason}\n\n        cycle_no = int(_finite(state.get("dcaCount")))\n        retry_prefix = _prefix(str(state.get("cycleId")), cycle_no, "DCA_HEDGE_SYNC_RETRY")\n        hq, hp, hcid, hoid = _execute_with_precision_retry(\n            client=client, symbol=symbol, mark=mark, notional=required_notional, leverage=leverage,\n            side=hedge_side, action="OPEN", prefix=retry_prefix, new_position_leverage=leverage,\n        )\n        owned = _upsert_owned(\n            owned, settings=settings, cycle_id=str(state.get("cycleId")), symbol=symbol, role=hedge_role,\n            side=hedge_side, quantity=hq, price=hp, client_id=hcid, order_id=hoid, dca=False, timestamp_ms=timestamp_ms,\n        )\n        estimated_short_after = hedge_qty + hq\n        remaining = max(0.0, target_qty - estimated_short_after)\n        if remaining > qty_tolerance:\n            state.update({\n                "hedgeState": HEDGE_ACTIVE, "cycleStatus": "DCA_HEDGE_SYNC_PENDING",\n                "lastAction": "DCA_HEDGE_SYNC_PENDING",\n                "lastReason": "SHORT sync gedeeltelijk gevuld; volgende realtime tick opnieuw proberen",\n                "hedgeTargetQty": target_qty,\n            })\n            _persist(ref, state, owned)\n            _audit(ref, "FOCUS_DCA_HEDGE_SYNC_PARTIAL", cycleId=state.get("cycleId"), symbol=symbol, fillQty=hq, remainingShortQty=remaining)\n            return {"status": "reconciling", "action": "DCA_HEDGE_SYNC_PENDING", "symbol": symbol, "ordersSent": 1, "requiredShortQty": remaining}\n\n        state.update({\n            "hedgeState": HEDGE_ACTIVE, "cycleStatus": "HEDGED",\n            "lastAction": "DCA_HEDGE_SYNCED",\n            "lastReason": "pending DCA-hedge sync voltooid; SHORT is weer gelijk aan totale LONG",\n            "hedgeTargetQty": target_qty, "lastHedgeEntryOrderId": hoid,\n        })\n        _persist(ref, state, owned)\n        _audit(ref, "FOCUS_DCA_HEDGE_SYNCED", cycleId=state.get("cycleId"), symbol=symbol, longQty=primary_qty, shortQty=estimated_short_after, orderId=hoid)\n        return {"status": "executed", "action": "DCA_HEDGE_SYNCED", "symbol": symbol, "ordersSent": 1}\n\n''' + anchor
replace_once(anchor, pending)

ENGINE.write_text(text, encoding='utf-8')

# Update the old source-contract assertion to the new explicit net-green action name.
legacy = LEGACY_TEST.read_text(encoding='utf-8')
old = '    assert "FOCUS_V2_HEDGE_RELEASED" in src\n'
new = '    assert "FOCUS_HEDGE_RELEASED_NET_GREEN" in src\n'
if legacy.count(old) != 1:
    raise SystemExit(f'legacy test assertion expected once, got {legacy.count(old)}')
LEGACY_TEST.write_text(legacy.replace(old, new, 1), encoding='utf-8')

print('Focus pending hedge-sync recovery patch applied')

# validation trigger 2026-08-30T06:02Z
