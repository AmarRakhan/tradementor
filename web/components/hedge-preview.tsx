"use client";

import { useEffect, useMemo, useState } from "react";
import { adviseSettings, adviseStake, simulate } from "@/lib/hedge-preview.mjs";

// Build 651 (Amar 24-10): live voorbeeld onder de afbouw-instellingen + advies (inleg <-> instellingen).
// Alleen uitleg: niets wordt opgeslagen tot de gebruiker in de afbouwkaart op Opslaan drukt.

type Dist = "EQUAL" | "ASCENDING" | "STEEP";
export type PreviewSettings = { steps: number; totalPct: number; distribution: Dist; rebuySteps: number; rehedgePct: number; safetyNetPct: number };
type Scenario = "RECOVER" | "FALL" | "CHOP";
type Goal = "SAFE" | "BALANCE" | "PROFIT";

const SCENARIOS: { key: Scenario; label: string }[] = [
  { key: "RECOVER", label: "Daalt en herstelt" }, { key: "FALL", label: "Blijft dalen" }, { key: "CHOP", label: "Schommelt" },
];
const GOALS: { key: Goal; label: string; sub: string }[] = [
  { key: "SAFE", label: "Veilig", sub: "veel terug-hedgen" },
  { key: "BALANCE", label: "Balans", sub: "aanbevolen" },
  { key: "PROFIT", label: "Meer winst", sub: "grote stap diep" },
];
const DIST_LABEL: Record<Dist, string> = { EQUAL: "Gelijk", ASCENDING: "Oplopend", STEEP: "Sterk oplopend" };
const money = (n: number) => `$${n.toLocaleString("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const num = (n: number, d = 1) => n.toLocaleString("nl-NL", { maximumFractionDigits: d });

function readStored(key: string, fallback: string) {
  try { return window.localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function store(key: string, value: string) {
  try { window.localStorage.setItem(key, value); } catch { /* preview only */ }
}

export function HedgePreview({ settings, maxHedgePct = 100, hedgeSide = "SHORT", onApply }: {
  settings: PreviewSettings | null;
  maxHedgePct?: number;
  hedgeSide?: "SHORT" | "LONG";
  onApply: (next: PreviewSettings) => void;
}) {
  const up = hedgeSide === "LONG";
  const protectedSide = up ? "SHORT" : "LONG";
  const [scenario, setScenario] = useState<Scenario>("RECOVER");
  const [tab, setTab] = useState<"STAKE" | "SETTINGS">("STAKE");
  const [goal, setGoal] = useState<Goal>("BALANCE");
  const [stake, setStake] = useState("1");
  const [leverage, setLeverage] = useState("20");
  useEffect(() => { setStake(readStored("hp-stake", "1")); setLeverage(readStored("hp-leverage", "20")); }, []);
  const stakeN = Number(String(stake).replace(",", "."));
  const levN = Math.round(Number(String(leverage).replace(",", ".")));
  const inputsOk = Number.isFinite(stakeN) && stakeN > 0 && Number.isFinite(levN) && levN >= 1 && levN <= 125;

  const sim = useMemo(() => (settings ? simulate(settings, scenario, { maxHedgePct, side: hedgeSide }) : null),
    [settings, scenario, maxHedgePct, hedgeSide]);
  const stakeAdvice = useMemo(() => (settings && inputsOk ? adviseStake({ ...settings, leverage: levN, maxHedgePct, stake: stakeN }) : null),
    [settings, inputsOk, levN, maxHedgePct, stakeN]);
  const settingsAdvice = useMemo(() => (inputsOk ? adviseSettings({ stake: stakeN, leverage: levN, maxHedgePct, totalPct: settings?.totalPct ?? 10, goal }) : null),
    [inputsOk, stakeN, levN, maxHedgePct, settings?.totalPct, goal]);

  if (!settings || !sim) return null;
  const pts = sim.points;
  const prices = pts.map((p) => p.price);
  const lo = Math.min(...prices), hi = Math.max(...prices);
  const W = 360, top = 14, ph = 120, bh = 70, gap = 26;
  const x = (i: number) => 30 + (i * (W - 40)) / Math.max(1, pts.length - 1);
  const y = (p: number) => top + ((hi - p) / Math.max(1e-9, hi - lo)) * ph;
  const maxNet = Math.max(10, ...pts.map((p) => p.net));
  const barTop = top + ph + gap;
  const zone = pts.map((p, i) => ({ i, on: Math.abs(p.net - sim.maxNet) < 1e-9 })).filter((z) => z.on);
  const zx0 = zone.length ? x(zone[0].i) - 8 : 0, zx1 = zone.length ? x(zone[zone.length - 1].i) + 8 : 0;
  const base = 10 * (maxHedgePct / 100);

  return <div className="hp">
    <div className="hp-head"><b>Voorbeeld met jouw instellingen</b><span className="hp-live">LIVE</span></div>
    <div className="hp-tabs" role="tablist">
      {SCENARIOS.map((s) => <button key={s.key} type="button" role="tab" aria-selected={scenario === s.key}
        className={scenario === s.key ? "on" : ""} onClick={() => setScenario(s.key)}>{s.label}</button>)}
    </div>
    <svg className="hp-chart" viewBox={`0 0 ${W} ${barTop + bh + 18}`} role="img"
      aria-label={`Voorbeeld: koers en netto ${protectedSide} per stap`}>
      {zone.length > 0 && <rect x={zx0} y={2} width={Math.max(0, zx1 - zx0)} height={ph + top} className="hp-zone" />}
      {zone.length > 0 && <text x={(zx0 + zx1) / 2} y={11} className="hp-zone-t" textAnchor="middle">max exposure</text>}
      {[hi, (hi + lo) / 2, lo].map((p, i) => <g key={i}><line x1={28} x2={W} y1={y(p)} y2={y(p)} className="hp-grid" />
        <text x={24} y={y(p) + 3} className="hp-axis" textAnchor="end">{num(p, 1)}</text></g>)}
      <polyline className="hp-line" points={pts.map((p, i) => `${x(i)},${y(p.price)}`).join(" ")} />
      {pts.map((p, i) => p.events.map((e, j) => <circle key={`${i}-${j}`} cx={x(i)} cy={y(p.price)}
        r={3 + Math.min(7, (Math.abs(e.qty) / Math.max(0.01, base)) * 14)}
        className={e.type === "SELL" ? "hp-sell" : e.type === "REBUY" ? "hp-rebuy" : "hp-stop"} />))}
      <text x={30} y={barTop - 8} className="hp-axis-l">Netto {protectedSide}</text>
      <line x1={28} x2={W} y1={barTop + bh} y2={barTop + bh} className="hp-base" />
      {pts.map((p, i) => <rect key={i} x={x(i) - 5} width={10} y={barTop + bh - (Math.max(0, p.net) / maxNet) * bh}
        height={(Math.max(0, p.net) / maxNet) * bh} rx={2}
        className={Math.abs(p.net - sim.maxNet) < 1e-9 ? "hp-bar-max" : p.events.some((e) => e.type === "REBUY") || i > (zone[zone.length - 1]?.i ?? 1e9) ? "hp-bar-up" : "hp-bar"} />)}
    </svg>
    <div className="hp-legend"><span><i className="s" />{hedgeSide} verkopen</span><span><i className="r" />{hedgeSide} terugzetten</span><span><i className="m" />volle {protectedSide}</span>{sim.noodrem != null && <span><i className="n" />noodrem</span>}</div>
    <div className="hp-kpi">
      <div><small>Max exposure</small><b className="y">{num((sim.maxNet / 10) * 100, 0)}%</b><small>{num(sim.maxNetFrom, 1)}–{num(sim.maxNetTo, 1)}</small></div>
      <div><small>Resultaat dit scenario</small><b className={sim.result >= 0 ? "g" : "r"}>{sim.result >= 0 ? "+" : "−"}${num(Math.abs(sim.result), 0)}</b><small>vaste hedge: {sim.fixed >= 0 ? "+" : "−"}${num(Math.abs(sim.fixed), 0)}</small></div>
      <div><small>Noodrem</small><b className="r">{num(sim.noodremAt, 1)}</b><small>weer {num(settings.rehedgePct * maxHedgePct / 100, 0)}% hedge</small></div>
    </div>
    <p className="hp-cap">Voorbeeld met {protectedSide} 10 en hedge op 100. Rekenvoorbeeld zonder fees en funding, geen garantie.</p>

    <div className="hp-adv">
      <div className="hp-adv-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "STAKE"} className={tab === "STAKE" ? "on" : ""} onClick={() => setTab("STAKE")}>Inleg voor mijn instellingen</button>
        <button type="button" role="tab" aria-selected={tab === "SETTINGS"} className={tab === "SETTINGS" ? "on" : ""} onClick={() => setTab("SETTINGS")}>Instellingen voor mijn inleg</button>
      </div>
      <div className="hp-in">
        <label><small>Inleg per trade</small><span><b>$</b><input aria-label="Inleg per trade" inputMode="decimal" value={stake}
          onChange={(e) => { setStake(e.target.value); store("hp-stake", e.target.value); }} /></span></label>
        <label><small>Hefboom</small><span><b>×</b><input aria-label="Hefboom" inputMode="numeric" value={leverage}
          onChange={(e) => { setLeverage(e.target.value); store("hp-leverage", e.target.value); }} /></span></label>
      </div>
      {!inputsOk ? <p className="hp-warn">Vul een inleg boven $0 en een hefboom van 1 t/m 125 in.</p> : tab === "STAKE" && stakeAdvice ? <>
        <div className="hp-big">{money(stakeAdvice.recommended)} <small>voor {settings.steps} stappen {DIST_LABEL[settings.distribution].toLowerCase()} · {levN}x</small></div>
        <p className="hp-p">Dan past elke afbouwstap boven het Aster-minimum ($5), ook op de laagste stap.</p>
        <table className="hp-table"><tbody>
          <tr className={stakeAdvice.current === settings.steps ? "ok" : "now"}><td>Jouw inleg {money(stakeN)} × {levN} = ${num(stakeN * levN, 0)} positie</td>
            <td>{stakeAdvice.current === 0 ? "te klein" : `${stakeAdvice.current} stap${stakeAdvice.current === 1 ? "" : "pen"}`}</td></tr>
          {stakeAdvice.rows.filter((r) => r.parts >= 2).map((r) => <tr key={r.parts}><td>{money(r.stake)} inleg</td><td>{r.parts} stappen{r.parts === settings.steps ? " ✓" : ""}</td></tr>)}
        </tbody></table>
        {settings.distribution !== "EQUAL" && <p className="hp-note">Met Verdeling "Gelijk" zijn {settings.steps} stappen al mogelijk vanaf {money(stakeAdvice.equalAll)}.</p>}
        <p className="hp-note">Je inleg pas je zelf aan in Botinstellingen.</p>
      </> : settingsAdvice && <>
        <p className="hp-q">Wat vind je belangrijk?</p>
        <div className="hp-goals">{GOALS.map((g) => <button key={g.key} type="button" className={goal === g.key ? "on" : ""}
          onClick={() => setGoal(g.key)}><b>{g.label}</b><small>{g.sub}</small></button>)}</div>
        {!settingsAdvice.ok ? <p className="hp-warn">{settingsAdvice.reason}</p> : <div className="hp-res">
          <h4>Advies: {GOALS.find((g) => g.key === goal)?.label}</h4>
          <small>Past bij {money(stakeN)} inleg · alle orders boven het Aster-minimum</small>
          <dl>
            <div><dt>Afbouwen</dt><dd>{num(settingsAdvice.settings.totalPct)}% in {settingsAdvice.settings.steps} stap{settingsAdvice.settings.steps === 1 ? "" : "pen"}</dd></div>
            <div><dt>Verdeling</dt><dd>{DIST_LABEL[settingsAdvice.settings.distribution as Dist]}</dd></div>
            <div><dt>Terugkopen na</dt><dd>{settingsAdvice.settings.rebuySteps} stap{settingsAdvice.settings.rebuySteps === 1 ? "" : "pen"}</dd></div>
            <div><dt>Terughedgen</dt><dd>{settingsAdvice.settings.rehedgePct}%</dd></div>
            <div><dt>Noodrem</dt><dd>na {num(settingsAdvice.settings.safetyNetPct)}% extra {up ? "stijging" : "daling"}</dd></div>
          </dl>
          <p className="hp-ok">✓ Kleinste stap ±{money(settingsAdvice.smallestUsd)}{settingsAdvice.settings.rehedgePct < 100 ? ` · terugzetten ${money(settingsAdvice.backUsd)}${settingsAdvice.backFits ? "" : " (onder minimum: hele deel terug)"}` : ""}</p>
          <button type="button" className="hp-apply" onClick={() => onApply(settingsAdvice.settings as PreviewSettings)}>Neem deze instellingen over</button>
          <p className="hp-note">Wordt ingevuld in de afbouwkaart · jij drukt zelf op Opslaan</p>
        </div>}
      </>}
    </div>
  </div>;
}
