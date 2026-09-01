from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"expected block not found in {path}: {old[:140]!r}")
    p.write_text(text.replace(old, new, 1))

# 1) Expose the new account-wide risk fields all the way through the public Aster status payload.
replace_once(
    "cloud_api/main.py",
    '        "maintenanceMargin": confirmed_snapshot_number("maintenanceMargin"),\n        "marginRatio": confirmed_snapshot_number("marginRatio"),\n',
    '        "maintenanceMargin": confirmed_snapshot_number("maintenanceMargin"),\n'
    '        "maintenanceMarginPct": confirmed_snapshot_number("maintenanceMarginPct"),\n'
    '        "liquidationRiskPct": confirmed_snapshot_number("liquidationRiskPct"),\n'
    '        "liquidationRiskSource": str(snapshot.get("liquidationRiskSource", "")),\n'
    '        "marginBalance": confirmed_snapshot_number("marginBalance"),\n'
    '        "totalUnrealizedPnl": confirmed_snapshot_number("totalUnrealizedPnl"),\n'
    '        "totalCrossNotional": confirmed_snapshot_number("totalCrossNotional"),\n'
    '        "longNotional": confirmed_snapshot_number("longNotional"),\n'
    '        "shortNotional": confirmed_snapshot_number("shortNotional"),\n'
    '        "netExposure": confirmed_snapshot_number("netExposure"),\n'
    '        "grossExposure": confirmed_snapshot_number("grossExposure"),\n'
    '        "positionCountIncluded": int(safe_float(snapshot.get("positionCountIncluded"))),\n'
    '        "marginRatio": confirmed_snapshot_number("marginRatio"),\n'
)

# 2) For Aster, remove the maintenance orbit entirely. Keep only the important liquidation meter.
replace_once(
    "web/app/page.tsx",
    '''        <div className={destination === "aster" ? "risk-orbits" : undefined}>\n          <div className={`risk-orbit risk-${view.riskTone}`} aria-label={view.riskLabel}>\n            <div className="orbit-lines" />\n            <div className="risk-core"><span>{view.riskLabel}</span><strong>{view.riskValue}</strong><small>{view.riskDetail}</small></div>\n          </div>\n          {destination === "aster" && <LiquidationRiskOrbit display={view.asterAccountDisplay} />}\n        </div>\n''',
    '''        {destination === "aster" ? <div className="risk-orbits liquidation-only"><LiquidationRiskOrbit display={view.asterAccountDisplay} /></div> : <div><div className={`risk-orbit risk-${view.riskTone}`} aria-label={view.riskLabel}><div className="orbit-lines" /><div className="risk-core"><span>{view.riskLabel}</span><strong>{view.riskValue}</strong><small>{view.riskDetail}</small></div></div></div>}\n''',
)

# Remove the separate Aster maintenance tile too; available-to-trade already communicates free capital.
replace_once(
    "web/app/page.tsx",
    '        {(isHyperliquid || destination === "aster") && <Metric label="MAINTENANCE MARGIN" value={view.maintenanceMargin} detail={destination === "aster" ? "Aster futures maintenance margin" : "Perps maintenance margin"} />}\n',
    '        {isHyperliquid && <Metric label="MAINTENANCE MARGIN" value={view.maintenanceMargin} detail="Perps maintenance margin" />}\n',
)

# 3) Make the single remaining meter minimal: label, value, one short health word.
old = '''function LiquidationRiskOrbit({ display }: { display: AsterAccountDisplay | null }) {\n  const tone = display?.liquidationTone ?? "unknown";\n  const available = display?.liquidationRiskPercent !== null && display?.liquidationRiskPercent !== undefined;\n  return <div className={`risk-orbit liquidation-risk risk-${tone}`} aria-label="LIQUIDATIERISICO"><div className="orbit-lines" /><div className="risk-core"><span>LIQUIDATIERISICO</span><strong className={available ? "" : "unavailable"}>{display?.liquidationValue ?? "—"}</strong><small>{display?.liquidationDetail ?? "Geen bevestigde cross-account liquidatieratio"}{display?.positionCountIncluded !== null && display?.positionCountIncluded !== undefined ? ` · ${display.positionCountIncluded} posities` : ""}</small></div></div>;\n}\n'''
new = '''function LiquidationRiskOrbit({ display }: { display: AsterAccountDisplay | null }) {\n  const tone = display?.liquidationTone ?? "unknown";\n  const available = display?.liquidationRiskPercent !== null && display?.liquidationRiskPercent !== undefined;\n  const health = tone === "safe" ? "VEILIG" : tone === "caution" ? "VERHOOGD" : tone === "high" ? "HOOG" : tone === "critical" ? "KRITIEK" : "GEEN DATA";\n  return <div className={`risk-orbit liquidation-risk risk-${tone}`} aria-label={`LIQUIDATIERISICO ${display?.liquidationValue ?? "onbekend"}`} title={display?.liquidationDetail ?? "Geen bevestigde cross-account liquidatieratio"}><div className="orbit-lines" /><div className="risk-core"><span>LIQUIDATIERISICO</span><strong className={available ? "" : "unavailable"}>{display?.liquidationValue ?? "—"}</strong><small>{health}</small></div></div>;\n}\n'''
replace_once("web/app/page.tsx", old, new)

# 4) Tiny single-orbit visual override. Roughly half the previous mobile diameter.
css = Path("web/app/globals.css")
style = '''\n\n/* Aster liquidation-only cockpit: one small high-priority money-health gauge. */\n.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only{display:flex;justify-content:center;align-items:center;width:auto;min-width:0}\n.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only .risk-orbit{width:92px;height:92px;min-width:92px;min-height:92px;transform:none}\n.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only .risk-core{width:68px}\n.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only .risk-core span{font-size:5.5px;letter-spacing:.06em}\n.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only .risk-core strong{font-size:21px;line-height:1}\n.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only .risk-core strong.unavailable{font-size:16px}\n.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only .risk-core small{max-width:64px;font-size:5.5px;line-height:1.1;font-weight:900;letter-spacing:.08em}\n@media(max-width:640px){.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only{width:100%;justify-content:flex-start}.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only .risk-orbit{width:72px;height:72px;min-width:72px;min-height:72px}.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only .risk-core{width:54px}.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only .risk-core strong{font-size:17px}.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only .risk-core span,.hero-panel:has(.aster-bot-status) .risk-orbits.liquidation-only .risk-core small{font-size:4.6px;max-width:52px}}\n'''
if "Aster liquidation-only cockpit" not in css.read_text():
    css.write_text(css.read_text() + style)

# 5) Regression tests: public data path plus one tiny liquidation-only Aster gauge.
Path("web/tests/aster-cross-liquidation-meter.test.mjs").write_text('''import test from "node:test";\nimport assert from "node:assert/strict";\nimport { readFileSync } from "node:fs";\n\nconst account = readFileSync(new URL("../lib/aster-account-display.ts", import.meta.url), "utf8");\nconst page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");\nconst css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");\nconst backend = readFileSync(new URL("../../cloud_api/main.py", import.meta.url), "utf8");\n\ntest("Aster public status exposes the cross-account liquidation fields consumed by the browser", () => {\n  for (const field of ["maintenanceMarginPct","liquidationRiskPct","liquidationRiskSource","marginBalance","totalCrossNotional","longNotional","shortNotional","netExposure","grossExposure","positionCountIncluded"]) assert.ok(backend.includes(`"${field}"`), `${field} missing from public Aster status projection`);\n  assert.match(account, /data\\?\\.liquidationRiskPct/);\n  assert.match(account, /liquidationRiskSource/);\n  assert.doesNotMatch(account, /data\\?\\.marginRatio/);\n});\n\ntest("Aster hero has one liquidation meter and no maintenance meter", () => {\n  assert.match(page, /risk-orbits liquidation-only/);\n  assert.match(page, /function LiquidationRiskOrbit/);\n  assert.match(page, /liquidation-risk/);\n  assert.match(page, /VEILIG/);\n  assert.doesNotMatch(page, /isHyperliquid \\|\\| destination === "aster"/);\n});\n\ntest("the remaining liquidation gauge is about half the previous mobile size", () => {\n  assert.match(css, /Aster liquidation-only cockpit/);\n  assert.match(css, /width:92px;height:92px/);\n  assert.match(css, /width:72px;height:72px/);\n});\n''')

# Keep the older liquidation contract test aligned with the new single-orbit UI.
p = Path("web/tests/liquidation-risk.test.mjs")
text = p.read_text()
text = text.replace('test("Aster hero renders distinct server maintenance and account-wide liquidation risk in a mobile two-column grid", async()=>{', 'test("Aster hero renders one compact server account-wide liquidation risk gauge", async()=>{')
text = text.replace('  assert.match(page,/MAINTENANCE MARGIN/);\n', '')
text = text.replace('  assert.match(page,/LIQUIDATIERISICO/);\n', '  assert.match(page,/function LiquidationRiskOrbit/);\n')
text = text.replace('  assert.match(page,/destination === "aster" && <LiquidationRiskOrbit/);\n', '  assert.match(page,/risk-orbits liquidation-only/);\n')
text = text.replace('  assert.match(page,/risk-orbit risk-\\$\\{view\\.riskTone\\}/);\n  assert.match(css,/risk-orbits[^}]*grid-template-columns:repeat\\(2,minmax\\(0,1fr\\)\\)/);\n', '  assert.match(page,/risk-orbits liquidation-only/);\n  assert.match(css,/Aster liquidation-only cockpit/);\n')
p.write_text(text)
