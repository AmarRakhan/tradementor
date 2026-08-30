from pathlib import Path

ENGINE = Path('cloud_api/aster_strategy2_focus_trailing.py')
TEST = Path('cloud_api/test_aster_strategy2_focus_trailing.py')

text = ENGINE.read_text(encoding='utf-8')


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly one match, got {count}')
    text = text.replace(old, new, 1)


# Keep the module contract aligned with Simple Mode: every DCA is a ratcheting
# trailing level. It follows favorable price movement, never chases price lower.
text = text.replace(
    '- while the hedge is active, the next DCA stays fixed one configured DCA-step beyond the last confirmed DCA fill;\n',
    '- in Simple Mode every DCA is a ratcheting trailing level: it follows fresh highs upward and never moves down during a pullback;\n',
    1,
)
text = text.replace(
    '- each deeper DCA replaces both the next-DCA and hedge-release references;\n',
    '- after each confirmed DCA the trailing anchor resets to that fill/current price and the next DCA starts one configured step below it;\n',
    1,
)

# Previously only DCA #1 trailed while hedged. In Simple Mode ALL DCA levels use
# the same ratchet: LONG anchor=max(previous anchor, live mark). This means a +12%
# rally pulls the DCA +12% upward; a subsequent decline leaves the DCA frozen at
# its last highest-derived value so price can cross it.
replace_once(
'''    # Primary-only OR initial start-hedge phase: DCA #1 moves on every fresh extreme.\n    initial_hedged_trailing = hedge_qty > 1e-12 and int(_finite(state.get("dcaCount"))) == 0 and _finite(state.get("lastDcaFillPrice")) <= 0\n    if hedge_qty <= 1e-12 or initial_hedged_trailing:\n        if primary_side == "LONG":\n            anchor = max(_finite(state.get("trailingHigh"), mark), mark)\n            state["trailingHigh"] = anchor\n        else:\n            current = _finite(state.get("trailingLow"), mark)\n            anchor = min(current, mark) if current > 0 else mark\n            state["trailingLow"] = anchor\n        state["nextDcaPrice"] = next_dca_from_anchor(anchor, primary_side, dca_ratio)\n        state["dcaAnchorPrice"] = anchor\n        state["dcaMode"] = DCA_TRAILING\n        state["hedgeState"] = HEDGE_ACTIVE if initial_hedged_trailing else HEDGE_OFF\n        state["cycleStatus"] = "TRAILING_HEDGED" if initial_hedged_trailing else "PRIMARY_ONLY"\n        state["frozenDcaReference"] = 0.0\n        state["hedgeReleasePrice"] = 0.0\n        state["hedgeTargetQty"] = primary_qty * configured_start_hedge_ratio if initial_hedged_trailing else 0.0\n    else:\n''',
'''    # Simple Mode: EVERY DCA ratchets from the freshest favorable extreme.\n    # LONG: fresh highs raise the DCA; falling ticks never lower it.\n    # After each fill the anchor is reset (see DCA execution below), so the next\n    # DCA starts one configured step below the new fill/current price.\n    initial_hedged_trailing = hedge_qty > 1e-12 and int(_finite(state.get("dcaCount"))) == 0 and _finite(state.get("lastDcaFillPrice")) <= 0\n    if simple_flow or hedge_qty <= 1e-12 or initial_hedged_trailing:\n        if primary_side == "LONG":\n            anchor = max(_finite(state.get("trailingHigh"), mark), mark)\n            state["trailingHigh"] = anchor\n        else:\n            current = _finite(state.get("trailingLow"), mark)\n            anchor = min(current, mark) if current > 0 else mark\n            state["trailingLow"] = anchor\n        state["nextDcaPrice"] = next_dca_from_anchor(anchor, primary_side, dca_ratio)\n        state["dcaAnchorPrice"] = anchor\n        state["dcaMode"] = DCA_TRAILING\n        if simple_flow:\n            state["hedgeState"] = HEDGE_ACTIVE if hedge_qty > 1e-12 else HEDGE_OFF\n            state["cycleStatus"] = "HEDGED" if hedge_qty > 1e-12 else "LONG_ONLY"\n            state["hedgeTargetQty"] = primary_qty * configured_hedge_ratio if hedge_qty > 1e-12 else 0.0\n        else:\n            state["hedgeState"] = HEDGE_ACTIVE if initial_hedged_trailing else HEDGE_OFF\n            state["cycleStatus"] = "TRAILING_HEDGED" if initial_hedged_trailing else "PRIMARY_ONLY"\n            state["hedgeTargetQty"] = primary_qty * configured_start_hedge_ratio if initial_hedged_trailing else 0.0\n        state["frozenDcaReference"] = 0.0\n        state["hedgeReleasePrice"] = 0.0\n    else:\n''',
'all-DCA trailing block',
)

# If a DCA fill is confirmed but hedge synchronization is still pending, start
# the NEW ratchet from that fill immediately. The next DCA itself remains blocked
# by DCA_HEDGE_SYNC_PENDING until the 1:1 hedge invariant is restored.
text = text.replace(
    '"dcaCount": cycle_no, "dcaMode": DCA_FROZEN, "hedgeState": HEDGE_ACTIVE,\n                "lastDcaFillPrice": p, "nextDcaPrice": next_dca_from_anchor(p, primary_side, dca_ratio),',
    '"dcaCount": cycle_no, "dcaMode": DCA_TRAILING if simple_flow else DCA_FROZEN, "hedgeState": HEDGE_ACTIVE,\n                "lastDcaFillPrice": p, "trailingHigh": p if primary_side == "LONG" else _finite(state.get("trailingHigh")), "trailingLow": p if primary_side == "SHORT" else _finite(state.get("trailingLow")), "dcaAnchorPrice": p, "nextDcaPrice": next_dca_from_anchor(p, primary_side, dca_ratio),',
    2,
)

# A fully successful DCA must also reset the ratchet to its new fill/current price
# instead of leaving the next level in FIXED_DURING_HEDGE mode.
replace_once(
'''        next_fixed_dca = next_dca_from_anchor(p, primary_side, dca_ratio)\n        release_price = 0.0 if simple_flow else release_price_from_last_dca(p, primary_side, release_ratio)\n        state.update({\n            "weightedEntry": new_entry,\n            "dcaCount": cycle_no,\n            "dcaMode": DCA_FROZEN,\n            "hedgeState": HEDGE_ACTIVE,\n            "frozenDcaReference": 0.0,\n            "lastDcaFillPrice": p,\n            "nextDcaPrice": next_fixed_dca,\n''',
'''        next_dca_after_fill = next_dca_from_anchor(p, primary_side, dca_ratio)\n        release_price = 0.0 if simple_flow else release_price_from_last_dca(p, primary_side, release_ratio)\n        state.update({\n            "weightedEntry": new_entry,\n            "dcaCount": cycle_no,\n            "dcaMode": DCA_TRAILING if simple_flow else DCA_FROZEN,\n            "hedgeState": HEDGE_ACTIVE,\n            "frozenDcaReference": 0.0,\n            "lastDcaFillPrice": p,\n            "trailingHigh": p if primary_side == "LONG" else _finite(state.get("trailingHigh")),\n            "trailingLow": p if primary_side == "SHORT" else _finite(state.get("trailingLow")),\n            "dcaAnchorPrice": p,\n            "nextDcaPrice": next_dca_after_fill,\n''',
'successful DCA ratchet reset',
)

ENGINE.write_text(text, encoding='utf-8')

# Add a behavior test proving DCA #3 (not just DCA #1) follows a +12% rally and
# does NOT chase price lower on the pullback while the SHORT hedge is active.
test = TEST.read_text(encoding='utf-8')
marker = '\ndef test_v6_full_tp_is_blocked_by_hedge_and_closes_when_flat(monkeypatch):\n'
new_test = '''\ndef test_v6_every_dca_ratchets_up_with_live_high_even_while_hedged(monkeypatch):\n    import aster_strategy2_focus_trailing as engine\n    monkeypatch.setattr(engine, "_selected_symbol", lambda *_a, **_k: "BTCUSDT")\n    settings = _v6_settings(focusV2AmountsAreMargin=False, focusDcaDistance=.003)\n    raw = {"focusV2State": {\n        "cycleId": "c", "symbol": "BTCUSDT", "primarySide": "LONG", "dcaCount": 2,\n        "lastDcaFillPrice": 99.0, "trailingHigh": 100.0, "nextDcaPrice": 98.703,\n        "hedgeState": "ACTIVE", "cycleStatus": "HEDGED", "stateMachineVersion": 6,\n    }}\n    positions_up = [_pos("LONG", 70, 100, 112, 840), _pos("SHORT", 70, 100, 112, -840)]\n    ref = _Ref()\n    up = engine.run_focus_v2_live_step(\n        client=_RuntimeClient(positions_up, 112), ref=ref, raw_state=raw, settings=settings, uid="u",\n        account={"totalMarginBalance": "500", "availableBalance": "400", "totalMaintMargin": "0"},\n        positions=positions_up, timestamp_ms=20,\n    )\n    assert up["ordersSent"] == 0\n    raised = ref.values[-1]["focusV2State"]\n    assert raised["dcaMode"] == DCA_TRAILING\n    assert raised["trailingHigh"] == pytest.approx(112.0)\n    assert raised["nextDcaPrice"] == pytest.approx(111.664)\n\n    # Pullback: the trailing high and DCA must stay where the +12% rally put them.\n    positions_down = [_pos("LONG", 70, 100, 111.9, 833), _pos("SHORT", 70, 100, 111.9, -833)]\n    ref2 = _Ref()\n    down = engine.run_focus_v2_live_step(\n        client=_RuntimeClient(positions_down, 111.9), ref=ref2, raw_state={"focusV2State": raised},\n        settings=settings, uid="u",\n        account={"totalMarginBalance": "500", "availableBalance": "400", "totalMaintMargin": "0"},\n        positions=positions_down, timestamp_ms=21,\n    )\n    assert down["ordersSent"] == 0\n    held = ref2.values[-1]["focusV2State"]\n    assert held["trailingHigh"] == pytest.approx(112.0)\n    assert held["nextDcaPrice"] == pytest.approx(111.664)\n\n'''
if 'test_v6_every_dca_ratchets_up_with_live_high_even_while_hedged' not in test:
    if marker not in test:
        raise SystemExit('test insertion marker missing')
    test = test.replace(marker, new_test + marker, 1)
TEST.write_text(test, encoding='utf-8')

print('Applied Focus Simple Mode all-DCA ratcheting trailing behavior')
