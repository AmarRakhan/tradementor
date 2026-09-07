from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"Expected source fragment not found in {path}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


maker = "web/components/aster-strategy2-maker.tsx"
guard = "web/lib/aster-strategy2-settings-guard.ts"
seat_test = "web/tests/strategy2-seat-volume-wizard.test.mjs"
hard_limit_test = "web/tests/strategy2-settings-hard-limits.test.mjs"

replace_once(
    maker,
    'import { strategy2ServerStatus } from "@/lib/aster-strategy2-server-status.mjs";\n',
    'import { strategy2ServerStatus } from "@/lib/aster-strategy2-server-status.mjs";\nimport { MAX_SIDE_SLOTS, MAX_TOTAL_POSITIONS, applyLongSlots, applyShortSlots, splitTotalPositions } from "@/lib/position-slot-input";\n',
)
replace_once(
    maker,
    '  const [totalDraft, setTotalDraft] = useState<string | null>(null);\n',
    '  const [totalDraft, setTotalDraft] = useState<string | null>(null);\n  const [longDraft, setLongDraft] = useState<string | null>(null);\n  const [shortDraft, setShortDraft] = useState<string | null>(null);\n',
)
replace_once(
    maker,
    '    const longSlots = clampInt(Number(x.longSlots ?? 20), 0, 25); const shortSlots = clampInt(Number(x.shortSlots ?? 10), 0, 25);\n',
    '    const longSlots = clampInt(Number(x.longSlots ?? 20), 0, MAX_SIDE_SLOTS); const shortSlots = clampInt(Number(x.shortSlots ?? 10), 0, MAX_SIDE_SLOTS);\n',
)
replace_once(
    maker,
    '      name: String(x.name || initial.name), universe: String(x.universeTopN ?? 30), positions: String(Math.min(50, longSlots + shortSlots)), longSlots: String(longSlots), shortSlots: String(shortSlots), minLeverage: String(x.minimumLeverage ?? 50),\n',
    '      name: String(x.name || initial.name), universe: String(x.universeTopN ?? 30), positions: String(Math.min(MAX_TOTAL_POSITIONS, longSlots + shortSlots)), longSlots: String(longSlots), shortSlots: String(shortSlots), minLeverage: String(x.minimumLeverage ?? 50),\n',
)
replace_once(
    maker,
    '    setTotalDraft(null);\n  }, [persisted, dirty]);\n',
    '    setTotalDraft(null);\n    setLongDraft(null);\n    setShortDraft(null);\n  }, [persisted, dirty]);\n',
)
replace_once(
    maker,
    '    const longSlots = clampInt(n(v.longSlots), 0, 25); const shortSlots = clampInt(n(v.shortSlots), 0, 25); const minLeverage = Math.max(1, Math.round(n(v.minLeverage)));\n',
    '    const longSlots = clampInt(n(v.longSlots), 0, MAX_SIDE_SLOTS); const shortSlots = clampInt(n(v.shortSlots), 0, MAX_SIDE_SLOTS); const minLeverage = Math.max(1, Math.round(n(v.minLeverage)));\n',
)
replace_once(
    maker,
    '      maximumPositions: Math.min(50, longSlots + shortSlots), longSlots, shortSlots, minimumLeverage: minLeverage, entrySizingMode: "margin",\n',
    '      maximumPositions: Math.min(MAX_TOTAL_POSITIONS, longSlots + shortSlots), longSlots, shortSlots, minimumLeverage: minLeverage, entrySizingMode: "margin",\n',
)
old_slot_logic = '''  const setTotal = (raw: string) => {\n    const total = clampInt(Number(raw), 1, 50); const oldLong = clampInt(n(v.longSlots), 0, 25); const oldShort = clampInt(n(v.shortSlots), 0, 25); const oldTotal = Math.max(1, oldLong + oldShort);\n    let long = Math.min(25, Math.round(total * oldLong / oldTotal)); let short = Math.min(25, total - long); if (long + short < total) long = Math.min(25, total - short);\n    change({ ...v, positions: String(long + short), longSlots: String(long), shortSlots: String(short) });\n  };\n  const commitTotal = () => { const raw = String(totalDraft ?? v.positions).trim(); setTotalDraft(null); if (raw) setTotal(raw); };\n  const setLong = (raw: string) => { const long = clampInt(Number(raw), 0, 25); const short = clampInt(n(v.shortSlots), 0, 25); change({ ...v, positions: String(long + short), longSlots: String(long), shortSlots: String(short) }); };\n  const setShort = (raw: string) => { const short = clampInt(Number(raw), 0, 25); const long = clampInt(n(v.longSlots), 0, 25); change({ ...v, positions: String(long + short), longSlots: String(long), shortSlots: String(short) }); };\n'''
new_slot_logic = '''  const setTotal = (raw: string) => {\n    const slots = splitTotalPositions(raw);\n    change({ ...v, positions: String(slots.total), longSlots: String(slots.long), shortSlots: String(slots.short) });\n  };\n  const commitTotal = () => { const raw = String(totalDraft ?? v.positions).trim(); setTotalDraft(null); if (raw) setTotal(raw); };\n  const setLong = (raw: string) => {\n    const slots = applyLongSlots(v.positions, raw);\n    change({ ...v, positions: String(slots.total), longSlots: String(slots.long), shortSlots: String(slots.short) });\n  };\n  const commitLong = () => { const raw = String(longDraft ?? v.longSlots).trim(); setLongDraft(null); if (raw) setLong(raw); };\n  const setShort = (raw: string) => {\n    const slots = applyShortSlots(v.positions, raw);\n    change({ ...v, positions: String(slots.total), longSlots: String(slots.long), shortSlots: String(slots.short) });\n  };\n  const commitShort = () => { const raw = String(shortDraft ?? v.shortSlots).trim(); setShortDraft(null); if (raw) setShort(raw); };\n'''
replace_once(maker, old_slot_logic, new_slot_logic)
replace_once(
    maker,
    '      if (settings.longSlots + settings.shortSlots < 1 || settings.longSlots > 25 || settings.shortSlots > 25 || settings.maximumPositions > 50) throw new Error("Positielimieten zijn ongeldig: maximaal 25 LONG + 25 SHORT (50 totaal).");\n',
    '      if (settings.longSlots + settings.shortSlots < 1 || settings.longSlots > MAX_SIDE_SLOTS || settings.shortSlots > MAX_SIDE_SLOTS || settings.maximumPositions > MAX_TOTAL_POSITIONS || settings.longSlots + settings.shortSlots !== settings.maximumPositions) throw new Error("Positielimieten zijn ongeldig: maximaal 100 totaal en LONG + SHORT moet exact gelijk zijn aan totaal.");\n',
)
replace_once(
    maker,
    '      <div className="position-settings-grid"><Field label="Totaal posities" value={totalDraft ?? v.positions} set={setTotalDraft} onBlur={commitTotal} /><Field label="LONG slots" value={v.longSlots} set={setLong} /><Field label="SHORT slots" value={v.shortSlots} set={setShort} /></div>\n',
    '      <div className="position-settings-grid"><Field label="Totaal posities" value={totalDraft ?? v.positions} set={setTotalDraft} onBlur={commitTotal} /><Field label="LONG slots" value={longDraft ?? v.longSlots} set={setLongDraft} onBlur={commitLong} /><Field label="SHORT slots" value={shortDraft ?? v.shortSlots} set={setShortDraft} onBlur={commitShort} /></div>\n',
)

replace_once(guard, 'const MAX_TOTAL_POSITIONS = 50;\nconst MAX_LONG_SLOTS = 25;\nconst MAX_SHORT_SLOTS = 25;\n', 'const MAX_TOTAL_POSITIONS = 100;\nconst MAX_LONG_SLOTS = 100;\nconst MAX_SHORT_SLOTS = 100;\n')
replace_once(seat_test, 'test("direct settings cap the Aster bot at 25 LONG plus 25 SHORT and 50 total", () => {\n', 'test("direct settings support up to 100 total positions with independent LONG and SHORT inputs", () => {\n')
replace_once(seat_test, '  assert.match(maker, /maximumPositions:\\s*Math\\.min\\(50, longSlots \\+ shortSlots\\)/);\n', '  assert.match(maker, /maximumPositions:\\s*Math\\.min\\(MAX_TOTAL_POSITIONS, longSlots \\+ shortSlots\\)/);\n')
replace_once(seat_test, '  assert.match(maker, /const longSlots = clampInt\\(n\\(v\\.longSlots\\), 0, 25\\)/);\n', '  assert.match(maker, /const longSlots = clampInt\\(n\\(v\\.longSlots\\), 0, MAX_SIDE_SLOTS\\)/);\n')
replace_once(seat_test, '  assert.match(maker, /const shortSlots = clampInt\\(n\\(v\\.shortSlots\\), 0, 25\\)/);\n', '  assert.match(maker, /const shortSlots = clampInt\\(n\\(v\\.shortSlots\\), 0, MAX_SIDE_SLOTS\\)/);\n')
replace_once(hard_limit_test, '  assert.match(guard, /MAX_TOTAL_POSITIONS = 50/);\n  assert.match(guard, /MAX_LONG_SLOTS = 25/);\n  assert.match(guard, /MAX_SHORT_SLOTS = 25/);\n', '  assert.match(guard, /MAX_TOTAL_POSITIONS = 100/);\n  assert.match(guard, /MAX_LONG_SLOTS = 100/);\n  assert.match(guard, /MAX_SHORT_SLOTS = 100/);\n')

Path("web/lib/position-slot-input.ts").write_text('''export const MAX_TOTAL_POSITIONS = 100;\nexport const MAX_SIDE_SLOTS = 100;\n\nexport type PositionSlotState = { total: number; long: number; short: number };\n\nfunction clampInteger(value: unknown, min: number, max: number) {\n  const number = Number(value);\n  const normalized = Number.isFinite(number) ? Math.round(number) : min;\n  return Math.max(min, Math.min(max, normalized));\n}\n\nexport function splitTotalPositions(value: unknown): PositionSlotState {\n  const total = clampInteger(value, 1, MAX_TOTAL_POSITIONS);\n  const long = Math.ceil(total / 2);\n  return { total, long, short: total - long };\n}\n\nexport function applyLongSlots(totalValue: unknown, longValue: unknown): PositionSlotState {\n  const total = clampInteger(totalValue, 1, MAX_TOTAL_POSITIONS);\n  const long = clampInteger(longValue, 0, Math.min(total, MAX_SIDE_SLOTS));\n  return { total, long, short: total - long };\n}\n\nexport function applyShortSlots(totalValue: unknown, shortValue: unknown): PositionSlotState {\n  const total = clampInteger(totalValue, 1, MAX_TOTAL_POSITIONS);\n  const short = clampInteger(shortValue, 0, Math.min(total, MAX_SIDE_SLOTS));\n  return { total, long: total - short, short };\n}\n''', encoding="utf-8")

Path("web/tests/position-slot-input.test.mjs").write_text('''import test from "node:test";\nimport assert from "node:assert/strict";\nimport { MAX_TOTAL_POSITIONS, applyLongSlots, applyShortSlots, splitTotalPositions } from "../lib/position-slot-input.ts";\n\ntest("total 70 defaults to a stable 35/35 split", () => {\n  assert.deepEqual(splitTotalPositions("70"), { total: 70, long: 35, short: 35 });\n});\n\ntest("odd totals use LONG first and still preserve the exact total", () => {\n  assert.deepEqual(splitTotalPositions("71"), { total: 71, long: 36, short: 35 });\n});\n\ntest("editing LONG keeps total fixed and derives SHORT", () => {\n  assert.deepEqual(applyLongSlots("70", "40"), { total: 70, long: 40, short: 30 });\n});\n\ntest("editing SHORT keeps total fixed and derives LONG", () => {\n  assert.deepEqual(applyShortSlots("70", "22"), { total: 70, long: 48, short: 22 });\n});\n\ntest("100 positions are accepted and values above the limit are clamped", () => {\n  assert.equal(MAX_TOTAL_POSITIONS, 100);\n  assert.deepEqual(splitTotalPositions("100"), { total: 100, long: 50, short: 50 });\n  assert.deepEqual(splitTotalPositions("101"), { total: 100, long: 50, short: 50 });\n});\n''', encoding="utf-8")

print("Position-slot input fix applied.")
