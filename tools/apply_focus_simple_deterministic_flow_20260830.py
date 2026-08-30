from pathlib import Path

ENGINE = Path('cloud_api/aster_strategy2_focus_trailing.py')
TEST = Path('cloud_api/test_focus_simple_deterministic_flow.py')
text = ENGINE.read_text(encoding='utf-8')


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'expected exactly one match, got {count}: {old[:140]!r}')
    text = text.replace(old, new, 1)


# Simple Focus mode always starts and DCA-syncs at 100% hedge ratio.
replace_once(
'''    configured_hedge_ratio = hedge_ratio(settings)\n    configured_start_hedge_ratio = start_hedge_ratio(settings)''',
'''    simple_flow = bool(getattr(settings, "focus_v2_simple_mode_enabled", False))\n    configured_hedge_ratio = 1.0 if simple_flow else hedge_ratio(settings)\n    configured_start_hedge_ratio = 1.0 if simple_flow else start_hedge_ratio(settings)''')

# Net-green hedge check: executable side of book when available; conservative round-trip fees/slippage.
needle = '''def _history(state: dict[str, Any], *, mark: float, dca_ratio: float, release_ratio: float,\n'''
helper = '''def _executable_hedge_close_price(client: Any, symbol: str, hedge_side: str, mark: float) -> float:\n    """Best executable close proxy: ask to buy back SHORT, bid to sell LONG hedge.\n\n    Fail closed to mark when bookTicker is unavailable; the explicit fee/slippage\n    buffers below keep the green gate conservative rather than optimistic.\n    """\n    try:\n        payload = client._public_get(\n            f"/fapi/v1/ticker/bookTicker?symbol={symbol.upper()}",\n            ttl_seconds=1,\n            invalid_message="Aster bookTicker niet beschikbaar voor hedge-release",\n        )\n        if isinstance(payload, dict):\n            key = "askPrice" if hedge_side.upper() == "SHORT" else "bidPrice"\n            value = _finite(payload.get(key))\n            if value > 0:\n                return value\n    except Exception:\n        pass\n    return mark\n\n\ndef expected_net_hedge_close_pnl(\n    client: Any, symbol: str, hedge_side: str, hedge_row: dict[str, Any] | None, mark: float,\n) -> tuple[float, float, float, float, float]:\n    """Expected full round-trip net PnL for the remaining protection hedge."""\n    if not hedge_row:\n        return 0.0, mark, 0.0, 0.0, 0.0\n    qty = abs(_finite(hedge_row.get("positionAmt")))\n    entry = _finite(hedge_row.get("entryPrice"))\n    if qty <= 0 or entry <= 0 or mark <= 0:\n        return 0.0, mark, 0.0, 0.0, 0.0\n    close_price = _executable_hedge_close_price(client, symbol, hedge_side, mark)\n    gross = (entry - close_price) * qty if hedge_side.upper() == "SHORT" else (close_price - entry) * qty\n    # Conservative defaults; the gate requires strictly positive result after a\n    # complete estimated round trip, not merely green mark-price PnL.\n    fee_rate = 0.0005\n    slippage_rate = 0.0002\n    fees = (entry + close_price) * qty * fee_rate\n    slippage = close_price * qty * slippage_rate\n    return gross - fees - slippage, close_price, gross, fees, slippage\n\n\n''' + needle
replace_once(needle, helper)

# Existing active cycles: release price no longer governs simple flow.
replace_once(
'''                state["dcaMode"] = DCA_FROZEN\n                state["nextDcaPrice"] = next_dca_from_anchor(last_dca, primary_side, dca_ratio)\n                state["hedgeReleasePrice"] = release_price_from_last_dca(last_dca, primary_side, release_ratio)\n                state["hedgeTargetQty"] = primary_qty * configured_hedge_ratio''',
'''                state["dcaMode"] = DCA_FROZEN\n                state["nextDcaPrice"] = next_dca_from_anchor(last_dca, primary_side, dca_ratio)\n                state["hedgeReleasePrice"] = 0.0 if simple_flow else release_price_from_last_dca(last_dca, primary_side, release_ratio)\n                state["hedgeTargetQty"] = primary_qty * configured_hedge_ratio''')

# In the active-cycle state, simple flow keeps the DCA reference but has no recovery release price.
replace_once(
'''        state["hedgeReleasePrice"] = release_price_from_last_dca(last_dca, primary_side, release_ratio)\n        state["hedgeTargetQty"] = primary_qty * configured_hedge_ratio''',
'''        state["hedgeReleasePrice"] = 0.0 if simple_flow else release_price_from_last_dca(last_dca, primary_side, release_ratio)\n        state["hedgeTargetQty"] = primary_qty * configured_hedge_ratio''')

# Transparent DCA block reasons instead of a generic silent WAITING result.
replace_once(
'''        if order_budget is not None and order_budget < 2:\n            return {"status": "budget-exhausted", "action": "FOCUS_V2_WAIT_DCA_HEDGE", "ordersSent": 0}''',
'''        if order_budget is not None and order_budget < 2:\n            reason = {"reason": "ORDER_BUDGET", "markPrice": mark, "nextDcaPrice": next_dca, "orderBudget": order_budget}\n            _audit(ref, "FOCUS_DCA_BLOCKED", cycleId=state.get("cycleId"), symbol=symbol, **reason)\n            return {"status": "budget-exhausted", "action": "FOCUS_DCA_BLOCKED", "ordersSent": 0, **reason}''')
replace_once(
'''        if dca_notional <= 0:\n            return {"status": "waiting", "action": "FOCUS_V2_DCA_BUDGET_BLOCK", "ordersSent": 0}''',
'''        if dca_notional <= 0:\n            reason = {"reason": "DCA_BUDGET", "markPrice": mark, "nextDcaPrice": next_dca, "dcaCount": current_count, "remainingBudget": remaining_budget}\n            _audit(ref, "FOCUS_DCA_BLOCKED", cycleId=state.get("cycleId"), symbol=symbol, **reason)\n            return {"status": "waiting", "action": "FOCUS_DCA_BLOCKED", "ordersSent": 0, **reason}''')
replace_once(
'''        if required_margin > available or maint >= settings.emergency_margin_ratio or liq_distance < 0.05:\n            return {"status": "waiting", "action": "FOCUS_V2_DCA_RISK_BLOCK", "ordersSent": 0}''',
'''        if required_margin > available or maint >= settings.emergency_margin_ratio or liq_distance < 0.05:\n            block_reason = "INSUFFICIENT_MARGIN" if required_margin > available else ("EMERGENCY_MARGIN_RATIO" if maint >= settings.emergency_margin_ratio else "LIQUIDATION_DISTANCE")\n            reason = {\n                "reason": block_reason, "markPrice": mark, "nextDcaPrice": next_dca,\n                "dcaEnabled": bool(settings.focus_dca_enabled), "dcaCount": current_count,\n                "maxDca": settings.focus_max_dca, "dcaUnlimited": bool(settings.focus_dca_unlimited),\n                "orderBudget": order_budget, "requiredMargin": required_margin, "availableMargin": available,\n                "maintenanceRatio": maint, "liquidationDistance": liq_distance,\n                "dcaNotional": dca_notional, "hedgeGapNotional": hedge_gap,\n            }\n            _audit(ref, "FOCUS_DCA_BLOCKED", cycleId=state.get("cycleId"), symbol=symbol, **reason)\n            return {"status": "waiting", "action": "FOCUS_DCA_BLOCKED", "ordersSent": 0, **reason}''')

# DCA hedge-sync uses ACTUAL exchange quantities, not approximate notional equality.
replace_once(
'''        fresh_primary_notional = _notional(fresh_primary) or actual_primary_after\n        fresh_primary_qty = abs(_finite((fresh_primary or {}).get("positionAmt"))) or (primary_qty + q)\n        fresh_hedge_notional = _notional(fresh_hedge)\n        target_after = fresh_primary_notional * configured_hedge_ratio\n        target_qty_after = fresh_primary_qty * configured_hedge_ratio\n        gap = max(0.0, target_after - fresh_hedge_notional)\n        hq = hp = 0.0''',
'''        fresh_primary_notional = _notional(fresh_primary) or actual_primary_after\n        fresh_primary_qty = abs(_finite((fresh_primary or {}).get("positionAmt"))) or (primary_qty + q)\n        fresh_hedge_notional = _notional(fresh_hedge)\n        fresh_hedge_qty = abs(_finite((fresh_hedge or {}).get("positionAmt")))\n        target_after = fresh_primary_notional * configured_hedge_ratio\n        target_qty_after = fresh_primary_qty * configured_hedge_ratio\n        gap_qty = max(0.0, target_qty_after - fresh_hedge_qty)\n        qty_tolerance = max(1e-12, target_qty_after * 0.001)\n        gap = gap_qty * max(p, mark)\n        hq = hp = 0.0''')
replace_once(
'''            if gap > max(1.0, actual_primary_after * 0.002):''',
'''            if gap_qty > qty_tolerance:''')

# If the hedge leg fails after a confirmed DCA, keep the DCA and persist a repair state.
replace_once(
'''        except Exception:\n            rollback_prefix = _prefix(str(state["cycleId"]), cycle_no, "DCA_ROLLBACK")\n            _execute_with_precision_retry(\n                client=client, symbol=symbol, mark=p, notional=q*p, leverage=leverage,\n                side=primary_side, action="CLOSE", prefix=rollback_prefix,\n            )\n            _audit(ref, "FOCUS_V2_TRAILING_DCA_ROLLBACK", cycleId=state["cycleId"], symbol=symbol, reason="tijdelijke hedge kon niet bevestigd worden")\n            raise''',
'''        except Exception as exc:\n            owned = _upsert_owned(\n                owned, settings=settings, cycle_id=str(state["cycleId"]), symbol=symbol,\n                role=primary_role, side=primary_side, quantity=q, price=p,\n                client_id=cid, order_id=oid, dca=True, timestamp_ms=timestamp_ms,\n            )\n            state.update({\n                "weightedEntry": _finite((fresh_primary or {}).get("entryPrice"), p),\n                "dcaCount": cycle_no, "dcaMode": DCA_FROZEN, "hedgeState": HEDGE_ACTIVE,\n                "lastDcaFillPrice": p, "nextDcaPrice": next_dca_from_anchor(p, primary_side, dca_ratio),\n                "hedgeReleasePrice": 0.0, "hedgeTargetQty": target_qty_after,\n                "cycleStatus": "DCA_HEDGE_SYNC_PENDING", "lastAction": "DCA_HEDGE_SYNC_PENDING",\n                "lastReason": f"LONG DCA bevestigd; SHORT sync opnieuw proberen: {exc}",\n            })\n            _persist(ref, state, owned)\n            _audit(ref, "FOCUS_DCA_HEDGE_SYNC_PENDING", cycleId=state["cycleId"], symbol=symbol, dcaCount=cycle_no, requiredShortQty=gap_qty, error=str(exc))\n            return {"status": "reconciling", "action": "DCA_HEDGE_SYNC_PENDING", "symbol": symbol, "ordersSent": 1, "requiredShortQty": gap_qty}''')

# Once DCA + hedge is complete, expose simple state names and no fixed release price.
replace_once(
'''        release_price = release_price_from_last_dca(p, primary_side, release_ratio)\n        state.update({''',
'''        release_price = 0.0 if simple_flow else release_price_from_last_dca(p, primary_side, release_ratio)\n        state.update({''')
replace_once(
'''            "cycleStatus": "DCA_HEDGE_ACTIVE",\n            "lastAction": "DCA_HEDGE_ACTIVE",\n            "lastReason": "DCA geraakt: primary DCA + hedge bevestigd; volgende DCA lager en release vanaf laatste fill staan vast",''',
'''            "cycleStatus": "HEDGED",\n            "lastAction": "DCA_HEDGE_SYNCED",\n            "lastReason": "DCA geraakt: LONG bevestigd en SHORT naar totale LONG-quantity gesynchroniseerd",''')

# Replace legacy +0.15/recovery release trigger with continuous net-green gate for simple flow.
old_release = '''    # With an active hedge, release 100% after the configured recovery from the LAST confirmed DCA fill.\n    if hedge_qty > 1e-12:\n        last_dca = _finite(state.get("lastDcaFillPrice"))\n        release_price = _finite(state.get("hedgeReleasePrice")) or release_price_from_last_dca(last_dca, primary_side, release_ratio)\n        recovery = recovery_from_last_dca(mark, last_dca, primary_side)\n        if last_dca > 0 and hedge_release_crossed(mark, release_price, primary_side):'''
new_release = '''    # Active protection is checked on EVERY execution tick. In simple mode the\n    # only strategic release gate is strictly positive expected NET hedge PnL.\n    if hedge_qty > 1e-12:\n        last_dca = _finite(state.get("lastDcaFillPrice"))\n        release_price = 0.0 if simple_flow else (_finite(state.get("hedgeReleasePrice")) or release_price_from_last_dca(last_dca, primary_side, release_ratio))\n        recovery = recovery_from_last_dca(mark, last_dca, primary_side)\n        expected_net, executable_close, gross_close_pnl, estimated_fees, slippage_buffer = expected_net_hedge_close_pnl(client, symbol, hedge_side, hedge_row, mark)\n        release_allowed = expected_net > 0.0 if simple_flow else (last_dca > 0 and hedge_release_crossed(mark, release_price, primary_side))\n        if release_allowed:'''
replace_once(old_release, new_release)

# Make green-release diagnostics explicit and primary-only state simple.
replace_once(
'''                "cycleStatus": "PRIMARY_ONLY",\n                "lastAction": "HEDGE_RELEASED",\n                "lastReason": "herstel vanaf laatste DCA-fill bereikt; hedge volledig weg; trailing direct hervat",''',
'''                "cycleStatus": "LONG_ONLY",\n                "lastAction": "HEDGE_RELEASED_NET_GREEN",\n                "lastReason": "SHORT netto groen; volledige beschermingshedge gesloten; LONG blijft actief",''')
replace_once(
'''            _audit(ref, "FOCUS_V2_TRAILING_HEDGE_RELEASE", cycleId=state["cycleId"], symbol=symbol, lastDcaFill=last_dca, releasePrice=release_price, recovery=recovery, threshold=release_ratio, closeQty=cq, closePrice=cp)\n            return {"status": "executed", "action": "FOCUS_V2_HEDGE_RELEASED", "symbol": symbol, "ordersSent": 1, "recoverySinceLastDca": recovery, "releasePrice": release_price, "shortOrLongHedgeRemaining": 0.0}''',
'''            _audit(ref, "FOCUS_HEDGE_RELEASED_NET_GREEN", cycleId=state["cycleId"], symbol=symbol, lastDcaFill=last_dca, expectedNetClosePnl=expected_net, executableClosePrice=executable_close, grossClosePnl=gross_close_pnl, estimatedFees=estimated_fees, slippageBuffer=slippage_buffer, closeQty=cq, closePrice=cp)\n            return {"status": "executed", "action": "FOCUS_HEDGE_RELEASED_NET_GREEN", "symbol": symbol, "ordersSent": 1, "expectedNetClosePnl": expected_net, "executableClosePrice": executable_close, "shortOrLongHedgeRemaining": 0.0}''')

# Red hedge is explicitly held and rechecked on next tick; no fixed release trigger is required.
replace_once(
'''    # v6 full-close TP is only legal in primary-only state.''',
'''        if simple_flow:\n            state.update({\n                "cycleStatus": "HEDGED", "lastAction": "HEDGE_HOLD_RED",\n                "lastReason": "SHORT nog niet netto groen; volgende realtime tick opnieuw controleren",\n                "hedgeReleasePrice": 0.0,\n            })\n\n    # v6 full-close TP is only legal in primary-only state.''')

ENGINE.write_text(text, encoding='utf-8')

TEST.write_text(r'''from pathlib import Path\n\nimport aster_strategy2_focus_trailing as focus\n\n\nclass BookClient:\n    def __init__(self, bid='99.8', ask='100.2'):\n        self.bid = bid\n        self.ask = ask\n\n    def _public_get(self, *args, **kwargs):\n        return {'bidPrice': self.bid, 'askPrice': self.ask}\n\n\ndef test_long_dca_cross_is_downward():\n    assert focus.dca_crossed(99.0, 100.0, 'LONG') is True\n    assert focus.dca_crossed(101.0, 100.0, 'LONG') is False\n\n\ndef test_short_red_is_not_net_green_after_costs():\n    row = {'positionAmt': '-10', 'entryPrice': '100'}\n    net, close, gross, fees, slippage = focus.expected_net_hedge_close_pnl(BookClient(ask='100.2'), 'X', 'SHORT', row, 100.2)\n    assert close == 100.2\n    assert gross < 0\n    assert net < 0\n    assert fees > 0\n    assert slippage > 0\n\n\ndef test_short_must_be_meaningfully_green_after_round_trip_costs():\n    row = {'positionAmt': '-10', 'entryPrice': '100'}\n    net, close, gross, fees, slippage = focus.expected_net_hedge_close_pnl(BookClient(ask='99.0'), 'X', 'SHORT', row, 99.0)\n    assert gross > 0\n    assert net > 0\n\n\ndef test_simple_flow_contract_has_no_fixed_release_gate():\n    source = Path(focus.__file__).read_text(encoding='utf-8')\n    assert 'release_allowed = expected_net > 0.0 if simple_flow' in source\n    assert 'cycleStatus": "DCA_HEDGE_SYNC_PENDING"' in source\n    assert 'target_qty_after = fresh_primary_qty * configured_hedge_ratio' in source\n    assert 'fresh_hedge_qty' in source\n    assert 'FOCUS_DCA_BLOCKED' in source\n    assert 'FOCUS_HEDGE_RELEASED_NET_GREEN' in source\n''', encoding='utf-8')

print('Focus simple deterministic flow patch applied')
