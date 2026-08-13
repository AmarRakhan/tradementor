"use client";

import { useEffect, useMemo, useState } from "react";
import type { ExchangeSnapshots } from "@/lib/use-exchange-data";

type Range = "1H" | "4H" | "24H" | "7D" | "30D" | "90D" | "ALL";
type RiskPoint = {
  id: string; at: number; score: number; confidence: number; equity: number;
  marginRatio: number; gross: number; net: number; long: number; short: number;
  openPnl: number; active: number; leverage: number; concentration: number; dca: number;
  exchange: "all" | "hyperliquid" | "aster"; reasons: string[];
};

const STORAGE_KEY = "tradementor.test.riskTimeline.v1";
const ranges: Array<{ id: Range; ms: number }> = [
  { id: "1H", ms: 3_600_000 }, { id: "4H", ms: 14_400_000 },
  { id: "24H", ms: 86_400_000 }, { id: "7D", ms: 604_800_000 },
  { id: "30D", ms: 2_592_000_000 }, { id: "90D", ms: 7_776_000_000 },
  { id: "ALL", ms: Number.POSITIVE_INFINITY },
];

export function RiskTimeline({ snapshots }: { snapshots: ExchangeSnapshots }) {
  const [range, setRange] = useState<Range>("24H");
  const [scope, setScope] = useState<"all" | "hyperliquid" | "aster">("all");
  const [history, setHistory] = useState<RiskPoint[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [simExposure, setSimExposure] = useState(100);
  const [simLeverage, setSimLeverage] = useState(100);
  const [safeMaintenanceLimit, setSafeMaintenanceLimit] = useState(35);
  const configuredEntry = useMemo(() => asterBaseNotional(snapshots), [snapshots.aster.data]);
  const [entryNotional, setEntryNotional] = useState(20);

  useEffect(() => { if (configuredEntry > 0) setEntryNotional(configuredEntry); }, [configuredEntry]);

  const current = useMemo(() => calculateRisk(snapshots, scope, history), [snapshots, scope, history]);

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      if (Array.isArray(saved)) setHistory(saved.filter(validPoint).slice(-5000));
    } catch { /* A corrupt local cache must never block current exchange data. */ }
  }, []);

  useEffect(() => {
    if (!current || current.confidence < 35) return;
    setHistory((existing) => {
      const latest = existing[existing.length - 1];
      if (latest && latest.exchange === current.exchange && current.at - latest.at < 10_000) return existing;
      const next = [...existing, current].slice(-5000);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, [current?.at, current?.score, current?.equity, current?.marginRatio, current?.gross, current?.exchange]);

  const visible = useMemo(() => {
    const duration = ranges.find((item) => item.id === range)?.ms ?? 86_400_000;
    const cutoff = Date.now() - duration;
    return history.filter((point) => point.exchange === scope && point.at >= cutoff);
  }, [history, range, scope]);
  const selected = visible.find((point) => point.id === selectedId) || visible[visible.length - 1] || current;
  const simulated = selected ? simulate(selected, simExposure, simLeverage) : null;
  const capacity = selected ? estimatePositionCapacity(selected, safeMaintenanceLimit, entryNotional, configuredEntry) : null;

  return <section className="risk-center" aria-labelledby="risk-title">
    <header className="risk-heading">
      <div><span>PORTFOLIO RISK TIMELINE</span><h1 id="risk-title">Zie risico voordat het pijn doet</h1><p>De score van 0–100 combineert meerdere risicofactoren en is dus geen marginpercentage. De maintenance-waarde van de exchange blijft leidend voor direct liquidatierisico. Dit scherm kan geen orders plaatsen of instellingen wijzigen.</p></div>
      <RiskBadge point={current} />
    </header>

    <div className="risk-controls">
      <div className="risk-segments" aria-label="Exchange kiezen">
        {(["all", "hyperliquid", "aster"] as const).map((item) => <button key={item} className={scope === item ? "active" : ""} type="button" onClick={() => { setScope(item); setSelectedId(""); }}>{item === "all" ? "Totaal" : item === "hyperliquid" ? "Hyperliquid" : "Aster"}</button>)}
      </div>
      <div className="risk-ranges" aria-label="Tijdsperiode kiezen">
        {ranges.map((item) => <button key={item.id} className={range === item.id ? "active" : ""} type="button" onClick={() => setRange(item.id)}>{item.id}</button>)}
      </div>
    </div>

    <div className="risk-main-grid">
      <article className="risk-chart-card">
        <div className="risk-chart-title"><div><span>RISICOSCORE DOOR DE TIJD</span><strong>{visible.length ? `${visible.length} betrouwbare metingen` : "Historie wordt vanaf nu opgebouwd"}</strong></div><small>0 laag · 100 kritiek</small></div>
        <RiskChart points={visible} selectedId={selected?.id || ""} onSelect={setSelectedId} />
        <div className="risk-legend"><span className="low">Laag</span><span className="raised">Verhoogd</span><span className="high">Hoog</span><span className="critical">Kritiek</span></div>
      </article>

      <article className="risk-explanation">
        <span className="risk-panel-kicker">GESELECTEERD MOMENT</span>
        {selected ? <>
          <div className="risk-score-line"><strong>{selected.score}</strong><div><b>{riskLabel(selected.score)}</b><small>{new Date(selected.at).toLocaleString("nl-NL")} · betrouwbaarheid {selected.confidence}%</small></div></div>
          <p className="risk-summary">{summary(selected)}</p>
          <div className="risk-facts"><RiskFact label="Equity" value={usd(selected.equity)} /><RiskFact label="Marginratio" value={`${selected.marginRatio.toFixed(2)}%`} /><RiskFact label="Gross exposure" value={usd(selected.gross)} /><RiskFact label="Net exposure" value={signedUsd(selected.net)} /></div>
          <h3>Waarom deze score?</h3>
          <ol className="risk-reasons">{selected.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ol>
        </> : <div className="risk-empty"><strong>Nog geen betrouwbare meting</strong><p>Koppel of vernieuw een exchange. Ontbrekende waarden worden nooit als nul geïnterpreteerd.</p></div>}
      </article>
    </div>

    {selected && <article className="risk-capacity-card">
      <div className="risk-card-title"><div><span>POSITIECAPACITEIT OP BASIS VAN MAINTENANCE</span><h2>Hoeveel posities passen bij jouw gekozen risico?</h2></div><small>Live schatting · geen ordertoestemming</small></div>
      <div className="risk-capacity-intro"><p>De schatting gebruikt actuele Aster-maintenance, equity, echte posities, gemiddelde exposure, leverage, DCA, open verlies en LONG/SHORT-onbalans. De bandbreedte vangt marktbeweging en contractverschillen op.</p><div className="risk-capacity-controls"><label className="risk-capacity-slider"><span>Gewenst risiconiveau <b>{capacityRiskLabel(safeMaintenanceLimit)}</b></span><strong>{safeMaintenanceLimit}% maintenance</strong><input aria-label="Gewenste maintenancegrens" type="range" min="15" max="80" step="1" value={safeMaintenanceLimit} onChange={(event) => setSafeMaintenanceLimit(Number(event.target.value))} /><em><small>Veilig</small><small>Verhoogd</small><small>Zeer riskant</small></em></label><label className="risk-capacity-slider risk-entry-slider"><span>Instapbedrag per positie <b>{entryRiskLabel(entryNotional, configuredEntry)}</b></span><strong>{usd(entryNotional)}</strong><input aria-label="Instapbedrag voor capaciteitsschatting" type="range" min="5" max={Math.max(100, Math.ceil(configuredEntry * 5 / 5) * 5)} step="5" value={entryNotional} onChange={(event) => setEntryNotional(Number(event.target.value))} /><em><small>Veilig</small><small>Verhoogd</small><small>Zeer riskant</small></em></label></div></div>
      {capacity ? <><div className="risk-capacity-result"><span>GESCHAT GEMIDDELD TOTAAL</span><strong>{capacity.estimated}</strong><b>posities</b><small>Waarschijnlijke bandbreedte {capacity.minimum}–{capacity.maximum}</small><p className={capacity.delta >= 0 ? "positive" : "negative"}>{capacity.delta >= 0 ? `Nog ongeveer ${capacity.delta} plekken vanaf de huidige ${selected.active}` : `Ongeveer ${Math.abs(capacity.delta)} posities boven dit risiconiveau`}</p></div><div className="risk-capacity-metrics"><RiskFact label="Werkelijke maintenance" value={`${selected.marginRatio.toFixed(2)}%`} /><RiskFact label="Nu actief" value={String(selected.active)} /><RiskFact label="Geschat totaal" value={String(capacity.estimated)} /><RiskFact label="Plekken verschil" value={`${capacity.delta >= 0 ? "+" : ""}${capacity.delta}`} /><RiskFact label="Gem. exposure" value={Number.isFinite(capacity.averageExposure) ? usd(capacity.averageExposure) : "—"} /><RiskFact label="Verwacht niveau" value={`${capacity.projectedRatio.toFixed(2)}%`} /></div><div className="risk-capacity-bar"><i style={{ width: `${Math.min(100, selected.marginRatio)}%` }} /><mark style={{ left: `${safeMaintenanceLimit}%` }} /><span>Huidig {selected.marginRatio.toFixed(2)}%</span><b>Keuze {safeMaintenanceLimit}%</b></div><p className="risk-capacity-note">Stressfactor {capacity.stressFactor.toFixed(2)}× · leverage {selected.leverage.toFixed(1)}× · DCA {selected.dca} · LONG {usd(selected.long)} · SHORT {usd(selected.short)}. Deze schuif verandert de botinstellingen niet.</p></> : <div className="risk-empty compact"><strong>Nog geen bruikbare schatting</strong><p>Er zijn minimaal actuele maintenance, equity en een werkelijk actief positieaantal nodig. Vernieuw Aster; zodra die waarden binnen zijn verschijnt het geschatte totaal direct.</p></div>}
    </article>}

    {selected && <div className="risk-lower-grid">
      <article className="risk-factor-card"><div className="risk-card-title"><div><span>RISICOBIJDRAGEN</span><h2>Waar komt het risico vandaan?</h2></div><small>Transparant, geen zwarte doos</small></div><RiskFactors point={selected} /></article>
      <article className="risk-simulator"><div className="risk-card-title"><div><span>VEILIGE WAT-ALS ANALYSE</span><h2>Wat had mogelijk beter gekund?</h2></div><small>Simulatie · geen order</small></div>
        <label>Exposure ten opzichte van werkelijk <b>{simExposure}%</b><input type="range" min="25" max="125" step="5" value={simExposure} onChange={(event) => setSimExposure(Number(event.target.value))} /></label>
        <label>Leverage ten opzichte van werkelijk <b>{simLeverage}%</b><input type="range" min="25" max="125" step="5" value={simLeverage} onChange={(event) => setSimLeverage(Number(event.target.value))} /></label>
        <div className="risk-sim-result"><span>Geschatte alternatieve score</span><strong>{simulated?.score ?? selected.score}</strong><small>{simulated ? `${simulated.delta > 0 ? "+" : ""}${simulated.delta} punten tegenover werkelijk` : "—"}</small></div>
        <p>{simulated?.message}</p>
      </article>
    </div>}
    <footer className="risk-disclaimer"><strong>Analyse, geen garantie</strong><span>De score ondersteunt besluitvorming maar voorspelt geen marktbeweging. Geschiedenis wordt in deze testversie vanaf het eerste gebruik opgebouwd; ontbrekende eerdere perioden worden niet ingevuld met nepdata.</span></footer>
  </section>;
}

function RiskChart({ points, selectedId, onSelect }: { points: RiskPoint[]; selectedId: string; onSelect: (id: string) => void }) {
  if (!points.length) return <div className="risk-chart-empty"><div /><strong>De eerste betrouwbare meting verschijnt hier</strong><span>Vernieuw de gekoppelde exchange om de tijdlijn te starten.</span></div>;
  const width = 900, height = 300, pad = 28;
  const minAt = points[0].at, maxAt = Math.max(points[points.length - 1].at, minAt + 1);
  const coords = points.map((point) => ({ point, x: pad + ((point.at - minAt) / (maxAt - minAt)) * (width - pad * 2), y: pad + (1 - point.score / 100) * (height - pad * 2) }));
  const path = coords.map((item, index) => `${index ? "L" : "M"}${item.x.toFixed(1)},${item.y.toFixed(1)}`).join(" ");
  return <div className="risk-chart-wrap"><svg className="risk-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Risicoscore door de tijd">
    <defs><linearGradient id="riskLine" x1="0" x2="1"><stop stopColor="#2ed6ba"/><stop offset=".55" stopColor="#f0b94b"/><stop offset="1" stopColor="#ff4e73"/></linearGradient><linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#6c70ff" stopOpacity=".28"/><stop offset="1" stopColor="#081426" stopOpacity="0"/></linearGradient></defs>
    <rect x={pad} y={pad} width={width-pad*2} height={(height-pad*2)*.25} fill="#ff4e7310"/><rect x={pad} y={pad+(height-pad*2)*.25} width={width-pad*2} height={(height-pad*2)*.25} fill="#f0b94b0b"/><rect x={pad} y={pad+(height-pad*2)*.5} width={width-pad*2} height={(height-pad*2)*.25} fill="#4b9eff08"/>
    {[0,25,50,75,100].map((value) => <g key={value}><line x1={pad} x2={width-pad} y1={pad+(1-value/100)*(height-pad*2)} y2={pad+(1-value/100)*(height-pad*2)} stroke="#7690b020"/><text x="4" y={pad+(1-value/100)*(height-pad*2)+3} fill="#71839a" fontSize="9">{value}</text></g>)}
    <path d={`${path} L${coords[coords.length-1].x},${height-pad} L${coords[0].x},${height-pad} Z`} fill="url(#riskFill)"/><path d={path} fill="none" stroke="url(#riskLine)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"/>
    {coords.map(({ point, x, y }) => <circle key={point.id} cx={x} cy={y} r={selectedId === point.id ? 8 : 5} fill={riskColor(point.score)} stroke="#071426" strokeWidth="3" className="risk-point" onClick={() => onSelect(point.id)}><title>{`${new Date(point.at).toLocaleString("nl-NL")}: score ${point.score}`}</title></circle>)}
  </svg></div>;
}

function RiskBadge({ point }: { point: RiskPoint | null }) { return <div className={`risk-current ${point ? riskClass(point.score) : "unknown"}`}><span>HUIDIG RISICO</span><strong>{point?.score ?? "—"}</strong><small>{point ? riskLabel(point.score) : "Onvoldoende gegevens"}</small></div>; }
function RiskFact({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
function RiskFactors({ point }: { point: RiskPoint }) {
  const factors = factorScores(point);
  return <div className="risk-factor-list">{factors.map((factor) => <div key={factor.name}><header><span>{factor.name}</span><b>{factor.score}/100</b></header><i><em style={{ width: `${factor.score}%` }} /></i><small>{factor.detail}</small></div>)}</div>;
}
function calculateRisk(snapshots: ExchangeSnapshots, scope: RiskPoint["exchange"], history: RiskPoint[]): RiskPoint | null {
  const selected = scope === "all" ? [snapshots.hyperliquid.data, snapshots.aster.data] : [snapshots[scope].data];
  const valid = selected.filter((item): item is Record<string, unknown> => Boolean(item));
  if (!valid.length) return null;
  let equity = 0, maintenance = 0, openPnl = 0, gross = 0, long = 0, short = 0, leverageWeighted = 0, dca = 0, active = 0, confidenceFields = 0;
  const notionals: number[] = [];
  for (const data of valid) {
    const e = firstNumber(data, ["portfolioValue", "equity", "accountValue", "walletBalance"]); if (e !== null) { equity += e; confidenceFields++; }
    const m = firstNumber(data, ["maintenanceMargin", "totalMaintMargin"]); if (m !== null) { maintenance += m; confidenceFields++; }
    const pnl = firstNumber(data, ["openPnl", "unrealizedPnl", "totalUnrealizedPnl"]); if (pnl !== null) openPnl += pnl;
    const positions = Array.isArray(data.positions) ? data.positions as Array<Record<string, unknown>> : [];
    active += positions.length;
    for (const position of positions) {
      const side = String(position.side ?? position.positionSide ?? "").toUpperCase();
      const notional = Math.abs(firstNumber(position, ["notionalUsd", "notional", "positionValueUsd", "positionValue", "sizeUsd"]) ?? ((Math.abs(firstNumber(position, ["size", "positionAmt", "szi"]) ?? 0)) * Math.abs(firstNumber(position, ["markPrice", "price", "currentPrice"]) ?? 0)));
      const lev = Math.abs(firstNumber(position, ["leverage", "leverageValue"]) ?? 1);
      if (notional > 0) { notionals.push(notional); gross += notional; leverageWeighted += notional * lev; if (side.includes("SHORT") || (firstNumber(position, ["positionAmt", "szi"]) ?? 0) < 0) short += notional; else long += notional; }
      dca += Math.max(0, Math.round(firstNumber(position, ["dcaCount", "buyCount", "safetyOrders"] ) ?? 0));
    }
  }
  if (equity <= 0) return null;
  const marginRatio = maintenance > 0 ? maintenance / equity * 100 : average(valid.map((data) => (firstNumber(data, ["marginRatio"]) ?? 0) * 100));
  const leverage = gross > 0 ? leverageWeighted / gross : 0;
  const net = long - short;
  const concentration = gross > 0 && notionals.length ? Math.max(...notionals) / gross * 100 : 0;
  const previous = history.filter((item) => item.exchange === scope);
  const hwm = Math.max(equity, ...previous.map((item) => item.equity));
  const drawdown = hwm > 0 ? Math.max(0, (hwm - equity) / hwm * 100) : 0;
  const raw = marginRisk(marginRatio) * .35 + clamp(leverage / 25 * 100) * .15 + clamp(concentration * 2) * .15 + clamp(Math.abs(net) / Math.max(gross, 1) * 100) * .10 + clamp(dca * 3) * .10 + clamp(drawdown * 5) * .15;
  const score = Math.round(clamp(raw));
  const confidence = Math.round(clamp(45 + confidenceFields * 12 + (active ? 20 : 0), 0, 100));
  const reasons = buildReasons({ marginRatio, leverage, concentration, gross, net, dca, drawdown, active });
  const at = Date.now();
  return { id: `${scope}-${at}`, at, score, confidence, equity, marginRatio, gross, net, long, short, openPnl, active, leverage, concentration, dca, exchange: scope, reasons };
}

function buildReasons(input: { marginRatio: number; leverage: number; concentration: number; gross: number; net: number; dca: number; drawdown: number; active: number }) {
  const reasons: Array<{ weight: number; text: string }> = [];
  reasons.push({ weight: marginRisk(input.marginRatio), text: `Maintenance gebruikt ${input.marginRatio.toFixed(2)}% van de equity; richting 100% neemt het liquidatierisico sterk toe.` });
  if (input.leverage) reasons.push({ weight: input.leverage * 4, text: `De gewogen leverage is ongeveer ${input.leverage.toFixed(1)}×; hierdoor reageren marge en ROE sterker op prijsbewegingen.` });
  if (input.gross) reasons.push({ weight: input.concentration * 2, text: `De grootste positie vormt ${input.concentration.toFixed(1)}% van de totale exposure; hoge concentratie maakt één pair belangrijker.` });
  if (input.gross) reasons.push({ weight: Math.abs(input.net) / input.gross * 100, text: `De directionele onbalans is ${(Math.abs(input.net) / input.gross * 100).toFixed(1)}% van gross exposure.` });
  if (input.dca) reasons.push({ weight: input.dca * 3, text: `${input.dca} geregistreerde DCA-stappen vergroten de opgebouwde exposure en herstelafhankelijkheid.` });
  if (input.drawdown) reasons.push({ weight: input.drawdown * 5, text: `De portfolio staat ${input.drawdown.toFixed(2)}% onder de lokaal gemeten high-water mark.` });
  return reasons.sort((a, b) => b.weight - a.weight).slice(0, 4).map((item) => item.text);
}

function factorScores(point: RiskPoint) { const imbalance = point.gross ? Math.abs(point.net) / point.gross * 100 : 0; return [
  { name: "Margin & liquidatie", score: Math.round(marginRisk(point.marginRatio)), detail: `${point.marginRatio.toFixed(2)}% maintenance/equity` },
  { name: "Leverage", score: Math.round(clamp(point.leverage / 25 * 100)), detail: `${point.leverage.toFixed(1)}× gewogen leverage` },
  { name: "Concentratie", score: Math.round(clamp(point.concentration * 2)), detail: `${point.concentration.toFixed(1)}% in de grootste positie` },
  { name: "Richtingsbalans", score: Math.round(clamp(imbalance)), detail: `${imbalance.toFixed(1)}% netto onbalans` },
  { name: "DCA-opbouw", score: Math.round(clamp(point.dca * 3)), detail: `${point.dca} geregistreerde bijkopen` },
].sort((a,b) => b.score-a.score); }
function simulate(point: RiskPoint, exposurePercent: number, leveragePercent: number) { const exposureFactor = exposurePercent / 100, leverageFactor = leveragePercent / 100; const margin = marginRisk(point.marginRatio * exposureFactor); const score = Math.round(clamp(margin*.35 + clamp(point.leverage*leverageFactor/25*100)*.15 + clamp(point.concentration*2)*.15 + clamp(Math.abs(point.net)*exposureFactor/Math.max(point.gross*exposureFactor,1)*100)*.10 + clamp(point.dca*3)*.10)); const delta = score-point.score; return { score, delta, message: delta < 0 ? `In deze vereenvoudigde terugblik was de risicoscore ongeveer ${Math.abs(delta)} punten lager. Mogelijke gemiste winst en marktdynamiek zijn hierin niet volledig te voorspellen.` : delta > 0 ? `Deze combinatie had de geschatte risicoscore ongeveer ${delta} punten verhoogd.` : "Deze aanpassing verandert de geschatte score nauwelijks. Bekijk vooral concentratie, margin en DCA samen." }; }
function summary(point: RiskPoint) { const top = point.reasons[0] || "Er is nog onvoldoende detail voor een hoofdoorzaak."; return `Score ${point.score} (${riskLabel(point.score).toLowerCase()}). ${top}`; }
function riskLabel(score: number) { return score >= 85 ? "Kritiek" : score >= 70 ? "Zeer hoog" : score >= 50 ? "Hoog" : score >= 25 ? "Verhoogd" : "Laag"; }
function riskClass(score: number) { return score >= 70 ? "critical" : score >= 50 ? "high" : score >= 25 ? "raised" : "low"; }
function riskColor(score: number) { return score >= 70 ? "#ff4e73" : score >= 50 ? "#f0b94b" : score >= 25 ? "#4b9eff" : "#2ed6ba"; }
function marginRisk(value: number) { return clamp(value <= 10 ? value * 2 : value <= 30 ? 20 + (value-10)*1.5 : value <= 60 ? 50+(value-30) : 80+(value-60)*.5); }
function estimatePositionCapacity(point: RiskPoint, safeLimit: number, entryNotional: number, configuredEntry: number) {
  if (point.active <= 0 || point.marginRatio <= 0 || point.equity <= 0) return null;
  const entryScale = configuredEntry > 0 ? Math.max(.1, entryNotional / configuredEntry) : 1;
  const maintenancePerPosition = point.marginRatio / point.active * entryScale;
  const imbalance = Math.abs(point.net) / Math.max(point.gross, 1);
  const dcaPerPosition = point.dca / point.active;
  const lossPressure = Math.max(0, -point.openPnl) / Math.max(point.equity, 1);
  const leveragePressure = Math.min(.3, Math.max(0, point.leverage - 5) / 100);
  const stressFactor = 1.12 + leveragePressure + Math.min(.35, imbalance * .35) + Math.min(.4, dcaPerPosition * .08) + Math.min(.4, lossPressure * 2);
  const optimisticFactor = Math.max(1, stressFactor - .18);
  const conservativeFactor = stressFactor + .25;
  const minimum = Math.max(0, Math.floor(safeLimit / (maintenancePerPosition * conservativeFactor)));
  const maximum = Math.max(minimum, Math.floor(safeLimit / (maintenancePerPosition * optimisticFactor)));
  const estimated = Math.round((minimum + maximum) / 2);
  const delta = estimated - point.active;
  const projectedRatio = Math.min(100, estimated * maintenancePerPosition * stressFactor);
  return { minimum, maximum, estimated, delta, projectedRatio, stressFactor, averageExposure: point.gross > 0 ? point.gross / point.active * entryScale : Number.NaN };
}
function capacityRiskLabel(value: number) { return value <= 25 ? "Veilig" : value <= 40 ? "Voorzichtig" : value <= 55 ? "Verhoogd" : value <= 70 ? "Hoog" : "Zeer riskant"; }
function entryRiskLabel(value: number, configured: number) { const ratio = configured > 0 ? value / configured : 1; return ratio <= .75 ? "Veilig" : ratio <= 1.1 ? "Huidige inleg" : ratio <= 1.75 ? "Verhoogd" : ratio <= 3 ? "Hoog" : "Zeer riskant"; }
function asterBaseNotional(snapshots: ExchangeSnapshots) { const data = snapshots.aster.data; if (!data) return 20; const state = data.strategy2 && typeof data.strategy2 === "object" ? data.strategy2 as Record<string, unknown> : {}; const settings = state.settings && typeof state.settings === "object" ? state.settings as Record<string, unknown> : {}; return Math.max(5, firstNumber(settings, ["baseNotional", "baseOrderUsd", "baseOrder"]) ?? 20); }
function firstNumber(source: Record<string, unknown>, keys: string[]) { for (const key of keys) { const value = Number(source[key]); if (Number.isFinite(value)) return value; } return null; }
function validPoint(item: unknown): item is RiskPoint { const point = item as RiskPoint; return Boolean(point && Number.isFinite(point.at) && Number.isFinite(point.score) && typeof point.exchange === "string"); }
function average(values: number[]) { return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0; }
function clamp(value: number, min=0, max=100) { return Math.max(min, Math.min(max, value)); }
function usd(value: number) { return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value); }
function signedUsd(value: number) { return `${value >= 0 ? "+" : ""}${usd(value)}`; }
