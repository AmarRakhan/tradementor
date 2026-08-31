"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { strategy2ServerStatus } from "@/lib/aster-strategy2-server-status.mjs";

type ManualSide = "LONG" | "SHORT";
type ManualSymbol = { symbol: string; side: ManualSide };
type Values = {
  name: string; universe: string; positions: string; longSlots: string; shortSlots: string;
  minLeverage: string; entryMargin: string; dcaDistance: string; dcaMargin: string;
  maxDca: string; tp: string; mode: "paper" | "live";
  manualEnabled: boolean; manualSymbols: ManualSymbol[];
};
const initial: Values = {
  name: "Aster Multi DCA", universe: "30", positions: "30", longSlots: "20", shortSlots: "10",
  minLeverage: "50", entryMargin: "5", dcaDistance: "0.30", dcaMargin: "2", maxDca: "3", tp: "1.5", mode: "live",
  manualEnabled: false, manualSymbols: [],
};
const n = (v: string) => Number(v) || 0;
const parseManualSymbols = (value: unknown): ManualSymbol[] => Array.isArray(value) ? value.flatMap((row) => {
  if (!row || typeof row !== "object") return [];
  const item = row as Record<string, unknown>;
  const symbol = String(item.symbol || "").toUpperCase();
  const side = String(item.side || "").toUpperCase();
  return symbol && (side === "LONG" || side === "SHORT") ? [{ symbol, side: side as ManualSide }] : [];
}) : [];

export function AsterStrategy2Maker({ snapshot, serverConfirmed, onConfirmed, onChanged }: { snapshot: Record<string, unknown> | null; serverConfirmed: boolean; onConfirmed: (strategy2: Record<string, unknown>) => void; onChanged: () => void }) {
  const [wizard, setWizard] = useState(false), [step, setStep] = useState(0), [v, setV] = useState(initial), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const [readiness, setReadiness] = useState<Record<string, unknown> | null>(null), [confirmedState, setConfirmedState] = useState<Record<string, unknown> | null>(null);
  const [markets, setMarkets] = useState<string[]>([]), [marketSearch, setMarketSearch] = useState(""), [marketBusy, setMarketBusy] = useState(false), [marketAttempted, setMarketAttempted] = useState(false);
  const snapshotState = (snapshot?.strategy2 && typeof snapshot.strategy2 === "object" ? snapshot.strategy2 : {}) as Record<string, unknown>;
  const status = strategy2ServerStatus(snapshotState, confirmedState, serverConfirmed); const state = status.state as Record<string, unknown>;

  useEffect(() => {
    if (wizard) return;
    const x = state.settings as Record<string, unknown> | undefined;
    if (!x || String(x.engine || x.strategyKind) !== "multi_bb_v1") return;
    setV({
      name: String(x.name || initial.name), universe: String(x.universeTopN ?? 30), positions: String(x.maximumPositions ?? 30),
      longSlots: String(x.longSlots ?? 20), shortSlots: String(x.shortSlots ?? 10), minLeverage: String(x.minimumLeverage ?? 50),
      entryMargin: String(x.entryNotionalUsd ?? x.baseNotional ?? (Number(x.entryMarginUsd ?? 5) * Number(x.minimumLeverage ?? 50))),
      dcaDistance: String(Number(x.dcaDistance ?? .003) * 100), dcaMargin: String(x.dcaMarginUsd ?? 2), maxDca: String(x.maxDca ?? 3),
      tp: String(Number(x.takeProfit ?? .015) * 100), mode: x.mode === "paper" ? "paper" : "live",
      manualEnabled: x.manualSymbolSelectionEnabled === true, manualSymbols: parseManualSymbols(x.manualSymbols),
    });
  }, [state.settings, wizard]);

  const settings = useMemo(() => ({
    engine: "multi_bb_v1", strategyKind: "multi_bb_v1", name: v.name, mode: v.mode,
    universeTopN:Math.round(n(v.universe)), maximumPositions:Math.round(n(v.positions)), longSlots:Math.round(n(v.longSlots)), shortSlots:Math.round(n(v.shortSlots)),
    minimumLeverage: Math.round(n(v.minLeverage)), entryNotionalUsd: n(v.entryMargin), entryMarginUsd: n(v.entryMargin) / Math.max(1, Math.round(n(v.minLeverage))),
    dcaDistance: n(v.dcaDistance) / 100, dcaMarginUsd: n(v.dcaMargin), maxDca: Math.round(n(v.maxDca)), takeProfit:n(v.tp)/100,
    entryMode: "immediate_fill", marginMode: "cross", autoRestart: true,
    manualSymbolSelectionEnabled: v.manualEnabled, manualSymbols: v.manualSymbols,
  }), [v]);

  const setTotal = (x: string) => { const total = Math.max(1, Math.round(Number(x) || 0)); const long = Math.min(total, Math.round(n(v.longSlots))); setV({ ...v, positions: x, longSlots: String(long), shortSlots: String(total - long) }); };
  const setLong = (x: string) => { const total = Math.max(1, Math.round(n(v.positions))); const long = Math.max(0, Math.min(total, Math.round(Number(x) || 0))); setV({ ...v, longSlots: String(long), shortSlots: String(total - long) }); };
  const setShort = (x: string) => { const total = Math.max(1, Math.round(n(v.positions))); const sh = Math.max(0, Math.min(total, Math.round(Number(x) || 0))); setV({ ...v, shortSlots: String(sh), longSlots: String(total - sh) }); };

  async function loadMarkets() {
    if (marketBusy) return;
    setMarketAttempted(true); setMarketBusy(true);
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/focus/markets") as Record<string, unknown>;
      const ranking = Array.isArray(result.ranking) ? result.ranking : [];
      setMarkets(ranking.flatMap((row) => row && typeof row === "object" ? [String((row as Record<string, unknown>).symbol || "").toUpperCase()] : []).filter(Boolean));
    } catch (e) { setMessage(e instanceof Error ? e.message : "Aster-markten konden niet worden geladen."); }
    finally { setMarketBusy(false); }
  }
  useEffect(() => { if (wizard && v.manualEnabled && !marketAttempted) void loadMarkets(); }, [wizard, v.manualEnabled, marketAttempted]);

  const selected = new Set(v.manualSymbols.map((x) => x.symbol));
  const marketMatches = markets.filter((symbol) => !selected.has(symbol) && symbol.includes(marketSearch.trim().toUpperCase())).slice(0, 10);
  const addSymbol = (symbol: string) => { if (!symbol || selected.has(symbol)) return; setV({ ...v, manualSymbols: [...v.manualSymbols, { symbol, side: "LONG" }] }); setMarketSearch(""); };
  const setSymbolSide = (symbol: string, side: ManualSide) => setV({ ...v, manualSymbols: v.manualSymbols.map((row) => row.symbol === symbol ? { ...row, side } : row) });
  const removeSymbol = (symbol: string) => setV({ ...v, manualSymbols: v.manualSymbols.filter((row) => row.symbol !== symbol) });
  const selectedLong = v.manualSymbols.filter((x) => x.side === "LONG").length, selectedShort = v.manualSymbols.filter((x) => x.side === "SHORT").length;

  const manualPicker = <div className="manual-symbol-mode">
    <label className="manual-symbol-toggle"><span><b>Zelf munten kiezen</b><small>Optioneel. UIT = exact huidige Top-N werking.</small></span><input type="checkbox" checked={v.manualEnabled} onChange={(e) => setV({ ...v, manualEnabled: e.target.checked })} /></label>
    {v.manualEnabled && <div className="manual-symbol-picker">
      <div className="manual-symbol-search"><input value={marketSearch} onChange={(e) => setMarketSearch(e.target.value.toUpperCase())} onFocus={() => { if (!markets.length) void loadMarkets(); }} placeholder="Zoek munt, bijvoorbeeld HYPEUSDT" /><button type="button" disabled={marketBusy || !marketSearch.trim()} onClick={() => { const exact = markets.find((x) => x === marketSearch.trim().toUpperCase()); if (exact) addSymbol(exact); }}>+ toevoegen</button></div>
      {marketSearch.trim() && <div className="manual-symbol-results">{marketBusy ? <small>Markten laden…</small> : marketMatches.length ? marketMatches.map((symbol) => <button type="button" key={symbol} onClick={() => addSymbol(symbol)}>{symbol}<i>+</i></button>) : <small>Geen beschikbare Aster USDT perpetual gevonden.</small>}</div>}
      <div className="manual-symbol-selected">{v.manualSymbols.map((row) => <div key={row.symbol}><b>{row.symbol}</b><span><button type="button" className={row.side === "LONG" ? "active long" : ""} onClick={() => setSymbolSide(row.symbol, "LONG")}>LONG</button><button type="button" className={row.side === "SHORT" ? "active short" : ""} onClick={() => setSymbolSide(row.symbol, "SHORT")}>SHORT</button></span><button type="button" className="remove" onClick={() => removeSymbol(row.symbol)} aria-label={`${row.symbol} verwijderen`}>×</button></div>)}</div>
      <p className="manual-symbol-summary">{v.manualSymbols.length} geselecteerd · {selectedLong} LONG · {selectedShort} SHORT</p>
      {!v.manualSymbols.length && <p className="inline-warning">Selecteer minimaal één munt. Bestaande posities worden nooit gesloten door deze keuze.</p>}
    </div>}
  </div>;

  const steps = [
    { title: "Top-N Aster-volume", help: "Alleen actuele Aster USDT-markten binnen deze Top-N op 24h quote-volume mogen een nieuwe positie openen. De extra handmatige modus hieronder verandert dit alleen wanneer jij hem expliciet aanzet.", body: <><Field label="Top-N volume" value={v.universe} set={x => setV({ ...v, universe: x })} />{manualPicker}</> },
    { title: "Hoeveel posities tegelijk?", help: "LONG + SHORT moet exact gelijk zijn aan het totaal. Dezelfde munt kan niet tegelijk LONG en SHORT zijn.", body: <><Field label="Totaal posities" value={v.positions} set={setTotal} /><Field label="LONG slots" value={v.longSlots} set={setLong} /><Field label="SHORT slots" value={v.shortSlots} set={setShort} /><b>{v.positions} totaal · {v.longSlots} LONG · {v.shortSlots} SHORT</b></> },
    { title: "Minimum leverage", help: "Een munt valt af als Aster minder ondersteunt. Een toegestane munt gebruikt de hoogste leverage die Aster voor de geplande order toestaat.", body: <Field label="Minimum leverage (×)" value={v.minLeverage} set={x => setV({ ...v, minLeverage: x })} /> },
    { title: "Eerste instap", help: "Dit is de vaste orderwaarde per nieuwe positie. De bot kiest een geldige leverage en berekent de benodigde margin automatisch.", body: <Field label="Entry orderwaarde (USDT)" value={v.entryMargin} set={x => setV({ ...v, entryMargin: x })} /> },
    { title: "Direct slots vullen", help: v.manualEnabled ? "Vrije slots worden direct gevuld uit jouw geselecteerde munten en richtingen. Er is geen indicator- of Bollinger-wachtregel." : "Vrije LONG- en SHORT-slots worden direct gevuld met de hoogst gerangschikte geldige Top-N markten. Er is geen indicator- of Bollinger-wachtregel.", body: <div className="maker-summary"><b>DIRECT FILL</b><span>Na TP komt het slot direct vrij en start de volgende positie als een nieuwe schone cyclus met DCA-teller 0.</span></div> },
    { title: "DCA-afstand", help: "LONG koopt lager bij; SHORT koopt hoger bij. De afstand wordt vanaf de laatste bot-fill gemeten.", body: <Field label="DCA afstand (%)" value={v.dcaDistance} set={x => setV({ ...v, dcaDistance: x })} /> },
    { title: "DCA-bedrag en harde limiet", help: "Na dit aantal automatische DCA's komt er absoluut geen extra automatische DCA. Handmatig bijkopen verandert deze teller niet.", body: <><Field label="DCA margin (USDT)" value={v.dcaMargin} set={x => setV({ ...v, dcaMargin: x })} /><Field label="Max automatische DCA's" value={v.maxDca} set={x => setV({ ...v, maxDca: x })} /></> },
    { title: "Take profit", help: "TP wordt telkens berekend vanaf de echte gewogen Aster-entry, ook na een handmatige bijkoop.", body: <Field label="Take Profit (%)" value={v.tp} set={x => setV({ ...v, tp: x })} /> },
    { title: "Cross margin", help: "Deze strategie gebruikt uitsluitend cross margin. Alle posities delen dezelfde accountpot; iedere risicotoename krijgt een available-margin check.", body: <div className="maker-summary"><b>CROSS</b><span>Geen hedge/airbag/portfolio-TP/Focus-state machine.</span><span>Risicobegrenzer: max automatische DCA's per positie.</span></div> },
    { title: "Controle", help: "Opslaan start niets. Jij start de bot pas zelf nadat alles gecontroleerd is.", body: <div className="maker-summary"><b>{v.name}</b><span>{v.manualEnabled ? `${v.manualSymbols.length} zelf gekozen munten · ${selectedLong} LONG / ${selectedShort} SHORT` : `Top ${v.universe} · ${v.positions} posities · ${v.longSlots} LONG / ${v.shortSlots} SHORT`}</span><span>Min {v.minLeverage}× · entry ${v.entryMargin} orderwaarde</span><span>DCA {v.dcaDistance}% · ${v.dcaMargin} · max {v.maxDca}</span><span>TP {v.tp}% · direct refill · cross</span></div> },
  ];

  async function action(kind: "save" | "simulate" | "start" | "stop") {
    setBusy(true); setMessage("");
    try {
      const route = kind === "save" ? "settings" : kind; const method = kind === "save" ? "PUT" : "POST"; const body = kind === "start" ? { confirm: true, settings } : kind === "stop" ? { confirm: true } : { settings };
      const result = await authenticatedRequest(`/api/exchanges/aster/strategy2/${route}`, { method, body: JSON.stringify(body) }) as Record<string, unknown>;
      const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null;
      if (confirmed) { setConfirmedState(confirmed); onConfirmed(confirmed); }
      if (kind === "start" && result.started === true) setWizard(false);
      if (kind === "save") setMessage("Nieuwe Multi DCA-configuratie opgeslagen. De bot is niet gestart.");
      else if (kind === "simulate") setMessage("Configuratie geldig; 0 orders verzonden.");
      else if (kind === "stop") setMessage("Bot gestopt; er worden geen automatische orders geplaatst.");
      else {
        const firstTick = result.firstTick && typeof result.firstTick === "object" ? result.firstTick as Record<string, unknown> : null;
        const tickStatus = String(firstTick?.status || "").toLowerCase(); const tickReason = String(firstTick?.reason || confirmed?.lastReason || "").trim();
        if (result.started !== true || confirmed?.enabled !== true) setMessage(`Start niet door de server bevestigd${tickReason ? `: ${tickReason}` : "."}`);
        else if (["blocked", "data-hold", "stopped"].includes(tickStatus)) setMessage(`Multi DCA is ingeschakeld, maar de eerste scan wacht${tickReason ? `: ${tickReason}` : "."}`);
        else setMessage("Multi DCA is ingeschakeld en server-side bevestigd.");
      }
      await Promise.resolve(onChanged());
    } catch (e) { setMessage(e instanceof Error ? e.message : "Actie mislukt"); } finally { setBusy(false); }
  }
  async function checkReadiness() { setBusy(true); setMessage(""); try { const r = await authenticatedRequest("/api/exchanges/aster/strategy2/readiness") as Record<string, unknown>; setReadiness(r); setMessage(Boolean(r.liveReady) ? "Live-gereedheid bevestigd." : "Readiness gecontroleerd; aanvullende live-bevestiging kan nodig zijn."); await Promise.resolve(onChanged()); } catch (e) { setMessage(e instanceof Error ? e.message : "Readiness mislukt"); } finally { setBusy(false); } }
  async function runCanary() { setBusy(true); setMessage("Canary opent één LONG van maximaal US$ 20 totale orderwaarde en sluit direct na bevestigde fill."); try { const r = await authenticatedRequest("/api/exchanges/aster/strategy2/canary", { method: "POST", body: JSON.stringify({confirm:true,notional_usd:20}) }) as Record<string, unknown>; setMessage(r.completed ? `Canary geslaagd op ${String(r.symbol)}: open en volledige close bevestigd.` : "Canary niet afgerond."); await checkReadiness(); await Promise.resolve(onChanged()); } catch (e) { setMessage(e instanceof Error ? e.message : "Canary veilig gestopt"); setBusy(false); } }
  const enabled = status.enabled === true; const liveReady = status.liveReady === true || (!status.pending && readiness?.liveReady === true); const report = (state.multiBb && typeof state.multiBb === "object" ? state.multiBb : {}) as Record<string, unknown>; const current = steps[Math.min(step, steps.length - 1)];
  async function toggleLive(){if(status.pending)return;if(enabled){await action("stop");return}if(liveReady){await action("start");return}await checkReadiness()}

  return <article id="strategy-2-maker" className="strategy-card strategy-two-card">
    <div className="strategy-title-row"><div><span className="kicker">ASTER BOT</span><h2>Multi DCA</h2></div><span className={`strategy-state ${enabled ? "on" : ""}`}>{enabled ? "AAN" : "UIT"}</span></div>
    <p>Top-volume multipair · directe LONG/SHORT slotvulling · beperkte DCA · TP op echte gewogen Aster-entry · direct schone herstart na TP.</p>
    <div className="strategy-facts"><span>{v.manualEnabled ? `${v.manualSymbols.length} zelf gekozen` : `Top ${v.universe} volume`}</span><span>{v.longSlots} LONG · {v.shortSlots} SHORT</span><span>min {v.minLeverage}×</span><span>DCA max {v.maxDca}</span><span>TP {v.tp}%</span><span>CROSS</span></div>
    <div className="strategy-message"><b>Exchange truth:</b> handmatige toevoegingen aan een beheerde positie worden meegenomen in quantity en gewogen entry zonder de automatische DCA-teller te resetten.<br /><b>Laatste scan:</b> {String(report.activeLong ?? state.longLegs ?? 0)} LONG · {String(report.activeShort ?? state.shortLegs ?? 0)} SHORT · {Array.isArray(report.rankedTopN) ? report.rankedTopN.length : 0} volume-kandidaten gecontroleerd.</div>
    <div className={`strategy-power-control ${enabled ? "enabled" : "ready"}`}><span><b>Multi DCA live bot</b><small>{enabled ? "draait" : "uit · jij start hem handmatig"}</small></span><button type="button" role="switch" aria-checked={enabled} disabled={busy || status.pending} onClick={toggleLive}><i />{enabled ? "Uitschakelen" : "Inschakelen"}</button></div>
    <button className="expand-settings" onClick={() => { setWizard(true); setStep(0); setMessage(""); }}>Strategy Maker openen</button><button className="expand-settings" disabled={busy} onClick={() => action("simulate")}>Test configuratie</button><button className="expand-settings" disabled={busy} onClick={checkReadiness}>Controleer live-gereedheid</button>
    {Boolean(readiness?.softwareReady) && !Boolean(readiness?.liveReady) && <button className="stop-action" disabled={busy} onClick={runCanary}>Bevestig 1 live testorder · maximaal US$ 20 · direct sluiten</button>}
    {readiness && <p className="strategy-message">Readiness: {Boolean(readiness.liveReady) ? "LIVE READY" : "nog niet volledig live ready"}</p>}
    {wizard && <div className="maker-overlay"><div className="maker-dialog"><button className="maker-close" onClick={() => setWizard(false)}>Sluiten</button><span className="kicker">STAP {step + 1} VAN {steps.length}</span><h2>{current.title}</h2><p>{current.help}</p><div className="maker-input">{current.body}</div><div className="maker-progress"><i style={{ width: `${(step + 1) / steps.length * 100}%` }} /></div><div className="maker-nav"><button disabled={step === 0} onClick={() => setStep(Math.max(0, step - 1))}>Terug</button>{step < steps.length - 1 ? <button onClick={() => setStep(step + 1)}>Volgende</button> : <><button disabled={busy} onClick={() => action("save")}>Opslaan</button><button disabled={busy} onClick={() => action("simulate")}>Test configuratie</button></>}</div>{message && <p className="strategy-message">{message}</p>}</div></div>}
    {message && !wizard && <p className="strategy-message">{message}</p>}
  </article>;
}

function Field({ label, value, set }: { label: string; value: string; set: (x: string) => void }) { return <label>{label}<input value={value} onChange={e => set(e.target.value.replace(",", "."))} /></label>; }
