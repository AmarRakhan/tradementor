from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:160]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Orphan SHORT rescue must be a real queue, not merely a sort of the current Top-N.
old_priority = '''    if settings.short_requires_long_enabled and not settings.asymmetric_hedge_enabled and not settings.manual_symbol_selection_enabled:\n        orphan_short_symbols = {\n            key.split("|", 1)[0] for key in active\n            if key.endswith("|SHORT") and f"{key.split('|', 1)[0]}|LONG" not in active\n        }\n        if orphan_short_symbols:\n            candidates = sorted(\n                candidates,\n                key=lambda row: 0 if str(row.get("symbol", "")).upper() in orphan_short_symbols else 1,\n            )\n'''
new_priority = '''    orphan_short_symbols: list[str] = []\n    if settings.short_requires_long_enabled and not settings.asymmetric_hedge_enabled and long_need > 0:\n        # Exchange truth is authoritative. Every currently-open SHORT without a\n        # same-symbol LONG becomes an explicit LONG rescue candidate. Inject it\n        # even when that symbol is outside the configured Top-N volume list.\n        orphan_short_symbols = sorted({\n            key.split("|", 1)[0] for key in active\n            if key.endswith("|SHORT") and f"{key.split('|', 1)[0]}|LONG" not in active\n        })\n        existing_candidates = {str(row.get("symbol", "")).upper(): row for row in candidates}\n        rescue_rows: list[dict[str, Any]] = []\n        for orphan_symbol in orphan_short_symbols:\n            if orphan_symbol not in info_map or prices.get(orphan_symbol, 0) <= 0:\n                actions.append({"kind": "ENTRY_SKIP", "symbol": orphan_symbol, "side": "LONG", "reason": "ORPHAN_LONG_MARKET_DATA_UNAVAILABLE"})\n                continue\n            base_row = dict(existing_candidates.get(orphan_symbol) or {"symbol": orphan_symbol, "quoteVolume": 0.0})\n            base_row["symbol"] = orphan_symbol\n            base_row["orphanShortPriority"] = True\n            rescue_rows.append(base_row)\n        if rescue_rows:\n            rescue_symbols = {str(row["symbol"]).upper() for row in rescue_rows}\n            candidates = rescue_rows + [row for row in candidates if str(row.get("symbol", "")).upper() not in rescue_symbols]\n'''
replace_once("cloud_api/aster_multi_bb_core.py", old_priority, new_priority)

old_side = '''        if settings.asymmetric_hedge_enabled:\n            # Exclusive paired mode: the old independent LONG/SHORT allocator is disabled.\n            # Every new scanner candidate is exactly one same-symbol LONG+SHORT pair.\n            if long_need <= 0 or short_need <= 0:\n                break\n            side = "LONG"\n        elif settings.manual_symbol_selection_enabled and ranked_row.get("manualReserved"):\n'''
new_side = '''        if ranked_row.get("orphanShortPriority") and long_need > 0:\n            # Hard priority: a free LONG seat is consumed by an orphan SHORT pair\n            # before the ordinary allocator is allowed to choose unrelated coins.\n            side = "LONG"\n        elif settings.asymmetric_hedge_enabled:\n            # Exclusive paired mode: the old independent LONG/SHORT allocator is disabled.\n            # Every new scanner candidate is exactly one same-symbol LONG+SHORT pair.\n            if long_need <= 0 or short_need <= 0:\n                break\n            side = "LONG"\n        elif settings.manual_symbol_selection_enabled and ranked_row.get("manualReserved"):\n'''
replace_once("cloud_api/aster_multi_bb_core.py", old_side, new_side)

# Expose rescue state in the scan report for UI/diagnostics.
old_report = '''              "actions": actions[-30:], "rankedTopN": ranked, "candidateMode": "manual" if settings.manual_symbol_selection_enabled else "top_n",\n              "manualSymbols": [{"symbol": symbol, "side": side} for symbol, side in settings.manual_symbols], "longSlots": settings.long_slots, "shortSlots": settings.short_slots,\n'''
new_report = '''              "actions": actions[-30:], "rankedTopN": ranked, "candidateMode": "manual" if settings.manual_symbol_selection_enabled else "top_n",\n              "manualSymbols": [{"symbol": symbol, "side": side} for symbol, side in settings.manual_symbols], "longSlots": settings.long_slots, "shortSlots": settings.short_slots,\n              "orphanShortSymbols": orphan_short_symbols,\n              "orphanLongPending": [symbol for symbol in orphan_short_symbols if f"{symbol}|LONG" not in active and f"{symbol}|LONG" not in state],\n'''
replace_once("cloud_api/aster_multi_bb_core.py", old_report, new_report)

# Regression: orphan outside Top-N must still be injected and forced LONG first.
test_path = ROOT / "cloud_api/test_short_requires_long_pairing_20260917.py"
test_text = test_path.read_text(encoding="utf-8")
marker = "def test_orphan_outside_top_n_is_injected_and_forced_long_first():"
if marker not in test_text:
    test_text += r'''


def test_orphan_outside_top_n_is_injected_and_forced_long_first():
    short = pos("ZECUSDT", "SHORT")
    result = run(
        settings=cfg(maximumPositions=3, longSlots=2, shortSlots=1, shortRequiresLongEnabled=True, universeTopN=1),
        positions=[short], raw_state=state_for("ZECUSDT", "SHORT"),
        tickers=[{"symbol": "AAAUSDT", "quoteVolume": "999999"}],
        prices={"AAAUSDT": 100, "ZECUSDT": 100},
    )
    entries = [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert entries, result
    assert entries[0]["symbol"] == "ZECUSDT"
    assert entries[0]["side"] == "LONG"
    assert "ZECUSDT" in result["orphanShortSymbols"]


def test_multiple_orphan_shorts_consume_free_long_seats_before_normal_candidates():
    shorts = [pos("AAAUSDT", "SHORT"), pos("BBBUSDT", "SHORT")]
    raw = {"multiBbPositions": {}}
    raw["multiBbPositions"].update(state_for("AAAUSDT", "SHORT")["multiBbPositions"])
    raw["multiBbPositions"].update(state_for("BBBUSDT", "SHORT")["multiBbPositions"])
    result = run(
        settings=cfg(maximumPositions=4, longSlots=2, shortSlots=2, shortRequiresLongEnabled=True, universeTopN=1),
        positions=shorts, raw_state=raw,
        tickers=[{"symbol": "CCCUSDT", "quoteVolume": "999999"}],
        prices={"AAAUSDT": 100, "BBBUSDT": 100, "CCCUSDT": 100},
    )
    entries = [(row["symbol"], row["side"]) for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert entries[:2] == [("AAAUSDT", "LONG"), ("BBBUSDT", "LONG")]
'''
    test_path.write_text(test_text, encoding="utf-8")

# 2) Portfolio snapshot: never keep an activePositions scalar that disagrees
# with a concrete exchange positions array.
cache = ROOT / "web/lib/aster-snapshot-cache.mjs"
cache_text = cache.read_text(encoding="utf-8")
helper_anchor = 'const isRecord = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);\n'
helper = '''const isRecord = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);\n\nexport function countOpenAsterPositions(snapshot) {\n  if (!Array.isArray(snapshot?.positions)) return null;\n  return snapshot.positions.reduce((count, row) => {\n    if (!row || typeof row !== "object") return count;\n    const raw = row.positionAmt ?? row.quantity ?? row.qty ?? row.size;\n    const quantity = Number(raw);\n    return count + (Number.isFinite(quantity) && Math.abs(quantity) > 0 ? 1 : 0);\n  }, 0);\n}\n\nfunction canonicalizeAsterPositionCount(snapshot) {\n  const count = countOpenAsterPositions(snapshot);\n  return count === null ? snapshot : { ...snapshot, activePositions: count, positionCountIncluded: count };\n}\n'''
if "function canonicalizeAsterPositionCount" not in cache_text:
    if helper_anchor not in cache_text: raise RuntimeError("aster snapshot helper anchor missing")
    cache_text = cache_text.replace(helper_anchor, helper, 1)
    cache_text = cache_text.replace('  if (!isRecord(previous)) return incoming;\n', '  if (!isRecord(previous)) return canonicalizeAsterPositionCount(incoming);\n', 1)
    cache_text = cache_text.replace('  return merged;\n}\n\nexport function mergeCompleteAsterSnapshot', '  return canonicalizeAsterPositionCount(merged);\n}\n\nexport function mergeCompleteAsterSnapshot', 1)
    cache_text = cache_text.replace('  return merged;\n}\n\nexport function mergeAsterSnapshotWithHistoryFallback', '  return canonicalizeAsterPositionCount(merged);\n}\n\nexport function mergeAsterSnapshotWithHistoryFallback', 1)
    cache_text = cache_text.replace('    return { data: saved.data, updatedAt: saved.updatedAt };\n', '    return { data: canonicalizeAsterPositionCount(saved.data), updatedAt: saved.updatedAt };\n', 1)
    cache.write_text(cache_text, encoding="utf-8")

web_test = ROOT / "web/tests/aster-snapshot-position-count.test.mjs"
if not web_test.exists():
    web_test.write_text(r'''import test from "node:test";
import assert from "node:assert/strict";
import { countOpenAsterPositions, mergeCompleteAsterSnapshot, preserveConfirmedAsterValues } from "../lib/aster-snapshot-cache.mjs";

const history = { historyAvailable: true, closedTrades: [], realizedEvents: [] };
const row = (symbol, side, amount) => ({ symbol, positionSide: side, positionAmt: String(amount) });

test("concrete Aster positions array is authoritative for active position count", () => {
  const account = { configured: true, strategy2: {}, activePositions: 21, positionCountIncluded: 21,
    positions: [row("ZECUSDT", "SHORT", 1), row("ETHUSDT", "LONG", 2), row("BTCUSDT", "LONG", 0)] };
  const merged = mergeCompleteAsterSnapshot(account, history);
  assert.equal(countOpenAsterPositions(merged), 2);
  assert.equal(merged.activePositions, 2);
  assert.equal(merged.positionCountIncluded, 2);
});

test("newer positions array cannot inherit a stale cached activePositions scalar", () => {
  const previous = { configured: true, strategy2: {}, ...history, activePositions: 21, positions: [row("OLDUSDT", "LONG", 1)] };
  const incoming = { configured: true, strategy2: {}, ...history, activePositions: undefined,
    positions: [row("ZECUSDT", "SHORT", 1), row("ETHUSDT", "LONG", 1)] };
  const merged = preserveConfirmedAsterValues(previous, incoming);
  assert.equal(merged.activePositions, 2);
});
''', encoding="utf-8")

print("orphan SHORT rescue + Aster snapshot count repair applied")
