from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected source block not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    maker = ROOT / "web/components/aster-strategy2-maker.tsx"
    text = maker.read_text(encoding="utf-8")
    if "fixedPositionSize: boolean" not in text:
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '  stopLossEnabled: boolean; stopLossMode: StopLossMode; stopLossLong: string; stopLossShort: string;\n'
            '  entryMarginLong: string; entryMarginShort: string;\n',
            '  stopLossEnabled: boolean; stopLossMode: StopLossMode; stopLossLong: string; stopLossShort: string;\n'
            '  fixedPositionSize: boolean;\n'
            '  entryMarginLong: string; entryMarginShort: string; entryNotionalLong: string; entryNotionalShort: string;\n',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '  stopLossEnabled: false, stopLossMode: "PERCENT", stopLossLong: "5", stopLossShort: "5",\n'
            '  entryMarginLong: "5", entryMarginShort: "5", longDcaDistance: "0.30", shortDcaDistance: "0.30",\n',
            '  stopLossEnabled: false, stopLossMode: "PERCENT", stopLossLong: "5", stopLossShort: "5",\n'
            '  fixedPositionSize: false, entryMarginLong: "5", entryMarginShort: "5", entryNotionalLong: "250", entryNotionalShort: "250",\n'
            '  longDcaDistance: "0.30", shortDcaDistance: "0.30",\n',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '    const legacyEntry = Number(x.entryMarginUsd ?? 5);\n'
            '    const legacyDcaDistance = Number(x.dcaDistance ?? .003);',
            '    const legacyEntry = Number(x.entryMarginUsd ?? 5);\n'
            '    const persistedMinLeverage = Math.max(1, Number(x.minimumLeverage ?? 50));\n'
            '    const legacyLongMargin = Number(x.entryMarginLongUsd ?? x.entryMarginLong ?? legacyEntry);\n'
            '    const legacyShortMargin = Number(x.entryMarginShortUsd ?? x.entryMarginShort ?? legacyEntry);\n'
            '    const legacyLongNotional = Number(x.entryNotionalLongUsd ?? x.entryNotionalLong ?? x.entryNotionalUsd ?? legacyLongMargin * persistedMinLeverage);\n'
            '    const legacyShortNotional = Number(x.entryNotionalShortUsd ?? x.entryNotionalShort ?? legacyShortMargin * persistedMinLeverage);\n'
            '    const legacyDcaDistance = Number(x.dcaDistance ?? .003);',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '      stopLossEnabled: x.stopLossEnabled === true, stopLossMode: String(x.stopLossMode || "PERCENT").toUpperCase() === "USD" ? "USD" : "PERCENT", stopLossLong: txt(x.stopLossLong, 5), stopLossShort: txt(x.stopLossShort, 5),\n'
            '      entryMarginLong: txt(x.entryMarginLongUsd ?? x.entryMarginLong ?? legacyEntry, legacyEntry), entryMarginShort: txt(x.entryMarginShortUsd ?? x.entryMarginShort ?? legacyEntry, legacyEntry),\n',
            '      stopLossEnabled: x.stopLossEnabled === true, stopLossMode: String(x.stopLossMode || "PERCENT").toUpperCase() === "USD" ? "USD" : "PERCENT", stopLossLong: txt(x.stopLossLong, 5), stopLossShort: txt(x.stopLossShort, 5),\n'
            '      fixedPositionSize: String(x.entrySizingMode || "margin").toLowerCase() === "notional",\n'
            '      entryMarginLong: txt(legacyLongMargin, legacyEntry), entryMarginShort: txt(legacyShortMargin, legacyEntry),\n'
            '      entryNotionalLong: txt(legacyLongNotional, legacyEntry * persistedMinLeverage), entryNotionalShort: txt(legacyShortNotional, legacyEntry * persistedMinLeverage),\n',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '    const longEntry = n(v.entryMarginLong); const shortEntry = n(v.entryMarginShort);\n',
            '    const longEntry = n(v.entryMarginLong); const shortEntry = n(v.entryMarginShort);\n'
            '    const longNotional = n(v.entryNotionalLong); const shortNotional = n(v.entryNotionalShort);\n',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '      maximumPositions: Math.min(MAX_TOTAL_POSITIONS, longSlots + shortSlots), longSlots, shortSlots, minimumLeverage: minLeverage, maximumLeverage: maxLeverage, entrySizingMode: "margin",\n'
            '      entryMarginUsd: longEntry, entryMarginLongUsd: longEntry, entryMarginShortUsd: shortEntry, entryMarginLong: longEntry, entryMarginShort: shortEntry,\n'
            '      entryNotionalUsd: longEntry * minLeverage,\n',
            '      maximumPositions: Math.min(MAX_TOTAL_POSITIONS, longSlots + shortSlots), longSlots, shortSlots, minimumLeverage: minLeverage, maximumLeverage: maxLeverage,\n'
            '      entrySizingMode: v.fixedPositionSize ? "notional" : "margin",\n'
            '      entryMarginUsd: longEntry, entryMarginLongUsd: longEntry, entryMarginShortUsd: shortEntry, entryMarginLong: longEntry, entryMarginShort: shortEntry,\n'
            '      entryNotionalUsd: longNotional, entryNotionalLongUsd: longNotional, entryNotionalShortUsd: shortNotional, entryNotionalLong: longNotional, entryNotionalShort: shortNotional,\n',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '      if (settings.longSlots > 0 && settings.entryMarginLongUsd <= 0) throw new Error("Instap LONG moet groter dan 0 USDT zijn.");\n'
            '      if (settings.shortSlots > 0 && settings.entryMarginShortUsd <= 0) throw new Error("Instap SHORT moet groter dan 0 USDT zijn.");\n',
            '      if (settings.entrySizingMode === "notional") {\n'
            '        if (settings.longSlots > 0 && settings.entryNotionalLongUsd <= 0) throw new Error("Positie LONG moet groter dan 0 USDT zijn.");\n'
            '        if (settings.shortSlots > 0 && settings.entryNotionalShortUsd <= 0) throw new Error("Positie SHORT moet groter dan 0 USDT zijn.");\n'
            '      } else {\n'
            '        if (settings.longSlots > 0 && settings.entryMarginLongUsd <= 0) throw new Error("Instapmargin LONG moet groter dan 0 USDT zijn.");\n'
            '        if (settings.shortSlots > 0 && settings.entryMarginShortUsd <= 0) throw new Error("Instapmargin SHORT moet groter dan 0 USDT zijn.");\n'
            '      }\n',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '      const entry = row.side === "SHORT" ? v.entryMarginShort : v.entryMarginLong; const dca = row.side === "SHORT" ? v.shortDcaAmount : v.longDcaAmount;\n'
            '      const query: Record<string, string> = { symbol: row.symbol, minimumLeverage: String(Math.max(1, Math.round(n(v.minLeverage)))), entryMarginUsd: String(Math.max(.01, n(entry))), dcaMarginUsd: String(Math.max(.01, n(dca))) }; if (v.maxLeverage.trim()) query.maximumLeverage = String(Math.max(1, Math.round(n(v.maxLeverage)))); const q = new URLSearchParams(query);\n',
            '      const entryMargin = row.side === "SHORT" ? v.entryMarginShort : v.entryMarginLong; const entryNotional = row.side === "SHORT" ? v.entryNotionalShort : v.entryNotionalLong; const dca = row.side === "SHORT" ? v.shortDcaAmount : v.longDcaAmount;\n'
            '      const query: Record<string, string> = { symbol: row.symbol, minimumLeverage: String(Math.max(1, Math.round(n(v.minLeverage)))), entrySizingMode: v.fixedPositionSize ? "notional" : "margin", dcaMarginUsd: String(Math.max(.01, n(dca))) };\n'
            '      if (v.fixedPositionSize) query.entryNotionalUsd = String(Math.max(.01, n(entryNotional))); else query.entryMarginUsd = String(Math.max(.01, n(entryMargin)));\n'
            '      if (v.maxLeverage.trim()) query.maximumLeverage = String(Math.max(1, Math.round(n(v.maxLeverage)))); const q = new URLSearchParams(query);\n',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '  }, [v.manualEnabled, v.manualSymbols, v.minLeverage, v.maxLeverage, v.entryMarginLong, v.entryMarginShort, v.longDcaAmount, v.shortDcaAmount]);\n',
            '  }, [v.manualEnabled, v.manualSymbols, v.minLeverage, v.maxLeverage, v.fixedPositionSize, v.entryMarginLong, v.entryMarginShort, v.entryNotionalLong, v.entryNotionalShort, v.longDcaAmount, v.shortDcaAmount]);\n',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '  const smartPreviewLeverage = Math.max(1, Number(firstSelectedLeverage || n(v.minLeverage) || 1));\n'
            '  const smartPreview = useMemo(() => buildSmartPreview(Math.max(.00000001, n(v.entryMarginLong)), smartPreviewLeverage, Math.max(.000001, n(v.smartRescueRange)), clampInt(n(v.smartRescueCount), 1, MAX_DCA), Math.max(1, n(v.smartRescueGrowth))), [v.entryMarginLong, v.smartRescueRange, v.smartRescueCount, v.smartRescueGrowth, smartPreviewLeverage]);\n',
            '  const smartPreviewLeverage = Math.max(1, Number(firstSelectedLeverage || n(v.minLeverage) || 1));\n'
            '  const smartStartMargin = v.fixedPositionSize ? Math.max(.00000001, n(v.entryNotionalLong) / smartPreviewLeverage) : Math.max(.00000001, n(v.entryMarginLong));\n'
            '  const smartPreview = useMemo(() => buildSmartPreview(smartStartMargin, smartPreviewLeverage, Math.max(.000001, n(v.smartRescueRange)), clampInt(n(v.smartRescueCount), 1, MAX_DCA), Math.max(1, n(v.smartRescueGrowth))), [smartStartMargin, v.smartRescueRange, v.smartRescueCount, v.smartRescueGrowth, smartPreviewLeverage]);\n',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '      if (kind === "save") { setDirty(false); setMessage("Instellingen server-side opgeslagen. Actieve posities, fills, avg entry, DCA-counts en Portfolio TP-cycle zijn intact gebleven."); }\n',
            '      if (kind === "save") {\n'
            '        const savedSettings = confirmed?.settings && typeof confirmed.settings === "object" ? confirmed.settings as Record<string, unknown> : null;\n'
            '        if (!savedSettings) throw new Error("Server bevestigde de opgeslagen Botinstellingen niet.");\n'
            '        const savedMax = savedSettings.maximumLeverage === null || savedSettings.maximumLeverage === undefined ? null : Number(savedSettings.maximumLeverage);\n'
            '        if (savedMax !== settings.maximumLeverage) throw new Error("Maximum leverage is niet server-side bevestigd; instellingen blijven als niet opgeslagen gemarkeerd.");\n'
            '        const savedSizing = String(savedSettings.entrySizingMode || "margin").toLowerCase();\n'
            '        if (savedSizing !== settings.entrySizingMode) throw new Error("Positieomvang-modus is niet server-side bevestigd; instellingen blijven als niet opgeslagen gemarkeerd.");\n'
            '        setV((current) => ({ ...current, maxLeverage: savedMax === null ? "" : String(savedMax), fixedPositionSize: savedSizing === "notional" }));\n'
            '        setDirty(false); setMessage("Instellingen server-side opgeslagen en bevestigd. Actieve posities, fills, avg entry, DCA-counts en Portfolio TP-cycle zijn intact gebleven.");\n'
            '      }\n',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '    </section>\n\n    <div className="maker-input compact-settings-grid">\n',
            '    </section>\n\n'
            '    <div className={"strategy-power-control entry-sizing-control " + (v.fixedPositionSize ? "enabled" : "ready")}>\n'
            '      <span className="pair-icon">◎</span><span><b>Vaste positieomvang</b><small>Aan: instapbedrag = totale positie in USDT · margin = positie ÷ leverage. Uit: instapbedrag = margin.</small></span>\n'
            '      <button type="button" role="switch" aria-checked={v.fixedPositionSize} onClick={() => change({ ...v, fixedPositionSize: !v.fixedPositionSize })}><i />{v.fixedPositionSize ? "Aan" : "Uit"}</button>\n'
            '    </div>\n\n'
            '    <div className="maker-input compact-settings-grid">\n',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '<Field label="Instap LONG" value={v.entryMarginLong} set={(value) => change({ ...v, entryMarginLong: value })} suffix="USDT" />',
            '<Field label={v.fixedPositionSize ? "Instap LONG · positie" : "Instap LONG · margin"} value={v.fixedPositionSize ? v.entryNotionalLong : v.entryMarginLong} set={(value) => v.fixedPositionSize ? change({ ...v, entryNotionalLong: value }) : change({ ...v, entryMarginLong: value })} suffix="USDT" />',
        )
        replace_once(
            "web/components/aster-strategy2-maker.tsx",
            '<Field label="Instap SHORT" value={v.entryMarginShort} set={(value) => change({ ...v, entryMarginShort: value })} suffix="USDT" disabled={v.smartRescueEnabled} />',
            '<Field label={v.fixedPositionSize ? "Instap SHORT · positie" : "Instap SHORT · margin"} value={v.fixedPositionSize ? v.entryNotionalShort : v.entryMarginShort} set={(value) => v.fixedPositionSize ? change({ ...v, entryNotionalShort: value }) : change({ ...v, entryMarginShort: value })} suffix="USDT" disabled={v.smartRescueEnabled} />',
        )

    route = ROOT / "web/app/api/exchanges/aster/strategy2/settings/route.ts"
    rtext = route.read_text(encoding="utf-8")
    if '"entrySizingMode"' not in rtext:
        replace_once(
            "web/app/api/exchanges/aster/strategy2/settings/route.ts",
            '  "maximumLeverage",\n'
            '  "stopLossEnabled",\n',
            '  "maximumLeverage",\n'
            '  "entrySizingMode",\n'
            '  "entryNotionalUsd",\n'
            '  "entryNotionalLongUsd",\n'
            '  "entryNotionalShortUsd",\n'
            '  "entryMarginLongUsd",\n'
            '  "entryMarginShortUsd",\n'
            '  "stopLossEnabled",\n',
        )

    test = ROOT / "web/tests/bot-settings-premium-maxlev-stoploss.test.mjs"
    t = test.read_text(encoding="utf-8")
    if 'fixed position size is optional' not in t:
        t += """
test("fixed position size is optional, explicit and persisted", () => {
  assert.ok(maker.includes("Vaste positieomvang"));
  assert.ok(maker.includes('role="switch" aria-checked={v.fixedPositionSize}'));
  assert.ok(maker.includes('entrySizingMode: v.fixedPositionSize ? "notional" : "margin"'));
  assert.ok(maker.includes("entryNotionalLongUsd: longNotional"));
  assert.ok(maker.includes("entryNotionalShortUsd: shortNotional"));
  assert.ok(maker.includes('"Instap LONG · positie"'));
  assert.ok(maker.includes('"Instap LONG · margin"'));
  assert.ok(maker.includes("margin = positie ÷ leverage"));
});

test("settings route preserves sizing mode and side notionals", () => {
  for (const key of ["entrySizingMode", "entryNotionalUsd", "entryNotionalLongUsd", "entryNotionalShortUsd"]) {
    assert.ok(settingsRoute.includes('"' + key + '"'), "missing sizing preservation key: " + key);
  }
});

test("confirmed save verifies maximum leverage and sizing mode before clearing dirty state", () => {
  assert.ok(maker.includes("Maximum leverage is niet server-side bevestigd"));
  assert.ok(maker.includes("Positieomvang-modus is niet server-side bevestigd"));
  assert.ok(maker.includes("setDirty(false)"));
});
"""
        test.write_text(t, encoding="utf-8")

    focus_test = ROOT / "web/tests/strategy2-focus-preview-price.test.mjs"
    focus_text = focus_test.read_text(encoding="utf-8")
    old_focus = '''test("Multi BB entry sizing keeps margin semantics with independent LONG and SHORT values", () => {
  assert.match(maker, /Instap LONG/);
  assert.match(maker, /Instap SHORT/);
  assert.match(maker, /entrySizingMode: "margin"/);
  assert.match(maker, /DCA-bedrag LONG/);
  assert.match(maker, /DCA-bedrag SHORT/);
  assert.doesNotMatch(maker, /focusExposurePreview/);
});'''
    new_focus = '''test("Multi BB entry sizing keeps independent LONG and SHORT values with optional fixed position size", () => {
  assert.match(maker, /Instap LONG/);
  assert.match(maker, /Instap SHORT/);
  assert.match(maker, /fixedPositionSize:\\s*false/);
  assert.match(maker, /entrySizingMode:\\s*v\\.fixedPositionSize \\? "notional" : "margin"/);
  assert.match(maker, /entryMarginLongUsd:\\s*longEntry/);
  assert.match(maker, /entryMarginShortUsd:\\s*shortEntry/);
  assert.match(maker, /entryNotionalLongUsd:\\s*longNotional/);
  assert.match(maker, /entryNotionalShortUsd:\\s*shortNotional/);
  assert.match(maker, /DCA-bedrag LONG/);
  assert.match(maker, /DCA-bedrag SHORT/);
  assert.doesNotMatch(maker, /focusExposurePreview/);
});'''
    if old_focus in focus_text:
        focus_test.write_text(focus_text.replace(old_focus, new_focus, 1), encoding="utf-8")

    manual_test = ROOT / "web/tests/strategy2-manual-margin-unlimited-dca.test.mjs"
    manual_text = manual_test.read_text(encoding="utf-8")
    old_manual = '''test("manual and automatic selection keep margin sizing with side-specific entries", () => {
  assert.match(maker, /Instap LONG/);
  assert.match(maker, /Instap SHORT/);
  assert.match(maker, /entrySizingMode:\\s*"margin"/);
  assert.match(maker, /entryMarginLongUsd:\\s*longEntry/);
  assert.match(maker, /entryMarginShortUsd:\\s*shortEntry/);
  assert.doesNotMatch(maker, /entrySizingMode:\\s*v\\.manualEnabled/);
});'''
    new_manual = '''test("manual and automatic selection share optional fixed-position sizing with side-specific entries", () => {
  assert.match(maker, /Instap LONG/);
  assert.match(maker, /Instap SHORT/);
  assert.match(maker, /fixedPositionSize:\\s*false/);
  assert.match(maker, /entrySizingMode:\\s*v\\.fixedPositionSize \\? "notional" : "margin"/);
  assert.match(maker, /entryMarginLongUsd:\\s*longEntry/);
  assert.match(maker, /entryMarginShortUsd:\\s*shortEntry/);
  assert.match(maker, /entryNotionalLongUsd:\\s*longNotional/);
  assert.match(maker, /entryNotionalShortUsd:\\s*shortNotional/);
  assert.doesNotMatch(maker, /entrySizingMode:\\s*v\\.manualEnabled/);
});'''
    if old_manual in manual_text:
        manual_test.write_text(manual_text.replace(old_manual, new_manual, 1), encoding="utf-8")

    seat_test = ROOT / "web/tests/strategy2-seat-volume-wizard.test.mjs"
    seat_text = seat_test.read_text(encoding="utf-8")
    old_seat = '  assert.match(maker, /entrySizingMode: "margin"/);'
    new_seat = '''  assert.match(maker, /fixedPositionSize:\\s*false/);
  assert.match(maker, /entrySizingMode:\\s*v\\.fixedPositionSize \\? "notional" : "margin"/);'''
    if old_seat in seat_text:
        seat_test.write_text(seat_text.replace(old_seat, new_seat, 1), encoding="utf-8")

    version = ROOT / "web/lib/app-version.ts"
    vtext = version.read_text(encoding="utf-8")
    if 'WEBAPP_BUILD_NUMBER = "379"' in vtext:
        version.write_text(vtext.replace('WEBAPP_BUILD_NUMBER = "379"', 'WEBAPP_BUILD_NUMBER = "380"', 1), encoding="utf-8")
    elif 'WEBAPP_BUILD_NUMBER = "380"' not in vtext:
        raise SystemExit("Unexpected web build number; refusing to overwrite")

    history = ROOT / "web/lib/release-history.ts"
    h = history.read_text(encoding="utf-8")
    if "Vaste positieomvang als optionele instapmodus" not in h:
        new_current = """export const CURRENT_RELEASE: ReleaseHistoryEntry = {
  id: __BT__v__DOLLAR__{WEBAPP_VERSION}-build-__DOLLAR__{WEBAPP_BUILD_NUMBER}-release-history__BT__,
  version: WEBAPP_VERSION,
  build: WEBAPP_BUILD_NUMBER,
  releasedAt: "2026-09-20",
  title: "Vaste positieomvang als optionele instapmodus",
  newItems: [
    "Nieuwe schakelaar Vaste positieomvang: instapbedrag kan nu optioneel de werkelijke LONG/SHORT positie in USDT zijn in plaats van margin.",
    "LONG en SHORT bewaren ieder hun eigen positieomvang en de benodigde margin wordt per markt uit de werkelijk gekozen leverage afgeleid.",
    "Opslaan controleert nu expliciet of Maximum leverage en de gekozen sizing-mode server-side zijn bevestigd voordat Niet opgeslagen verdwijnt.",
  ],
  problems: [
    "Bij gelijke margin kregen markten met verschillende leverage verschillende werkelijke positieomvang: $0,30 op 20x is circa $6, terwijl $0,30 op 50x circa $15 is.",
    "Daardoor konden lager-leveraged posities minder PnL-bijdrage leveren ondanks hetzelfde zichtbare instapbedrag.",
    "Een save mocht niet als afgerond ogen wanneer Maximum leverage of sizing-mode niet uit de serverbevestiging terugkwam.",
  ],
  causes: [
    "Build 379 stuurde de compacte LONG/SHORT instapvelden expliciet als entrySizingMode=margin.",
    "Margin is kapitaalbeslag; notional is de werkelijke positieomvang. Bij margin-sizing groeit notional daarom mee met leverage.",
  ],
  fixes: [
    "Vaste positieomvang AAN gebruikt de bestaande server-authoritative notional resolver: planned notional blijft gelijk en required margin = notional / leverage.",
    "Vaste positieomvang UIT behoudt het bestaande margin-gedrag volledig backward-compatible.",
    "Side-specific entryNotionalLongUsd en entryNotionalShortUsd zijn toegevoegd en worden door oudere settings-editors beschermd.",
    "Smart Rescue leidt bij notional-sizing zijn startmargin af uit de werkelijke entry leverage.",
  ],
  now: [
    "Voor een ingestelde positie van $6 gebruikt 20x circa $0,30 margin, 50x circa $0,12 en 100x circa $0,06, terwijl de geplande positie circa $6 blijft.",
    "Minimum en Maximum leverage blijven leveragefilters/caps; ze veranderen bij Vaste positieomvang niet het gekozen positiebedrag.",
    "De gebruiker kan per account kiezen tussen vaste positieomvang en het bestaande vaste-margin gedrag.",
  ],
  before: "Het compacte instapveld van build 379 betekende altijd margin, waardoor dezelfde $0,30 bij verschillende leverage een andere werkelijke positieomvang gaf.",
  after: "Een expliciete schakelaar bepaalt of het instapbedrag margin of werkelijke positieomvang is; beide modi blijven beschikbaar.",
  technicalDetails: [
    "Veilige simulatie blijft orderloos en toont de sizing-mode plus het 6-USDT voorbeeld voor 20x/50x/100x.",
    "Backend en web hebben regressiedekking voor side-specific notional, Maximum leverage, save-persistentie en Smart Rescue startmargin.",
  ],
  confidence: "confirmed",
};

const HISTORICAL_RELEASES: ReleaseHistoryEntry[] = [
  {
    id: "v46-build-379-compact-settings-maxlev-stoploss",
    version: "46",
    build: "379",
    releasedAt: "2026-09-20",
    title: "Compacte Botinstellingen met Maximum leverage en Stoploss",
    newItems: ["Compact premium Botinstellingen, optionele Maximum leverage en server-side Stoploss."],
    problems: ["Botinstellingen waren te ruim en leverage had nog geen optionele bovengrens."],
    causes: ["Bestaande UI en leverage-resolver waren voor de nieuwe compacte instellingen nog niet samengebracht."],
    fixes: ["Slot-overzicht, Maximum leverage en Stoploss zijn toegevoegd zonder bestaande posities te resetten."],
    now: ["Dit is de directe voorganger van build 380."],
    confidence: "confirmed",
  },
"""
        new_current = new_current.replace("__BT__", chr(96)).replace("__DOLLAR__", "$")
        pattern = re.compile(r'export const CURRENT_RELEASE: ReleaseHistoryEntry = \{.*?\n\};\n\nconst HISTORICAL_RELEASES: ReleaseHistoryEntry\[] = \[\n', re.S)
        if not pattern.search(h):
            raise SystemExit("Current release block not found")
        h = pattern.sub(new_current, h, count=1)
        history.write_text(h, encoding="utf-8")


if __name__ == "__main__":
    main()
