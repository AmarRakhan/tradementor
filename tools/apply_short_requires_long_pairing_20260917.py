from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Backend: persist the toggle through the canonical Multi BB config.
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "    long_slots: int = 20\n    short_slots: int = 10\n    minimum_leverage: int = 50\n",
    "    long_slots: int = 20\n    short_slots: int = 10\n    short_requires_long_enabled: bool = False\n    minimum_leverage: int = 50\n",
)
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "            long_slots=_i(raw.get(\"longSlots\", raw.get(\"maximumLongPositions\")), 20),\n            short_slots=_i(raw.get(\"shortSlots\", raw.get(\"maximumShortPositions\")), 10),\n            minimum_leverage=minimum_leverage,\n",
    "            long_slots=_i(raw.get(\"longSlots\", raw.get(\"maximumLongPositions\")), 20),\n            short_slots=_i(raw.get(\"shortSlots\", raw.get(\"maximumShortPositions\")), 10),\n            short_requires_long_enabled=bool(raw.get(\"shortRequiresLongEnabled\", raw.get(\"short_requires_long_enabled\", False))),\n            minimum_leverage=minimum_leverage,\n",
)
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "            \"longSlots\": self.long_slots, \"shortSlots\": self.short_slots, \"minimumLeverage\": self.minimum_leverage,\n            \"bollingerEntryFilter15mEnabled\": self.bollinger_entry_filter_15m_enabled,\n",
    "            \"longSlots\": self.long_slots, \"shortSlots\": self.short_slots, \"minimumLeverage\": self.minimum_leverage,\n            \"shortRequiresLongEnabled\": self.short_requires_long_enabled,\n            \"bollingerEntryFilter15mEnabled\": self.bollinger_entry_filter_15m_enabled,\n",
)

# Automatic scanner priority: when a SHORT already exists without its LONG,
# move that symbol to the front. Stable sorting preserves the original volume
# order inside the priority/non-priority groups. Manual symbol choices keep
# their explicit side and order.
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "    else:\n        pair_need = 0\n        long_need = max(0, settings.long_slots - long_count); short_need = max(0, settings.short_slots - short_count)\n        account_remaining_capacity = max(0, settings.maximum_positions - account_position_count)\n\n    # New seats: fill immediately from Top-N volume after leverage/order/margin checks.\n",
    "    else:\n        pair_need = 0\n        long_need = max(0, settings.long_slots - long_count); short_need = max(0, settings.short_slots - short_count)\n        account_remaining_capacity = max(0, settings.maximum_positions - account_position_count)\n\n    if settings.short_requires_long_enabled and not settings.asymmetric_hedge_enabled and not settings.manual_symbol_selection_enabled:\n        orphan_short_symbols = {\n            key.split(\"|\", 1)[0] for key in active\n            if key.endswith(\"|SHORT\") and f\"{key.split('|', 1)[0]}|LONG\" not in active\n        }\n        if orphan_short_symbols:\n            candidates = sorted(\n                candidates,\n                key=lambda row: 0 if str(row.get(\"symbol\", \"\")).upper() in orphan_short_symbols else 1,\n            )\n\n    # New seats: fill immediately from Top-N volume after leverage/order/margin checks.\n",
)

# Entry gate. Automatic mode is allowed to reroute an otherwise-invalid new
# SHORT candidate into a LONG candidate so LONG never waits for SHORT and the
# allocator cannot deadlock. Explicit manual SHORT choices are never silently
# rewritten; they wait until the same symbol has a LONG.
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "        else:\n            side = _next_entry_side(long_count=long_count,short_count=short_count,long_slots=settings.long_slots,short_slots=settings.short_slots)\n            if not side: break\n\n        # In normal Multi-DCA mode LONG and SHORT are independent seats.\n",
    "        else:\n            side = _next_entry_side(long_count=long_count,short_count=short_count,long_slots=settings.long_slots,short_slots=settings.short_slots)\n            if not side: break\n\n        short_requires_long_gate = settings.short_requires_long_enabled and not settings.asymmetric_hedge_enabled\n        manual_reserved = settings.manual_symbol_selection_enabled and bool(ranked_row.get(\"manualReserved\"))\n        if short_requires_long_gate and side == \"SHORT\" and f\"{symbol}|LONG\" not in active:\n            if not manual_reserved and long_need > 0:\n                side = \"LONG\"\n            else:\n                actions.append({\"kind\": \"ENTRY_SKIP\", \"symbol\": symbol, \"side\": \"SHORT\", \"reason\": \"SHORT_REQUIRES_LONG\"})\n                continue\n\n        # In normal Multi-DCA mode LONG and SHORT are independent seats.\n",
)

# Final exchange-truth check immediately before a live SHORT order. This closes
# the race where the paired LONG could disappear between candidate selection
# and order submission.
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "        short_action = ({\"kind\": \"ASYM_SHORT_ENTRY\", \"symbol\": symbol, \"side\": \"SHORT\", \"leverage\": short_plan.leverage, \"notionalUsd\": float(short_plan.notional_per_leg), \"marginUsd\": short_required, \"multiplier\": settings.short_start_multiplier} if paired and short_plan is not None else None)\n        if dry_run:\n",
    "        short_action = ({\"kind\": \"ASYM_SHORT_ENTRY\", \"symbol\": symbol, \"side\": \"SHORT\", \"leverage\": short_plan.leverage, \"notionalUsd\": float(short_plan.notional_per_leg), \"marginUsd\": short_required, \"multiplier\": settings.short_start_multiplier} if paired and short_plan is not None else None)\n        if not dry_run and short_requires_long_gate and side == \"SHORT\":\n            fresh_pair_positions = _position_map(client.position_risk(symbol))\n            if f\"{symbol}|LONG\" not in fresh_pair_positions:\n                actions.append({\"kind\": \"ENTRY_SKIP\", \"symbol\": symbol, \"side\": \"SHORT\", \"reason\": \"SHORT_REQUIRES_LONG\", \"stage\": \"pre_order\"})\n                continue\n        if dry_run:\n",
)
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "              \"bollingerEntryFilter15mEnabled\": settings.bollinger_entry_filter_15m_enabled, \"bollingerEntryFilterTimeframe\": settings.bollinger_entry_filter_timeframe,\n              \"asymmetricHedgeModeEnabled\": settings.asymmetric_hedge_enabled, \"shortStartMultiplier\": settings.short_start_multiplier,\n",
    "              \"bollingerEntryFilter15mEnabled\": settings.bollinger_entry_filter_15m_enabled, \"bollingerEntryFilterTimeframe\": settings.bollinger_entry_filter_timeframe,\n              \"shortRequiresLongEnabled\": settings.short_requires_long_enabled,\n              \"asymmetricHedgeModeEnabled\": settings.asymmetric_hedge_enabled, \"shortStartMultiplier\": settings.short_start_multiplier,\n",
)

# Frontend: one simple switch directly under the LONG/SHORT seat allocator.
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    "  mode: \"paper\" | \"live\"; manualEnabled: boolean; manualSymbols: ManualSymbol[];\n  smartRescueEnabled: boolean; smartRescueRange: string; smartRescueCount: string; smartRescueGrowth: string; smartRescueRecovery: string;\n",
    "  mode: \"paper\" | \"live\"; manualEnabled: boolean; manualSymbols: ManualSymbol[]; shortRequiresLongEnabled: boolean;\n  smartRescueEnabled: boolean; smartRescueRange: string; smartRescueCount: string; smartRescueGrowth: string; smartRescueRecovery: string;\n",
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    "  tpMode: \"PER_TRADE\", portfolioTp: \"20\", mode: \"live\", manualEnabled: false, manualSymbols: [],\n  smartRescueEnabled: false, smartRescueRange: \"10\", smartRescueCount: \"10\", smartRescueGrowth: \"1.35\", smartRescueRecovery: \"0.30\",\n",
    "  tpMode: \"PER_TRADE\", portfolioTp: \"20\", mode: \"live\", manualEnabled: false, manualSymbols: [], shortRequiresLongEnabled: false,\n  smartRescueEnabled: false, smartRescueRange: \"10\", smartRescueCount: \"10\", smartRescueGrowth: \"1.35\", smartRescueRecovery: \"0.30\",\n",
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    "      manualEnabled: x.manualSymbolSelectionEnabled === true, manualSymbols: parseManualSymbols(x.manualSymbols),\n      smartRescueEnabled: x.smartRescueEnabled === true, smartRescueRange: txt(x.smartRescueRangePercent, 10),\n",
    "      manualEnabled: x.manualSymbolSelectionEnabled === true, manualSymbols: parseManualSymbols(x.manualSymbols),\n      shortRequiresLongEnabled: x.shortRequiresLongEnabled === true,\n      smartRescueEnabled: x.smartRescueEnabled === true, smartRescueRange: txt(x.smartRescueRangePercent, 10),\n",
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    "      manualSymbolSelectionEnabled: v.manualEnabled, manualSymbols: v.manualEnabled ? v.manualSymbols : [],\n      smartRescueEnabled: v.smartRescueEnabled, smartRescueVersion: 1, smartRescueRangePercent: n(v.smartRescueRange),\n",
    "      manualSymbolSelectionEnabled: v.manualEnabled, manualSymbols: v.manualEnabled ? v.manualSymbols : [],\n      shortRequiresLongEnabled: v.shortRequiresLongEnabled,\n      smartRescueEnabled: v.smartRescueEnabled, smartRescueVersion: 1, smartRescueRangePercent: n(v.smartRescueRange),\n",
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    "      <div className=\"position-settings-grid\"><Field label=\"Totaal posities\" value={totalDraft ?? v.positions} set={setTotalDraft} onBlur={commitTotal} /><Field label=\"LONG slots\" value={longDraft ?? v.longSlots} set={setLongDraft} onBlur={commitLong} /><Field label=\"SHORT slots\" value={shortDraft ?? v.shortSlots} set={setShortDraft} onBlur={commitShort} /></div>\n      <Field label=\"Minimum leverage\" value={v.minLeverage} set={(value) => change({ ...v, minLeverage: value })} />\n",
    "      <div className=\"position-settings-grid\"><Field label=\"Totaal posities\" value={totalDraft ?? v.positions} set={setTotalDraft} onBlur={commitTotal} /><Field label=\"LONG slots\" value={longDraft ?? v.longSlots} set={setLongDraft} onBlur={commitLong} /><Field label=\"SHORT slots\" value={shortDraft ?? v.shortSlots} set={setShortDraft} onBlur={commitShort} /></div>\n      <div className={`strategy-power-control short-pair-control ${v.shortRequiresLongEnabled ? \"enabled\" : \"ready\"}`}><span><b>SHORT alleen met LONG</b><small>LONG mag altijd zelfstandig openen · ontbrekende LONG krijgt scanner-prioriteit</small></span><button type=\"button\" role=\"switch\" aria-checked={v.shortRequiresLongEnabled} onClick={() => change({ ...v, shortRequiresLongEnabled: !v.shortRequiresLongEnabled })}><i />{v.shortRequiresLongEnabled ? \"Aan\" : \"Uit\"}</button></div>\n      <Field label=\"Minimum leverage\" value={v.minLeverage} set={(value) => change({ ...v, minLeverage: value })} />\n",
)

# Focused regression suite, including a source contract for the UI wiring.
test_path = ROOT / "cloud_api/test_short_requires_long_pairing_20260917.py"
test_path.write_text(r'''from pathlib import Path
import time

from aster_multi_bb import run_multi_bb_step
from test_aster_multi_bb import Client, Ref, cfg


def pos(symbol: str, side: str, *, mark: float = 100.0):
    return {"symbol": symbol, "positionSide": side, "positionAmt": "1", "entryPrice": "100", "markPrice": str(mark), "leverage": "100"}


def state_for(symbol: str, side: str):
    return {"multiBbPositions": {f"{symbol}|{side}": {"cycleId": "c1", "dcaCount": 0, "lastBotFillPrice": 100, "lastKnownQty": 1, "lastKnownEntry": 100, "cycleStartedAtMs": 1, "botManaged": True}}}


def run(*, settings, positions=None, raw_state=None, tickers=None, prices=None):
    positions = list(positions or [])
    tickers = list(tickers or [{"symbol": "AAAUSDT", "quoteVolume": "1000"}])
    prices = dict(prices or {str(row["symbol"]): 100 for row in tickers})
    client = Client(positions=positions, tickers=tickers, prices=prices, leverage=100)
    return run_multi_bb_step(
        client=client, ref=Ref(), raw_state=raw_state or {}, settings=settings, uid="u",
        account={"availableBalance": "1000"}, positions=positions, open_orders=[],
        timestamp_ms=int(time.time() * 1000), dry_run=True,
    )


def test_toggle_roundtrips_through_public_settings():
    settings = cfg(shortRequiresLongEnabled=True)
    assert settings.short_requires_long_enabled is True
    assert settings.public_dict()["shortRequiresLongEnabled"] is True


def test_new_short_is_blocked_without_same_symbol_long_when_enabled():
    result = run(settings=cfg(maximumPositions=1, longSlots=0, shortSlots=1, shortRequiresLongEnabled=True))
    assert not [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert any(row.get("reason") == "SHORT_REQUIRES_LONG" for row in result["actions"])


def test_legacy_short_entry_still_works_when_toggle_is_off():
    result = run(settings=cfg(maximumPositions=1, longSlots=0, shortSlots=1, shortRequiresLongEnabled=False))
    entry = next(row for row in result["actions"] if row.get("kind") == "ENTRY")
    assert entry["symbol"] == "AAAUSDT"
    assert entry["side"] == "SHORT"


def test_short_can_open_when_same_symbol_long_already_exists():
    long = pos("AAAUSDT", "LONG")
    result = run(
        settings=cfg(maximumPositions=2, longSlots=1, shortSlots=1, shortRequiresLongEnabled=True),
        positions=[long], raw_state=state_for("AAAUSDT", "LONG"),
    )
    entry = next(row for row in result["actions"] if row.get("kind") == "ENTRY")
    assert entry["symbol"] == "AAAUSDT"
    assert entry["side"] == "SHORT"


def test_orphan_short_symbol_gets_long_priority_over_higher_volume_unpaired_coin():
    short = pos("AAAUSDT", "SHORT")
    result = run(
        settings=cfg(maximumPositions=2, longSlots=1, shortSlots=1, shortRequiresLongEnabled=True),
        positions=[short], raw_state=state_for("AAAUSDT", "SHORT"),
        tickers=[{"symbol": "BBBUSDT", "quoteVolume": "2000"}, {"symbol": "AAAUSDT", "quoteVolume": "1000"}],
        prices={"AAAUSDT": 100, "BBBUSDT": 100},
    )
    entry = next(row for row in result["actions"] if row.get("kind") == "ENTRY")
    assert entry["symbol"] == "AAAUSDT"
    assert entry["side"] == "LONG"


def test_existing_short_dca_is_not_blocked_by_entry_only_pairing_gate():
    short = pos("AAAUSDT", "SHORT", mark=101.0)
    result = run(
        settings=cfg(maximumPositions=1, longSlots=0, shortSlots=1, shortRequiresLongEnabled=True, maxDca=3),
        positions=[short], raw_state=state_for("AAAUSDT", "SHORT"),
        tickers=[], prices={"AAAUSDT": 101.0},
    )
    assert any(row.get("kind") == "DCA" and row.get("side") == "SHORT" for row in result["actions"])


def test_frontend_toggle_is_loaded_saved_and_rendered_next_to_seat_controls():
    source = (Path(__file__).resolve().parents[1] / "web/components/aster-strategy2-maker.tsx").read_text(encoding="utf-8")
    assert "shortRequiresLongEnabled: boolean" in source
    assert "shortRequiresLongEnabled: x.shortRequiresLongEnabled === true" in source
    assert "shortRequiresLongEnabled: v.shortRequiresLongEnabled" in source
    assert "SHORT alleen met LONG" in source
    assert "LONG mag altijd zelfstandig openen" in source
''', encoding="utf-8")

print("Applied SHORT-requires-LONG pairing gate, priority, UI toggle and regressions.")
