from pathlib import Path

BACKEND = Path("cloud_api/aster_multi_bb_core.py")
TEST = Path("cloud_api/test_short_requires_long_pairing_20260917.py")


def replace_exact(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1)
    if count == 0 and new in text:
        return text
    raise RuntimeError(f"{label}: expected one old snippet (or already-repaired new snippet), found {count}")


source = BACKEND.read_text(encoding="utf-8")

source = replace_exact(
    source,
    '''        short_requires_long_gate = settings.short_requires_long_enabled and not settings.asymmetric_hedge_enabled\n        manual_reserved = settings.manual_symbol_selection_enabled and bool(ranked_row.get("manualReserved"))\n        if short_requires_long_gate and side == "SHORT" and f"{symbol}|LONG" not in active:\n            if not manual_reserved and long_need > 0:\n                side = "LONG"\n            else:\n                actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "side": "SHORT", "reason": "SHORT_REQUIRES_LONG"})\n                continue\n''',
    '''        # Strict entry-only pairing gate.  It applies to every NEW initial SHORT\n        # route, including manual selection and asymmetric hedge mode.  A blocked\n        # SHORT is never silently converted into a LONG; LONG allocation remains\n        # independent and is evaluated through its normal scanner path.\n        short_requires_long_gate = settings.short_requires_long_enabled\n        if short_requires_long_gate and side == "SHORT" and f"{symbol}|LONG" not in active:\n            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "side": "SHORT", "reason": "SHORT_REQUIRES_LONG", "stage": "candidate"})\n            continue\n''',
    label="initial strict gate",
)

source = replace_exact(
    source,
    '''            if settings.bollinger_entry_filter_15m_enabled and not candidate_bb_pass(side):\n                continue\n        paired = bool(settings.asymmetric_hedge_enabled)\n        if paired and (short_need <= 0 or account_remaining_capacity < 2 or budget - sent < 2):\n''',
    '''            if settings.bollinger_entry_filter_15m_enabled and not candidate_bb_pass(side):\n                continue\n\n        # The final side can change after the allocator gate above (notably in\n        # the independent Bollinger scan or opposite-seat fallback).  Re-apply\n        # the same-pair rule here so no later side selection can leak a SHORT.\n        if short_requires_long_gate and side == "SHORT" and f"{symbol}|LONG" not in active:\n            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "side": "SHORT", "reason": "SHORT_REQUIRES_LONG", "stage": "final_side"})\n            continue\n\n        paired = bool(settings.asymmetric_hedge_enabled)\n        # In paired mode the toggle means the LONG must already exist in the\n        # exchange snapshot that started this reconciliation tick.  A LONG that\n        # is only being opened in this same tick does not authorize its SHORT.\n        defer_paired_short = bool(paired and settings.short_requires_long_enabled and f"{symbol}|LONG" not in active)\n        if paired and (short_need <= 0 or account_remaining_capacity < 2 or budget - sent < 2):\n''',
    label="post-selection strict gate",
)

source = replace_exact(
    source,
    '''        total_required = required + short_required\n''',
    '''        total_required = required + (0.0 if defer_paired_short else short_required)\n''',
    label="paired margin deferral",
)

source = replace_exact(
    source,
    '''        if dry_run:\n            actions.append(entry_action)\n            if short_action is not None: actions.append(short_action)\n        else:\n''',
    '''        if dry_run:\n            actions.append(entry_action)\n            if short_action is not None and not defer_paired_short:\n                actions.append(short_action)\n            elif short_action is not None and defer_paired_short:\n                actions.append({"kind": "ASYM_SHORT_ENTRY_PENDING", "symbol": symbol, "side": "SHORT", "reason": "SHORT_REQUIRES_PREEXISTING_LONG"})\n        else:\n''',
    label="dry-run paired deferral",
)

source = replace_exact(
    source,
    '''            actions.append(entry_action)\n            if paired and short_plan is not None and short_action is not None:\n                try:\n''',
    '''            actions.append(entry_action)\n            if paired and short_plan is not None and short_action is not None and defer_paired_short:\n                pending = dict(state[key]); pending.update({"pairedShortPending": True, "pairedShortLastError": "SHORT_REQUIRES_PREEXISTING_LONG", "updatedAtMs": timestamp_ms}); state[key] = pending\n                ref.set({"multiBbPositions": state, "phase": "RUNNING", "lastReason": f"Asymmetrische hedge: LONG {symbol} bevestigd; initiële SHORT wacht tot een volgende exchange-snapshot"}, merge=True)\n                actions.append({"kind": "ASYM_SHORT_ENTRY_PENDING", "symbol": symbol, "side": "SHORT", "reason": "SHORT_REQUIRES_PREEXISTING_LONG"})\n            if paired and short_plan is not None and short_action is not None and not defer_paired_short:\n                try:\n''',
    label="live paired deferral",
)

source = replace_exact(
    source,
    '''        consumed = 2 if paired and (dry_run or f"{symbol}|SHORT" in state) else 1\n''',
    '''        consumed = 2 if paired and ((dry_run and not defer_paired_short) or f"{symbol}|SHORT" in state) else 1\n''',
    label="paired consumed accounting",
)

source = replace_exact(
    source,
    '''                if available < required_short * 1.05:\n                    actions.append({"kind": "ASYM_SHORT_RECOVERY_WAIT", "symbol": symbol, "reason": "INSUFFICIENT_AVAILABLE_MARGIN"}); continue\n                actions.append({"kind": "ASYM_SHORT_RECOVERY", "symbol": symbol, "multiplier": settings.short_start_multiplier})\n                if not dry_run:\n                    recovered = execute_leg_once(client, short_plan, side=PositionSide.SHORT, action="OPEN", id_prefix=f"mbb-asym-short-{st0.get('cycleId')}", confirm=True, new_position_leverage=current_lev, before_submit=before_order)\n''',
    '''                if available < required_short * 1.05:\n                    actions.append({"kind": "ASYM_SHORT_RECOVERY_WAIT", "symbol": symbol, "reason": "INSUFFICIENT_AVAILABLE_MARGIN"}); continue\n                # Recovery is the only paired route that may create the delayed\n                # SHORT while the toggle is on.  Re-read exchange truth directly\n                # before submission so a stale/closed LONG can never authorize it.\n                if not dry_run and settings.short_requires_long_enabled:\n                    fresh_pair_positions = _position_map(client.position_risk(symbol))\n                    if key not in fresh_pair_positions:\n                        actions.append({"kind": "ASYM_SHORT_RECOVERY_WAIT", "symbol": symbol, "reason": "SHORT_REQUIRES_LONG", "stage": "pre_order"})\n                        continue\n                actions.append({"kind": "ASYM_SHORT_RECOVERY", "symbol": symbol, "multiplier": settings.short_start_multiplier})\n                if not dry_run:\n                    recovered = execute_leg_once(client, short_plan, side=PositionSide.SHORT, action="OPEN", id_prefix=f"mbb-asym-short-{st0.get('cycleId')}", confirm=True, new_position_leverage=current_lev, before_submit=before_order)\n''',
    label="paired recovery exchange guard",
)

# Guard against the exact regressions that caused the live UNI leak.
assert "short_requires_long_gate = settings.short_requires_long_enabled and not settings.asymmetric_hedge_enabled" not in source
assert '"stage": "final_side"' in source
assert "SHORT_REQUIRES_PREEXISTING_LONG" in source
assert 'fresh_pair_positions = _position_map(client.position_risk(symbol))' in source

BACKEND.write_text(source, encoding="utf-8")

# Append focused regression tests once.  Existing tests remain intact.
test_source = TEST.read_text(encoding="utf-8")
marker = "def test_different_symbol_long_does_not_authorize_short():"
if marker not in test_source:
    test_source += r'''


def test_different_symbol_long_does_not_authorize_short():
    other_long = pos("BBBUSDT", "LONG")
    result = run(
        settings=cfg(maximumPositions=2, longSlots=1, shortSlots=1, shortRequiresLongEnabled=True),
        positions=[other_long], raw_state=state_for("BBBUSDT", "LONG"),
        tickers=[{"symbol": "AAAUSDT", "quoteVolume": "1000"}], prices={"AAAUSDT": 100, "BBBUSDT": 100},
    )
    assert not [row for row in result["actions"] if row.get("kind") == "ENTRY" and row.get("side") == "SHORT"]
    assert any(row.get("symbol") == "AAAUSDT" and row.get("reason") == "SHORT_REQUIRES_LONG" for row in result["actions"])


def test_manual_selected_short_cannot_bypass_same_pair_long_gate():
    result = run(settings=cfg(
        maximumPositions=1, longSlots=0, shortSlots=1, shortRequiresLongEnabled=True,
        manualSymbolSelectionEnabled=True, manualSymbols=[{"symbol": "AAAUSDT", "side": "SHORT"}],
    ))
    assert not [row for row in result["actions"] if row.get("kind") == "ENTRY" and row.get("side") == "SHORT"]
    assert any(row.get("reason") == "SHORT_REQUIRES_LONG" for row in result["actions"])


def test_asymmetric_mode_defers_same_tick_short_until_long_preexists():
    result = run(settings=cfg(
        maximumPositions=2, longSlots=1, shortSlots=1, shortRequiresLongEnabled=True,
        asymmetricHedgeModeEnabled=True, shortStartMultiplier=2,
    ))
    assert any(row.get("kind") == "ENTRY" and row.get("side") == "LONG" for row in result["actions"])
    assert not any(row.get("kind") == "ASYM_SHORT_ENTRY" for row in result["actions"])
    assert any(row.get("kind") == "ASYM_SHORT_ENTRY_PENDING" and row.get("reason") == "SHORT_REQUIRES_PREEXISTING_LONG" for row in result["actions"])


def test_source_reapplies_gate_after_final_bollinger_side_selection():
    source = (Path(__file__).resolve().parent / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    selected = source.index("side = selected_side")
    final_gate = source.index('"stage": "final_side"')
    planning = source.index("paired = bool(settings.asymmetric_hedge_enabled)", final_gate)
    assert selected < final_gate < planning
    assert "short_requires_long_gate = settings.short_requires_long_enabled and not settings.asymmetric_hedge_enabled" not in source


def test_paired_short_recovery_rechecks_exchange_long_before_live_submit():
    source = (Path(__file__).resolve().parent / "aster_multi_bb_core.py").read_text(encoding="utf-8")
    recovery = source.index("# Recover an initial paired SHORT idempotently")
    pre_order_guard = source.index('"stage": "pre_order"', recovery)
    submit = source.index('id_prefix=f"mbb-asym-short-', pre_order_guard)
    assert recovery < pre_order_guard < submit
'''
    TEST.write_text(test_source, encoding="utf-8")

print("STRICT_SHORT_REQUIRES_LONG_REPAIR_APPLIED=1")
