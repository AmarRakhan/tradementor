from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"Expected snippet not found in {path}: {old[:180]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


core = "cloud_api/aster_multi_bb_core.py"

# Manual selections are side-specific. LONG and SHORT on the same symbol are
# independent seats in the current strategy, so dedupe by (symbol, side), not symbol.
replace_once(
    core,
    '''            if not symbol or side not in {"LONG", "SHORT"} or symbol in seen: continue\n            seen.add(symbol); manual_symbols.append((symbol, side))''',
    '''            key=(symbol, side)\n            if not symbol or side not in {"LONG", "SHORT"} or key in seen: continue\n            seen.add(key); manual_symbols.append(key)''',
)

# Preserve legacy isolation for unselected/manual-external dual-side positions,
# but when manual selection explicitly reserves both LONG and SHORT of one symbol,
# those sides are independent managed seats and must not be isolated as a hedge.
replace_once(
    core,
    '''        conflicts = sorted(symbol for symbol, sides in symbol_sides.items() if len(sides) > 1)''',
    '''        conflicts = sorted(symbol for symbol, sides in symbol_sides.items()\n                           if len(sides) > 1 and not (settings.manual_symbol_selection_enabled and all(f"{symbol}|{side}" in selected_keys for side in sides)))''',
)

# If a manually selected exchange position is present but its managed state row
# is missing, the management loop currently skips it completely. Recover it
# safely from exchange truth and re-arm DCA from the current mark. Re-arming from
# current mark intentionally avoids blind catch-up of already-missed levels.
anchor = '''    available = _f(account.get("availableBalance", account.get("availableMargin")))\n    actions: list[dict[str, Any]] = []\n\n    # Exchange truth reconciles every already-managed leg.'''
insert = '''    available = _f(account.get("availableBalance", account.get("availableMargin")))\n    actions: list[dict[str, Any]] = []\n\n    # P0 recovery: selected manual-mode positions must never exist on Aster\n    # without a managed state row. Such a missing row makes the DCA management\n    # loop skip the position entirely. Recover from exchange truth and re-arm\n    # from the current mark so missed historical levels are not blindly replayed.\n    if settings.manual_symbol_selection_enabled:\n        for key in sorted(selected_keys):\n            if key in state or key not in pmap:\n                continue\n            row = pmap[key]\n            qty = abs(_f(row.get("positionAmt")))\n            entry = _f(row.get("entryPrice"))\n            mark = _f(row.get("markPrice"), prices.get(str(row.get("symbol", "")).upper(), entry))\n            if qty <= 0 or entry <= 0:\n                continue\n            rearm_anchor = mark if mark > 0 else entry\n            symbol, side = key.split("|", 1)\n            recovered = {\n                "cycleId": hashlib.sha256((uid+key+str(timestamp_ms)).encode()).hexdigest()[:16],\n                "dcaCount": 0,\n                "lastBotFillPrice": rearm_anchor,\n                "lastKnownQty": qty,\n                "lastKnownEntry": entry,\n                "leverage": max(1, _i(row.get("leverage"))),\n                "cycleStartedAtMs": timestamp_ms,\n                "updatedAtMs": timestamp_ms,\n                "botManaged": True,\n                "selectedStateRecoveredAtMs": timestamp_ms,\n                "selectedStateRecoveryAnchor": rearm_anchor,\n                "recoveredFromSelectedOpenPosition": True,\n            }\n            state[key] = recovered\n            action = {\n                "kind": "SELECTED_POSITION_STATE_RECOVERED",\n                "symbol": symbol, "side": side,\n                "anchor": rearm_anchor,\n                "reason": "SELECTED_OPEN_POSITION_MISSING_MANAGED_STATE",\n            }\n            actions.append(action)\n            if not dry_run:\n                ref.collection("audit").add({\n                    "event": "SELECTED_POSITION_STATE_RECOVERED", "user": uid,\n                    "symbol": symbol, "side": side, "anchor": rearm_anchor,\n                    "reason": action["reason"], "timestamp": datetime.now(timezone.utc),\n                })\n\n    # Exchange truth reconciles every already-managed leg.'''
replace_once(core, anchor, insert)


test_path = Path("cloud_api/test_aster_multi_bb.py")
text = test_path.read_text(encoding="utf-8")
marker = "def test_manual_selected_open_position_missing_state_is_safely_rearmed():"
if marker not in text:
    text += r'''


def test_manual_selected_open_position_missing_state_is_safely_rearmed():
    pos={"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"89.41","markPrice":"87.34","leverage":"100"}
    c=Client(positions=[pos],tickers=[{"symbol":"AAAUSDT","quoteVolume":"100"}],prices={"AAAUSDT":87.34},leverage=100)
    settings=manual_cfg([{"symbol":"AAAUSDT","side":"LONG"}],maximumPositions=1,longSlots=1,shortSlots=0,dcaDistance=.003)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=settings,uid="u",account={"availableBalance":"100"},positions=[pos],open_orders=[],timestamp_ms=10000,dry_run=True)
    recovered=next(x for x in r["actions"] if x["kind"]=="SELECTED_POSITION_STATE_RECOVERED")
    assert recovered["anchor"] == pytest.approx(87.34)
    assert not any(x["kind"]=="DCA" for x in r["actions"])


def test_manual_selected_missing_state_recovery_persists_and_next_real_move_can_dca():
    pos={"symbol":"AAAUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"89.41","markPrice":"87.34","leverage":"100"}
    c=Client(positions=[pos],tickers=[{"symbol":"AAAUSDT","quoteVolume":"100"}],prices={"AAAUSDT":87.34},leverage=100)
    settings=manual_cfg([{"symbol":"AAAUSDT","side":"LONG"}],maximumPositions=1,longSlots=1,shortSlots=0,dcaDistance=.003)
    ref=Ref()
    run_multi_bb_step(client=c,ref=ref,raw_state={},settings=settings,uid="u",account={"availableBalance":"100"},positions=[pos],open_orders=[],timestamp_ms=10000,dry_run=False)
    persisted=next(row["multiBbPositions"] for row in reversed(ref.updates) if "multiBbPositions" in row)
    assert persisted["AAAUSDT|LONG"]["lastBotFillPrice"] == pytest.approx(87.34)
    pos2={**pos,"markPrice":"87.00"}
    c2=Client(positions=[pos2],tickers=[{"symbol":"AAAUSDT","quoteVolume":"100"}],prices={"AAAUSDT":87.00},leverage=100)
    r2=run_multi_bb_step(client=c2,ref=Ref(),raw_state={"multiBbPositions":persisted},settings=settings,uid="u",account={"availableBalance":"100"},positions=[pos2],open_orders=[],timestamp_ms=11000,dry_run=True)
    assert any(x["kind"]=="DCA" and x["symbol"]=="AAAUSDT" and x["side"]=="LONG" for x in r2["actions"])


def test_manual_selection_allows_same_symbol_long_and_short_as_independent_sides():
    settings=manual_cfg([
        {"symbol":"BTCUSDT","side":"LONG"},
        {"symbol":"BTCUSDT","side":"SHORT"},
    ],maximumPositions=2,longSlots=1,shortSlots=1)
    assert settings.manual_symbols == (("BTCUSDT","LONG"),("BTCUSDT","SHORT"))
'''
    test_path.write_text(text, encoding="utf-8")
