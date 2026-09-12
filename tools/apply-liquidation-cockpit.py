from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "web/components/aster-portfolio-snapshot-enhancer.tsx"
CSS = ROOT / "web/app/portfolio-snapshot.css"
HELPER = ROOT / "web/lib/liquidation-gauge.mjs"
DECL = ROOT / "web/lib/liquidation-gauge.d.ts"
TEST = ROOT / "web/tests/liquidation-cockpit-gauge.test.mjs"
REFERENCE = "file_000000004e80820a80318a3de3ae5abd"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


component = COMPONENT.read_text(encoding="utf-8")

component = replace_once(
    component,
    'import { AsterHedgeManager } from "./aster-hedge-manager";\n',
    'import { AsterHedgeManager } from "./aster-hedge-manager";\nimport { formatLiquidationRisk, liquidationNeedleDegrees, liquidationRiskRemaining, liquidationRiskTone, normalizeLiquidationRisk } from "@/lib/liquidation-gauge.mjs";\n',
    "liquidation helper import",
)

component = replace_once(
    component,
    'const CLOSE_POSITIVE_REFERENCE = "file_000000009fec821084026a5551398488";\n',
    'const CLOSE_POSITIVE_REFERENCE = "file_000000009fec821084026a5551398488";\nconst LIQUIDATION_GAUGE_REFERENCE = "file_000000004e80820a80318a3de3ae5abd";\n\ntype LiquidationDiagnostics = {\n  liquidationRiskPercent: number | null;\n  source: "ASTER_ACCOUNT_RATIO" | "SERVER_RECONSTRUCTED" | "UNKNOWN";\n  marginBalance: number | null;\n  equity: number | null;\n  maintenanceMarginUsd: number | null;\n  longExposureUsd: number | null;\n  shortExposureUsd: number | null;\n  netExposureUsd: number | null;\n};\n',
    "liquidation reference/types",
)

percentage_anchor = '''function percentageTone(value: string): Tone {\n  if (value === "—") return "neutral";\n  const parsed = Number(value.replace("%", "").replace("+", "").replace(",", ".").trim());\n  return Number.isFinite(parsed) && parsed > 0 ? "positive" : Number.isFinite(parsed) && parsed < 0 ? "negative" : "neutral";\n}\n'''
percentage_addition = percentage_anchor + '''\nfunction record(value: unknown): Record<string, unknown> {\n  return value && typeof value === "object" ? value as Record<string, unknown> : {};\n}\n\nfunction optionalNumber(value: unknown) {\n  const parsed = typeof value === "number" ? value : Number(value);\n  return Number.isFinite(parsed) ? parsed : null;\n}\n\nfunction firstNumber(records: Record<string, unknown>[], keys: string[]) {\n  for (const source of records) {\n    for (const key of keys) {\n      const value = optionalNumber(source[key]);\n      if (value !== null) return value;\n    }\n  }\n  return null;\n}\n\nfunction firstString(records: Record<string, unknown>[], keys: string[]) {\n  for (const source of records) {\n    for (const key of keys) {\n      const value = source[key];\n      if (typeof value === "string" && value.trim()) return value.trim();\n    }\n  }\n  return "";\n}\n\nfunction money(value: number | null, fallback = "—") {\n  if (value === null || !Number.isFinite(value)) return fallback;\n  return `US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}`;\n}\n\nasync function loadLiquidationDiagnostics(): Promise<LiquidationDiagnostics> {\n  const payload = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" });\n  const root = record(payload);\n  const records = [root, record(root.data), record(root.account), record(root.snapshot), record(root.accountRisk), record(root.crossRisk), record(root.portfolio)];\n  const sourceRaw = firstString(records, ["liquidationRiskSource"]);\n  const source = sourceRaw === "ASTER_ACCOUNT_RATIO" || sourceRaw === "SERVER_RECONSTRUCTED" ? sourceRaw : "UNKNOWN";\n  return {\n    liquidationRiskPercent: firstNumber(records, ["liquidationRiskPct"]),\n    source,\n    marginBalance: firstNumber(records, ["marginBalance", "totalMarginBalance"]),\n    equity: firstNumber(records, ["equity", "totalMarginBalance"]),\n    maintenanceMarginUsd: firstNumber(records, ["maintenanceMarginUsd", "totalMaintMargin"]),\n    longExposureUsd: firstNumber(records, ["longNotional", "longExposureUsd"]),\n    shortExposureUsd: firstNumber(records, ["shortNotional", "shortExposureUsd"]),\n    netExposureUsd: firstNumber(records, ["netExposure", "netExposureUsd"]),\n  };\n}\n'''
component = replace_once(component, percentage_anchor, percentage_addition, "diagnostic helpers")

# Add the premium flip gauge directly after GrowthCard so it remains a pure presentation component.
growth_anchor = '''function GrowthCard({ icon, label, value, tone }: { icon: "growth" | "calendar"; label: string; value: string; tone: Tone }) {\n  return <article className={`aps-growth-card aps-${tone}`}><span className="aps-icon"><Icon name={icon} /></span><div><small>{label}</small><strong>{value}</strong></div></article>;\n}\n'''
gauge_component = growth_anchor + r'''

function LiquidationGauge({ value, diagnostics, exposure, equity, available }: {
  value: string;
  diagnostics: LiquidationDiagnostics | null;
  exposure: ExposureSnapshot | null | undefined;
  equity: string;
  available: string;
}) {
  const [flipped, setFlipped] = useState(false);
  const risk = normalizeLiquidationRisk(value);
  const degrees = liquidationNeedleDegrees(risk);
  const remaining = liquidationRiskRemaining(risk);
  const tone = liquidationRiskTone(risk);
  const display = formatLiquidationRisk(risk);
  const longExposure = exposure?.reliable ? exposure.longExposureUsd : diagnostics?.longExposureUsd ?? null;
  const shortExposure = exposure?.reliable ? exposure.shortExposureUsd : diagnostics?.shortExposureUsd ?? null;
  const netExposure = exposure?.reliable ? exposure.netExposureUsd : diagnostics?.netExposureUsd ?? null;
  const source = diagnostics?.source === "ASTER_ACCOUNT_RATIO" ? "ASTER ACCOUNT RATIO" : diagnostics?.source === "SERVER_RECONSTRUCTED" ? "SERVER RECONSTRUCTED" : "ONBEKEND";
  const marginLabel = diagnostics?.marginBalance !== null && diagnostics?.marginBalance !== undefined
    ? money(diagnostics.marginBalance)
    : diagnostics?.equity !== null && diagnostics?.equity !== undefined
      ? money(diagnostics.equity)
      : equity;

  return <button
    type="button"
    className={`aps-liquidation-gauge aps-gauge-${tone}`}
    data-reference={LIQUIDATION_GAUGE_REFERENCE}
    data-risk-value={risk ?? "unknown"}
    aria-label={`Liquidatierisico ${display}. Tik voor details.`}
    aria-pressed={flipped}
    onClick={() => setFlipped((current) => !current)}
  >
    <span className={`aps-gauge-flipper${flipped ? " is-flipped" : ""}`}>
      <span className="aps-gauge-face aps-gauge-front">
        <span className="aps-gauge-head"><b>LIQUIDATIERISICO</b><em><i />LIVE</em></span>
        <span className="aps-gauge-dial" aria-hidden="true">
          <svg viewBox="0 0 220 126" role="presentation">
            <path className="aps-gauge-track" d="M20 105 A90 90 0 0 1 200 105" pathLength="100" />
            <path className="aps-gauge-arc arc-green" d="M20 105 A90 90 0 0 1 200 105" pathLength="100" />
            <path className="aps-gauge-arc arc-lime" d="M20 105 A90 90 0 0 1 200 105" pathLength="100" />
            <path className="aps-gauge-arc arc-yellow" d="M20 105 A90 90 0 0 1 200 105" pathLength="100" />
            <path className="aps-gauge-arc arc-orange" d="M20 105 A90 90 0 0 1 200 105" pathLength="100" />
            <path className="aps-gauge-arc arc-red" d="M20 105 A90 90 0 0 1 200 105" pathLength="100" />
            <text x="21" y="119">0%</text>
            <text x="54" y="60">25%</text>
            <text x="110" y="39" textAnchor="middle">50%</text>
            <text x="166" y="60" textAnchor="middle">75%</text>
            <text x="199" y="119" textAnchor="end" className="danger">100%</text>
            <g className="aps-gauge-needle" style={{ transform: `rotate(${degrees}deg)`, transformOrigin: "110px 105px" }}>
              <line x1="110" y1="105" x2="37" y2="105" />
              <circle cx="110" cy="105" r="6" />
            </g>
            <circle className="aps-gauge-hub" cx="110" cy="105" r="3.2" />
          </svg>
        </span>
        <strong className="aps-gauge-value">{display}</strong>
        <small className="aps-gauge-caption">100% = liquidatie</small>
      </span>
      <span className="aps-gauge-face aps-gauge-back">
        <span className="aps-gauge-back-head"><b>LIQUIDATIERISICO</b><em>{display}</em></span>
        <span className="aps-gauge-details">
          <span><small>Ruimte tot 100%</small><strong>{remaining === null ? "—" : `${new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 2 }).format(remaining)}%`}</strong></span>
          <span><small>Margin / equity</small><strong>{marginLabel}</strong></span>
          <span><small>Maintenance</small><strong>{money(diagnostics?.maintenanceMarginUsd ?? null)}</strong></span>
          <span><small>Available</small><strong>{available}</strong></span>
          <span><small>Long exposure</small><strong>{money(longExposure)}</strong></span>
          <span><small>Short exposure</small><strong>{money(shortExposure)}</strong></span>
          <span><small>Netto exposure</small><strong>{money(netExposure)}</strong></span>
          <span><small>Actuele ratio</small><strong>{diagnostics?.liquidationRiskPercent === null || diagnostics?.liquidationRiskPercent === undefined ? display : formatLiquidationRisk(diagnostics.liquidationRiskPercent)}</strong></span>
        </span>
        <small className="aps-gauge-source">BRON · {source}</small>
      </span>
    </span>
  </button>;
}
'''
component = replace_once(component, growth_anchor, gauge_component, "gauge component")

snapshot_signature_old = '''function Snapshot({ values, profitPreview, profitBusy, onCloseAll, onCloseProfit, onOpenHedge }: {\n  values: SnapshotValues;\n  profitPreview: ProfitPreview | null;\n  profitBusy: ProfitScope | null;\n  onCloseAll: () => void;\n  onCloseProfit: (scope: ProfitScope) => void;\n  onOpenHedge: () => void;\n}) {'''
snapshot_signature_new = '''function Snapshot({ values, profitPreview, liquidationDiagnostics, profitBusy, onCloseAll, onCloseProfit, onOpenHedge }: {\n  values: SnapshotValues;\n  profitPreview: ProfitPreview | null;\n  liquidationDiagnostics: LiquidationDiagnostics | null;\n  profitBusy: ProfitScope | null;\n  onCloseAll: () => void;\n  onCloseProfit: (scope: ProfitScope) => void;\n  onOpenHedge: () => void;\n}) {'''
component = replace_once(component, snapshot_signature_old, snapshot_signature_new, "snapshot signature")

old_rows = '''    <div className="aps-status-row">\n      <div className="aps-status aps-balance"><Icon name="balance" /><strong><b>{values.longs}L</b><span>/</span><em>{values.shorts}S</em></strong></div>\n      <div className="aps-status"><Icon name="dca" /><strong>{values.dca} DCA</strong></div>\n      <div className={`aps-status aps-risk aps-risk-${values.riskTone}`}><Icon name="shield" /><span><small>LIQUIDATIERISICO</small><strong>{values.liquidation}</strong></span></div>\n    </div>\n    <div className="aps-growth-row">\n      <GrowthCard icon="growth" label="RENDEMENT VANDAAG" value={values.todayGrowth} tone={values.todayGrowthTone} />\n      <GrowthCard icon="calendar" label="GEMIDDELD PER DAG" value={values.averageDailyGrowth} tone={values.averageDailyGrowthTone} />\n    </div>'''
new_rows = '''    <div className="aps-health-grid">\n      <div className="aps-health-left">\n        <div className="aps-status-row">\n          <div className="aps-status aps-balance"><Icon name="balance" /><strong><b>{values.longs}L</b><span>/</span><em>{values.shorts}S</em></strong></div>\n          <div className="aps-status"><Icon name="dca" /><strong>{values.dca} DCA</strong></div>\n        </div>\n        <div className="aps-growth-row">\n          <GrowthCard icon="growth" label="RENDEMENT VANDAAG" value={values.todayGrowth} tone={values.todayGrowthTone} />\n          <GrowthCard icon="calendar" label="GEMIDDELD PER DAG" value={values.averageDailyGrowth} tone={values.averageDailyGrowthTone} />\n        </div>\n      </div>\n      <LiquidationGauge\n        value={values.liquidation}\n        diagnostics={liquidationDiagnostics}\n        exposure={profitPreview?.exposure}\n        equity={values.equity}\n        available={values.available}\n      />\n    </div>'''
component = replace_once(component, old_rows, new_rows, "snapshot risk rows")

component = replace_once(
    component,
    '  const [profitPreview, setProfitPreview] = useState<ProfitPreview | null>(null);\n',
    '  const [profitPreview, setProfitPreview] = useState<ProfitPreview | null>(null);\n  const [liquidationDiagnostics, setLiquidationDiagnostics] = useState<LiquidationDiagnostics | null>(null);\n',
    "diagnostics state",
)

profit_effect_anchor = '''  useEffect(() => {\n    if (!host) return;\n    let alive = true;\n    const refresh = async () => {\n      try {\n        const preview = await loadProfitPreview();\n        if (alive) setProfitPreview(preview);\n      } catch {\n        if (alive) setProfitPreview(null);\n      }\n    };\n    void refresh();\n    const timer = window.setInterval(refresh, 15000);\n    const onVisible = () => { if (document.visibilityState === "visible") void refresh(); };\n    document.addEventListener("visibilitychange", onVisible);\n    return () => {\n      alive = false;\n      window.clearInterval(timer);\n      document.removeEventListener("visibilitychange", onVisible);\n    };\n  }, [host]);\n'''
diagnostic_effect = profit_effect_anchor + '''\n  useEffect(() => {\n    if (!host) return;\n    let alive = true;\n    const refresh = async () => {\n      try {\n        const diagnostics = await loadLiquidationDiagnostics();\n        if (alive) setLiquidationDiagnostics(diagnostics);\n      } catch {\n        if (alive) setLiquidationDiagnostics(null);\n      }\n    };\n    void refresh();\n    const timer = window.setInterval(refresh, 15000);\n    const onVisible = () => { if (document.visibilityState === "visible") void refresh(); };\n    document.addEventListener("visibilitychange", onVisible);\n    return () => {\n      alive = false;\n      window.clearInterval(timer);\n      document.removeEventListener("visibilitychange", onVisible);\n    };\n  }, [host]);\n'''
component = replace_once(component, profit_effect_anchor, diagnostic_effect, "diagnostics refresh effect")

component = replace_once(
    component,
    '        profitPreview={profitPreview}\n        profitBusy={profitBusy}\n',
    '        profitPreview={profitPreview}\n        liquidationDiagnostics={liquidationDiagnostics}\n        profitBusy={profitBusy}\n',
    "snapshot diagnostics prop",
)

COMPONENT.write_text(component, encoding="utf-8")

css = CSS.read_text(encoding="utf-8")
marker = f"/* Liquidation cockpit reference: {REFERENCE} */"
if marker in css:
    raise SystemExit("cockpit CSS already present")
css += r'''

/* Liquidation cockpit reference: file_000000004e80820a80318a3de3ae5abd */
.aps-health-grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(132px,1.25fr);gap:7px;align-items:stretch;margin-top:7px}
.aps-health-left{min-width:0;display:grid;grid-template-rows:auto auto;gap:7px}
.aps-health-left .aps-status-row,.aps-health-left .aps-growth-row{margin-top:0}
.aps-health-left .aps-status-row{grid-template-columns:repeat(2,minmax(0,1fr))}
.aps-health-left .aps-status:last-child{border-right:0}
.aps-liquidation-gauge{min-width:0;min-height:111px;margin:0;padding:0;border:1px solid rgba(80,219,135,.42);border-radius:11px;color:#f8f7f2;background:linear-gradient(150deg,rgba(3,34,21,.96),rgba(1,15,10,.99));box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 0 18px rgba(37,239,145,.07);font:inherit;cursor:pointer;perspective:760px;overflow:hidden;appearance:none;-webkit-tap-highlight-color:transparent}
.aps-liquidation-gauge:focus-visible{outline:2px solid #e8b83d;outline-offset:2px}
.aps-gauge-flipper{position:relative;display:block;width:100%;height:100%;min-height:111px;transform-style:preserve-3d;transition:transform .62s cubic-bezier(.2,.72,.22,1)}
.aps-gauge-flipper.is-flipped{transform:rotateY(180deg)}
.aps-gauge-face{position:absolute;inset:0;display:block;backface-visibility:hidden;-webkit-backface-visibility:hidden}
.aps-gauge-front{padding:7px 7px 5px}
.aps-gauge-head{position:relative;z-index:4;display:flex;align-items:center;justify-content:space-between;gap:5px;color:#d9ab3d;font-size:6.6px;line-height:1;font-weight:950;letter-spacing:.055em;white-space:nowrap}
.aps-gauge-head em{display:flex;align-items:center;gap:3px;color:#33ec99;font-size:5.5px;font-style:normal;letter-spacing:.04em}
.aps-gauge-head em i{width:5px;height:5px;border-radius:50%;background:#28ed91;box-shadow:0 0 7px rgba(40,237,145,.9);animation:aps-live-pulse 1.7s ease-in-out infinite}
@keyframes aps-live-pulse{0%,100%{opacity:.55;transform:scale(.82)}50%{opacity:1;transform:scale(1.15)}}
.aps-gauge-dial{position:absolute;left:3px;right:3px;top:17px;bottom:6px;display:grid;place-items:center}
.aps-gauge-dial svg{display:block;width:100%;height:100%;overflow:visible}
.aps-gauge-track,.aps-gauge-arc{fill:none;stroke-width:12;stroke-linecap:butt}
.aps-gauge-track{stroke:rgba(93,122,103,.18)}
.aps-gauge-arc{stroke-dasharray:20 80}
.aps-gauge-arc.arc-green{stroke:#22e98e;stroke-dashoffset:0;filter:drop-shadow(0 0 4px rgba(34,233,142,.55))}
.aps-gauge-arc.arc-lime{stroke:#82e344;stroke-dashoffset:-20}
.aps-gauge-arc.arc-yellow{stroke:#f4d13c;stroke-dashoffset:-40}
.aps-gauge-arc.arc-orange{stroke:#ff9b31;stroke-dashoffset:-60}
.aps-gauge-arc.arc-red{stroke:#ff465f;stroke-dashoffset:-80;filter:drop-shadow(0 0 3px rgba(255,70,95,.45))}
.aps-gauge-dial text{fill:#d5d9d2;font-size:8px;font-weight:800}.aps-gauge-dial text.danger{fill:#ff5d74}
.aps-gauge-needle{transition:transform .72s cubic-bezier(.19,.78,.18,1);will-change:transform}.aps-gauge-needle line{stroke:#54f1a9;stroke-width:4;stroke-linecap:round;filter:drop-shadow(0 0 4px rgba(48,238,151,.75))}.aps-gauge-needle circle{fill:#1b5a3d;stroke:#51efa7;stroke-width:2}.aps-gauge-hub{fill:#44efa1;filter:drop-shadow(0 0 4px rgba(54,239,158,.85))}
.aps-gauge-value{position:absolute;z-index:5;left:50%;bottom:13px;transform:translateX(-50%);color:#35ee9a;font-size:17px;line-height:1;font-weight:950;letter-spacing:-.035em;text-shadow:0 0 10px rgba(40,238,150,.28);white-space:nowrap}
.aps-gauge-caption{position:absolute;z-index:5;left:0;right:0;bottom:3px;color:#aeb8b0;font-size:5.6px;line-height:1;font-weight:750;letter-spacing:.02em;text-align:center;white-space:nowrap}
.aps-gauge-caution .aps-gauge-value{color:#f3cd44}.aps-gauge-high .aps-gauge-value{color:#ff9a4a}.aps-gauge-critical .aps-gauge-value{color:#ff5b75}.aps-gauge-unknown .aps-gauge-value{color:#89968d}
.aps-gauge-back{padding:6px 7px 5px;transform:rotateY(180deg);background:linear-gradient(155deg,rgba(2,27,17,.99),rgba(1,12,8,.99))}
.aps-gauge-back-head{display:flex;align-items:center;justify-content:space-between;gap:4px;margin-bottom:4px;color:#d9ab3d;font-size:6px;font-weight:950;letter-spacing:.04em}.aps-gauge-back-head em{color:#35ee9a;font-size:9px;font-style:normal;letter-spacing:0}
.aps-gauge-details{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3px}
.aps-gauge-details>span{min-width:0;padding:3px 4px;border:1px solid rgba(74,184,119,.17);border-radius:5px;background:rgba(3,40,24,.45);text-align:left}
.aps-gauge-details small,.aps-gauge-details strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.aps-gauge-details small{color:#aeb8b0;font-size:4.6px;line-height:1.05;font-weight:750}.aps-gauge-details strong{margin-top:2px;color:#f0f2ed;font-size:6.4px;line-height:1.05;font-weight:900}.aps-gauge-source{position:absolute;left:7px;right:7px;bottom:3px;overflow:hidden;color:#7fa38f;font-size:4.6px;font-weight:800;letter-spacing:.04em;text-align:center;text-overflow:ellipsis;white-space:nowrap}
@media(max-width:640px){.aps-health-grid{grid-template-columns:minmax(0,2fr) minmax(112px,1.25fr);gap:5px}.aps-health-left{gap:5px}.aps-health-left .aps-status{min-height:49px}.aps-health-left .aps-growth-card{min-height:52px}.aps-liquidation-gauge,.aps-gauge-flipper{min-height:106px}.aps-gauge-front{padding:6px 5px 4px}.aps-gauge-head{font-size:5.8px}.aps-gauge-head em{font-size:4.8px}.aps-gauge-dial{top:15px;left:1px;right:1px}.aps-gauge-value{bottom:12px;font-size:15px}.aps-gauge-caption{bottom:3px;font-size:5px}.aps-gauge-back{padding:5px}.aps-gauge-details{gap:2px}.aps-gauge-details>span{padding:2px 3px}.aps-gauge-details small{font-size:4.1px}.aps-gauge-details strong{font-size:5.8px}.aps-gauge-source{left:5px;right:5px;font-size:4px}}
@media(max-width:380px){.aps-health-grid{grid-template-columns:minmax(0,1.9fr) minmax(104px,1.2fr);gap:4px}.aps-health-left{gap:4px}.aps-health-left .aps-status{min-height:47px}.aps-health-left .aps-growth-card{min-height:50px}.aps-liquidation-gauge,.aps-gauge-flipper{min-height:101px}.aps-gauge-head{font-size:5.2px}.aps-gauge-head em{font-size:4.3px}.aps-gauge-value{font-size:14px}.aps-gauge-caption{font-size:4.6px}.aps-gauge-details small{font-size:3.8px}.aps-gauge-details strong{font-size:5.3px}}
@media(prefers-reduced-motion:reduce){.aps-gauge-flipper,.aps-gauge-needle{transition:none}.aps-gauge-head em i{animation:none}}
'''
CSS.write_text(css, encoding="utf-8")

HELPER.write_text(r'''export function normalizeLiquidationRisk(value) {
  if (value === null || value === undefined) return null;
  const parsed = typeof value === "number"
    ? value
    : Number(String(value).replace("%", "").replace(",", ".").trim());
  if (!Number.isFinite(parsed)) return null;
  return Math.max(0, Math.min(100, parsed));
}

export function liquidationNeedleDegrees(value) {
  const risk = normalizeLiquidationRisk(value);
  return risk === null ? 0 : risk * 1.8;
}

export function liquidationRiskRemaining(value) {
  const risk = normalizeLiquidationRisk(value);
  return risk === null ? null : Math.max(0, 100 - risk);
}

export function liquidationRiskTone(value) {
  const risk = normalizeLiquidationRisk(value);
  if (risk === null) return "unknown";
  if (risk < 25) return "safe";
  if (risk < 50) return "caution";
  if (risk < 75) return "high";
  return "critical";
}

export function formatLiquidationRisk(value) {
  const risk = normalizeLiquidationRisk(value);
  if (risk === null) return "—";
  return `${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: risk % 1 === 0 ? 0 : 2, maximumFractionDigits: 2 }).format(risk)}%`;
}
''', encoding="utf-8")

DECL.write_text('''export function normalizeLiquidationRisk(value: unknown): number | null;\nexport function liquidationNeedleDegrees(value: unknown): number;\nexport function liquidationRiskRemaining(value: unknown): number | null;\nexport function liquidationRiskTone(value: unknown): "safe" | "caution" | "high" | "critical" | "unknown";\nexport function formatLiquidationRisk(value: unknown): string;\n''', encoding="utf-8")

TEST.write_text(r'''import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { formatLiquidationRisk, liquidationNeedleDegrees, liquidationRiskRemaining, liquidationRiskTone, normalizeLiquidationRisk } from "../lib/liquidation-gauge.mjs";

const explicit = [0, 4.7, 25, 50, 75, 95, 99.9, 100];

test("liquidation cockpit maps the requested 0-100 scale without inventing another score", () => {
  for (const value of explicit) assert.equal(normalizeLiquidationRisk(value), value);
  assert.equal(normalizeLiquidationRisk("4,70%"), 4.7);
  assert.equal(normalizeLiquidationRisk(null), null);
  assert.equal(normalizeLiquidationRisk("—"), null);
  assert.equal(normalizeLiquidationRisk(-5), 0);
  assert.equal(normalizeLiquidationRisk(120), 100);
  assert.equal(liquidationNeedleDegrees(0), 0);
  assert.equal(liquidationNeedleDegrees(50), 90);
  assert.equal(liquidationNeedleDegrees(100), 180);
  assert.equal(liquidationRiskRemaining(4.7), 95.3);
});

test("risk zones remain green to red with 100 percent as liquidation boundary", () => {
  assert.equal(liquidationRiskTone(4.7), "safe");
  assert.equal(liquidationRiskTone(25), "caution");
  assert.equal(liquidationRiskTone(50), "high");
  assert.equal(liquidationRiskTone(75), "critical");
  assert.equal(formatLiquidationRisk(4.7), "4,70%");
  assert.equal(formatLiquidationRisk(100), "100%");
});

test("requested live simulation produces deterministic needle movement", () => {
  const sequence = [4.7, 5.1, 6.4, 8.0, 6.2, 4.9];
  const degrees = sequence.map(liquidationNeedleDegrees);
  assert.deepEqual(degrees, [8.46, 9.18, 11.52, 14.4, 11.16, 8.82]);
  assert.ok(degrees[3] > degrees[0]);
  assert.ok(degrees[5] < degrees[3]);
});

test("portfolio snapshot contains one premium gauge and preserves surrounding controls", () => {
  const component = fs.readFileSync(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");
  const css = fs.readFileSync(new URL("../app/portfolio-snapshot.css", import.meta.url), "utf8");
  assert.match(component, /file_000000004e80820a80318a3de3ae5abd/);
  assert.match(component, /className="aps-health-grid"/);
  assert.match(component, /<LiquidationGauge/);
  assert.doesNotMatch(component, /aps-status aps-risk/);
  for (const label of ["PORTFOLIOWAARDE", "AVAILABLE TO TRADE", "ACTIEF TRADE CAPITAL", "ACTIEVE POSITIES", "GESLOTEN RESULTAAT", "TRADES GESLOTEN", "Close Long", "Close Short", "Close All"]) assert.ok(component.includes(label), label);
  assert.match(css, /\.aps-gauge-flipper\.is-flipped\{transform:rotateY\(180deg\)\}/);
  assert.match(css, /transition:transform \.72s/);
  assert.match(css, /@media\(max-width:640px\)/);
  assert.match(css, /@media\(max-width:380px\)/);
});
''', encoding="utf-8")

print("Applied liquidation cockpit gauge patch using reference", REFERENCE)
