"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { strategy2ServerStatus } from "@/lib/aster-strategy2-server-status.mjs";
import { MAX_SIDE_SLOTS, MAX_TOTAL_POSITIONS, applyLongSlots, applyShortSlots, splitTotalPositions } from "@/lib/position-slot-input";

type ManualSide = "LONG" | "SHORT";
type ManualSymbol = { symbol: string; side: ManualSide };
type TpMode = "PER_TRADE" | "PORTFOLIO" | "OFF";
type TierPreview = {
  symbol: string;
  entryPlan?: { leverage: number } | null;
  currentLeverage?: number;
  minimumEntryMarginUsd?: number;
  suggestedEntryMarginUsd?: number;
  configuredEntryMarginUsd?: number;
  entryOrderValid?: boolean;
};
type Values = {
  name: string; universe: string; positions: string; longSlots: string; shortSlots: string; minLeverage: string;
  entryMarginLong: string; entryMarginShort: string;
  longDcaDistance: string; shortDcaDistance: string; longDcaAmount: string; shortDcaAmount: string;
  maxDcaLong: string; maxDcaShort: string; longTp: string; shortTp: string; tpMode: TpMode; portfolioTp: string;
  mode: "paper" | "live"; manualEnabled: boolean; manualSymbols: ManualSymbol[];
};

const initial: Values = {
  name: "Aster Multi DCA", universe: "30", positions: "30", longSlots: "20", shortSlots: "10", minLeverage: "50",
  entryMarginLong: "5", entryMarginShort: "5", longDcaDistance: "0.30", shortDcaDistance: "0.30",
  longDcaAmount: "2", shortDcaAmount: "2", maxDcaLong: "3", maxDcaShort: "3", longTp: "1.5", shortTp: "1.5",
  tpMode: "PER_TRADE", portfolioTp: "20", mode: "live", manualEnabled: false, manualSymbols: [],
};
const MAX_DCA = 500;
const n = (value: string) => Number(value.replace(",", ".")) || 0;
const clampInt = (value: number, min: number, max: number) => Math.max(min, Math.min(max, Math.round(value || 0)));
const pct = (value: unknown, fallback: number) => String((Number.isFinite(Number(value)) ? Number(value) : fallback) * 100);
const txt = (value: unknown, fallback: number) => String(Number.isFinite(Number(value)) ? Number(value) : fallback);
const parseManualSymbols = (value: unknown): ManualSymbol[] => Array.isArray(value) ? value.flatMap((row) => {
  if (!row || typeof row !== "object") return [];
  const item = row as Record<string, unknown>; const symbol = String(item.symbol || "").toUpperCase(); const side = String(item.side || "").toUpperCase();
  return symbol && (side === "LONG" || side === "SHORT") ? [{ symbol, side: side as ManualSide }] : [];
}) : [];
const tpModeFrom = (x: Record<string, unknown>): TpMode => {
  const raw = String(x.takeProfitMode || (x.takeProfitEnabled === false ? "OFF" : "PER_TRADE")).toUpperCase();
  return raw === "PORTFOLIO" ? "PORTFOLIO" : raw === "OFF" ? "OFF" : "PER_TRADE";
};

export function AsterStrategy2Maker({ snapshot, serverConfirmed, onConfirmed, onChanged }: { snapshot: Record<string, unknown> | null; serverConfirmed: boolean; onConfirmed: (strategy2: Record<string, unknown>) => void; onChanged: () => void }) {
  const [v, setV] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);
  const [readiness, setReadiness] = useState<Record<string, unknown> | null>(null);
  const [confirmedState, setConfirmedState] = useState<Record<string, unknown> | null>(null);
  const [markets, setMarkets] = useState<string[]>([]);
  const [marketSearch, setMarketSearch] = useState("");
  const [marketBusy, setMarketBusy] = useState(false);
  const [marketAttempted, setMarketAttempted] = useState(false);
  const [marketLoadError, setMarketLoadError] = useState("");
  const [tierPreviews, setTierPreviews] = useState<Record<string, TierPreview>>({});
  const [tierBusy, setTierBusy] = useState(false);
  const [totalDraft, setTotalDraft] = useState<string | null>(null);
  const [longDraft, setLongDraft] = useState<string | null>(null);
  const [shortDraft, setShortDraft] = useState<string | null>(null);

  const snapshotState = (snapshot?.strategy2 && typeof snapshot.strategy2 === "object" ? snapshot.strategy2 : {}) as Record<string, unknown>;
  const status = strategy2ServerStatus(snapshotState, confirmedState, serverConfirmed);
  const state = status.state as Record<string, unknown>;
  const persisted = (state.settings && typeof state.settings === "object" ? state.settings : {}) as Record<string, unknown>;
  const rawReport = ((state.multiBb && typeof state.multiBb === "object" ? state.multiBb : state.multiBbReport && typeof state.multiBbReport === "object" ? state.multiBbReport : {}) || {}) as Record<string, unknown>;
  const cycle = (rawReport.portfolioCycle && typeof rawReport.portfolioCycle === "object" ? rawReport.portfolioCycle : {}) as Record<string, unknown>;

  useEffect(() => {
    if (dirty) return;
    const x = persisted;
    if (!x || String(x.engine || x.strategyKind) !== "multi_bb_v1") return;
    const longSlots = clampInt(Number(x.longSlots ?? 20), 0, MAX_SIDE_SLOTS); const shortSlots = clampInt(Number(x.shortSlots ?? 10), 0, MAX_SIDE_SLOTS);
    const legacyEntry = Number(x.entryMarginUsd ?? 5);
    const legacyDcaDistance = Number(x.dcaDistance ?? .003); const legacyDcaAmount = Number(x.dcaMarginUsd ?? 2); const legacyMax = Number(x.maxDca ?? 3); const legacyTp = Number(x.takeProfit ?? .015);
    setV({
      name: String(x.name || initial.name), universe: String(x.universeTopN ?? 30), positions: String(Math.min(MAX_TOTAL_POSITIONS, longSlots + shortSlots)), longSlots: String(longSlots), shortSlots: String(shortSlots), minLeverage: String(x.minimumLeverage ?? 50),
      entryMarginLong: txt(x.entryMarginLongUsd ?? x.entryMarginLong ?? legacyEntry, legacyEntry), entryMarginShort: txt(x.entryMarginShortUsd ?? x.entryMarginShort ?? legacyEntry, legacyEntry),
      longDcaDistance: pct(x.longDcaDistance ?? legacyDcaDistance, legacyDcaDistance), shortDcaDistance: pct(x.shortDcaDistance ?? legacyDcaDistance, legacyDcaDistance),
      longDcaAmount: txt(x.longDcaMarginUsd ?? x.longDcaAmount ?? legacyDcaAmount, legacyDcaAmount), shortDcaAmount: txt(x.shortDcaMarginUsd ?? x.shortDcaAmount ?? legacyDcaAmount, legacyDcaAmount),
      maxDcaLong: txt(x.maxDcaLong ?? x.longMaxDca ?? legacyMax, legacyMax), maxDcaShort: txt(x.maxDcaShort ?? x.shortMaxDca ?? legacyMax, legacyMax),
      longTp: pct(x.longTakeProfitValue ?? x.takeProfitLong ?? legacyTp, legacyTp), shortTp: pct(x.shortTakeProfitValue ?? x.takeProfitShort ?? legacyTp, legacyTp),
      tpMode: tpModeFrom(x), portfolioTp: txt(x.portfolioTpPercent, 20), mode: x.mode === "paper" ? "paper" : "live",
      manualEnabled: x.manualSymbolSelectionEnabled === true, manualSymbols: parseManualSymbols(x.manualSymbols),
    });
    setTotalDraft(null);
    setLongDraft(null);
    setShortDraft(null);
  }, [persisted, dirty]);

  const change = (next: Values) => { setV(next); setDirty(true); setMessage(""); };
  const settings = useMemo(() => {
    const longSlots = clampInt(n(v.longSlots), 0, MAX_SIDE_SLOTS); const shortSlots = clampInt(n(v.shortSlots), 0, MAX_SIDE_SLOTS); const minLeverage = Math.max(1, Math.round(n(v.minLeverage)));
    const longEntry = n(v.entryMarginLong); const shortEntry = n(v.entryMarginShort);
    const longDistance = n(v.longDcaDistance) / 100; const shortDistance = n(v.shortDcaDistance) / 100;
    const longAmount = n(v.longDcaAmount); const shortAmount = n(v.shortDcaAmount); const maxLong = clampInt(n(v.maxDcaLong), 0, MAX_DCA); const maxShort = clampInt(n(v.maxDcaShort), 0, MAX_DCA);
    const longTp = n(v.longTp) / 100; const shortTp = n(v.shortTp) / 100;
    return {
      ...persisted,
      engine: "multi_bb_v1", strategyKind: "multi_bb_v1", name: v.name, mode: v.mode, universeTopN: Math.max(1, Math.round(n(v.universe))),
      maximumPositions: Math.min(MAX_TOTAL_POSITIONS, longSlots + shortSlots), longSlots, shortSlots, minimumLeverage: minLeverage, entrySizingMode: "margin",
      entryMarginUsd: longEntry, entryMarginLongUsd: longEntry, entryMarginShortUsd: shortEntry, entryMarginLong: longEntry, entryMarginShort: shortEntry,
      entryNotionalUsd: longEntry * minLeverage,
      dcaDistance: longDistance, longDcaDistance: longDistance, shortDcaDistance: shortDistance,
      dcaMarginUsd: longAmount, longDcaMarginUsd: longAmount, shortDcaMarginUsd: shortAmount, longDcaAmount: longAmount, shortDcaAmount: shortAmount,
      maxDca: maxLong, maxDcaLong: maxLong, maxDcaShort: maxShort, longMaxDca: maxLong, shortMaxDca: maxShort, unlimitedDca: false,
      takeProfit: longTp, longTakeProfitValue: longTp, shortTakeProfitValue: shortTp, takeProfitLong: longTp, takeProfitShort: shortTp,
      takeProfitMode: v.tpMode, portfolioTpPercent: n(v.portfolioTp), takeProfitEnabled: v.tpMode === "PER_TRADE",
      entryMode: "immediate_fill", marginMode: "cross", autoRestart: true,
      manualSymbolSelectionEnabled: v.manualEnabled, manualSymbols: v.manualEnabled ? v.manualSymbols : [],
    };
  }, [v, persisted]);

  const setTotal = (raw: string) => {
    const slots = splitTotalPositions(raw);
    change({ ...v, positions: String(slots.total), longSlots: String(slots.long), shortSlots: String(slots.short) });
  };
  const commitTotal = () => { const raw = String(totalDraft ?? v.positions).trim(); setTotalDraft(null); if (raw) setTotal(raw); };
  const setLong = (raw: string) => {
    const slots = applyLongSlots(v.positions, raw);
    change({ ...v, positions: String(slots.total), longSlots: String(slots.long), shortSlots: String(slots.short) });
  };
  const commitLong = () => { const raw = String(longDraft ?? v.longSlots).trim(); setLongDraft(null); if (raw) setLong(raw); };
  const setShort = (raw: string) => {
    const slots = applyShortSlots(v.positions, raw);
    change({ ...v, positions: String(slots.total), longSlots: String(slots.long), shortSlots: String(slots.short) });
  };
  const commitShort = () => { const raw = String(shortDraft ?? v.shortSlots).trim(); setShortDraft(null); if (raw) setShort(raw); };

  async function loadMarkets() {
    if (marketBusy) return; setMarketAttempted(true); setMarketBusy(true); setMarketLoadError("");
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/focus/markets") as Record<string, unknown>;
      if (!Array.isArray(result.ranking)) throw new Error("Aster-marktlijst gaf geen geldige ranking terug.");
      const symbols = result.ranking.flatMap((row) => row && typeof row === "object" ? [String((row as Record<string, unknown>).symbol || "").toUpperCase().trim()] : []).filter(Boolean);
      if (!symbols.length) throw new Error("Aster retourneerde geen actieve USDT perpetuals.");
      setMarkets([...new Set(symbols)]);
    }
    catch (error) { const text = error instanceof Error ? error.message : "Aster-markten konden niet worden geladen."; setMarketLoadError(text); setMessage(text); }
    finally { setMarketBusy(false); }
  }
  useEffect(() => { if (v.manualEnabled && !marketAttempted) void loadMarkets(); }, [v.manualEnabled, marketAttempted]);
  useEffect(() => {
    if (!v.manualEnabled || !v.manualSymbols.length) { setTierPreviews({}); return; }
    let cancelled = false; setTierBusy(true);
    void Promise.all(v.manualSymbols.map(async (row) => {
      const entry = row.side === "SHORT" ? v.entryMarginShort : v.entryMarginLong; const dca = row.side === "SHORT" ? v.shortDcaAmount : v.longDcaAmount;
      const q = new URLSearchParams({ symbol: row.symbol, minimumLeverage: String(Math.max(1, Math.round(n(v.minLeverage)))), entryMarginUsd: String(Math.max(.01, n(entry))), dcaMarginUsd: String(Math.max(.01, n(dca))) });
      const result = await authenticatedRequest(`/api/exchanges/aster/strategy2/leverage-tiers?${q.toString()}`) as TierPreview; return [row.symbol, result] as const;
    })).then((rows) => { if (!cancelled) setTierPreviews(Object.fromEntries(rows)); }).catch((error) => { if (!cancelled) setMessage(error instanceof Error ? error.message : "Leverage tiers konden niet worden geladen."); }).finally(() => { if (!cancelled) setTierBusy(false); });
    return () => { cancelled = true; };
  }, [v.manualEnabled, v.manualSymbols, v.minLeverage, v.entryMarginLong, v.entryMarginShort, v.longDcaAmount, v.shortDcaAmount]);

  const selected = new Set(v.manualSymbols.map((row) => row.symbol));
  const marketQuery = marketSearch.trim().toUpperCase();
  const marketMatches = markets.filter((symbol) => !selected.has(symbol) && symbol.includes(marketQuery)).slice(0, 12);
  const directMarket = markets.find((symbol) => !selected.has(symbol) && (symbol === marketQuery || symbol === `${marketQuery}USDT`)) || (marketMatches.length === 1 ? marketMatches[0] : "");
  const addSymbol = (symbol: string) => { if (!symbol || selected.has(symbol)) return; change({ ...v, manualSymbols: [...v.manualSymbols, { symbol, side: "LONG" }] }); setMarketSearch(""); };
  const setSymbolSide = (symbol: string, side: ManualSide) => change({ ...v, manualSymbols: v.manualSymbols.map((row) => row.symbol === symbol ? { ...row, side } : row) });
  const removeSymbol = (symbol: string) => change({ ...v, manualSymbols: v.manualSymbols.filter((row) => row.symbol !== symbol) });

  async function action(kind: "save" | "simulate" | "start" | "stop") {
    setBusy(true); setMessage("");
    try {
      if (settings.longSlots + settings.shortSlots < 1 || settings.longSlots > MAX_SIDE_SLOTS || settings.shortSlots > MAX_SIDE_SLOTS || settings.maximumPositions > MAX_TOTAL_POSITIONS || settings.longSlots + settings.shortSlots !== settings.maximumPositions) throw new Error("Positielimieten zijn ongeldig: maximaal 100 totaal en LONG + SHORT moet exact gelijk zijn aan totaal.");
      if (settings.longSlots > 0 && settings.entryMarginLongUsd * settings.minimumLeverage < 5) throw new Error(`Instap LONG te laag: minimaal circa ${(5 / settings.minimumLeverage).toFixed(2)} USDT bij ${settings.minimumLeverage}x.`);
      if (settings.shortSlots > 0 && settings.entryMarginShortUsd * settings.minimumLeverage < 5) throw new Error(`Instap SHORT te laag: minimaal circa ${(5 / settings.minimumLeverage).toFixed(2)} USDT bij ${settings.minimumLeverage}x.`);
      if (settings.longDcaDistance <= 0 || settings.shortDcaDistance <= 0 || settings.longDcaDistance > .5 || settings.shortDcaDistance > .5) throw new Error("DCA-afstand moet tussen 0,01% en 50% liggen.");
      if (settings.longDcaMarginUsd <= 0 || settings.shortDcaMarginUsd <= 0) throw new Error("DCA-bedrag LONG/SHORT moet positief zijn.");
      if (settings.maxDcaLong > MAX_DCA || settings.maxDcaShort > MAX_DCA) throw new Error(`Max DCA mag maximaal ${MAX_DCA} zijn.`);
      if (v.tpMode === "PER_TRADE" && (settings.longTakeProfitValue <= 0 || settings.shortTakeProfitValue <= 0)) throw new Error("Take Profit LONG/SHORT moet positief zijn.");
      if (v.tpMode === "PORTFOLIO" && settings.portfolioTpPercent <= 0) throw new Error("Portfolio TP moet positief zijn.");
      if (v.manualEnabled && !v.manualSymbols.length) throw new Error("Selecteer minimaal één Aster USDT perpetual of zet handmatige selectie uit.");
      if (kind === "start" && v.manualEnabled) { const blocked = v.manualSymbols.map((row) => tierPreviews[row.symbol]).filter((row) => row?.entryOrderValid === false); if (blocked.length) throw new Error(`${blocked[0].symbol}: instapmargin voldoet niet aan de actuele Aster minimumorder.`); }
      const route = kind === "save" ? "settings" : kind; const method = kind === "save" ? "PUT" : "POST"; const body = kind === "start" ? { confirm: true, settings } : kind === "stop" ? { confirm: true } : { settings };
      const result = await authenticatedRequest(`/api/exchanges/aster/strategy2/${route}`, { method, body: JSON.stringify(body) }) as Record<string, unknown>;
      const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null; if (confirmed) { setConfirmedState(confirmed); onConfirmed(confirmed); }
      if (kind === "save") { setDirty(false); setMessage("Instellingen server-side opgeslagen. Actieve posities, fills, avg entry, DCA-counts en Portfolio TP-cycle zijn intact gebleven."); }
      else if (kind === "simulate") setMessage("Configuratie veilig gesimuleerd: 0 orders verzonden.");
      else if (kind === "stop") setMessage("Bot-stop door server verwerkt.");
      else { const firstTick = result.firstTick && typeof result.firstTick === "object" ? result.firstTick as Record<string, unknown> : null; const reason = String(firstTick?.reason || confirmed?.lastReason || "").trim(); setMessage(result.started === true && confirmed?.enabled === true ? `Bot server-side gestart${reason ? ` · ${reason}` : ""}.` : `Start niet bevestigd${reason ? `: ${reason}` : "."}`); }
      await Promise.resolve(onChanged());
    } catch (error) { setMessage(error instanceof Error ? error.message : "Actie mislukt"); }
    finally { setBusy(false); }
  }
  async function checkReadiness(startWhenReady = false) {
    setBusy(true); setMessage("");
    try { const result = await authenticatedRequest("/api/exchanges/aster/strategy2/readiness") as Record<string, unknown>; setReadiness(result); if (startWhenReady && Boolean(result.liveReady)) { setBusy(false); await action("start"); return; } setMessage(Boolean(result.liveReady) ? "Live-gereedheid server-side bevestigd." : "Readiness gecontroleerd; live-start is nog niet vrijgegeven."); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Readiness mislukt"); }
    finally { setBusy(false); }
  }

  const enabled = status.enabled === true; const liveReady = status.liveReady === true || (!status.pending && readiness?.liveReady === true);
  const activeLong = Number(rawReport.activeLong ?? state.longLegs ?? 0); const activeShort = Number(rawReport.activeShort ?? state.shortLegs ?? 0);
  const remainingLong = Number(rawReport.remainingLong ?? Math.max(0, n(v.longSlots) - activeLong)); const remainingShort = Number(rawReport.remainingShort ?? Math.max(0, n(v.shortSlots) - activeShort));
  const candidateCount = Number(rawReport.candidateCount ?? 0); const scannedCandidateCount = Number(rawReport.scannedCandidateCount ?? 0);
  const cycleStart = Number(cycle.cycleStartEquity || 0); const currentEquity = Number(cycle.currentEquity || 0); const target = cycleStart > 0 ? cycleStart * (1 + n(v.portfolioTp) / 100) : Number(cycle.targetEquity || 0);
  const portfolioWarning = v.tpMode === "PORTFOLIO" && target > 0 && currentEquity >= target;
  async function toggleLive() { if (status.pending || busy) return; if (dirty) { setMessage("Sla eerst de gewijzigde instellingen op; daarna kun je de bot direct aan- of uitzetten."); return; } if (enabled) return action("stop"); if (liveReady) return action("start"); return checkReadiness(true); }

  return <article id="strategy-2-maker" className="strategy-card strategy-two-card botsettings-ref">
    <div className="strategy-title-row"><div><span className="kicker">ASTER BOT</span><h2>Botinstellingen</h2></div><span className={`strategy-state ${enabled ? "on" : ""}`}>{status.pending ? "BEZIG" : enabled ? "AAN" : "UIT"}</span></div>
    <div className="strategy-facts"><span>{v.longSlots} LONG slots</span><span>{v.shortSlots} SHORT slots</span><span>{Number(v.longSlots) + Number(v.shortSlots)} totaal</span><span>CROSS</span></div>
    <div className="strategy-message compact-scan"><b>Botposities</b><span>{activeLong}L · {activeShort}S</span><b>Vrije botslots</b><span>{remainingLong}L · {remainingShort}S</span><small>{candidateCount} kandidaten{scannedCandidateCount ? ` · ${scannedCandidateCount} onderzocht` : ""}</small>{dirty && <em>Niet opgeslagen</em>}</div>
    <div className={`strategy-power-control ${enabled ? "enabled" : "ready"}`}><span><b>Aster live bot</b><small>{dirty ? "eerst wijzigingen opslaan" : enabled ? "server bevestigt actief" : "uit"}</small></span><button type="button" role="switch" aria-checked={enabled} disabled={busy || status.pending} onClick={toggleLive}><i />{busy ? "Bezig…" : enabled ? "Uitschakelen" : "Inschakelen"}</button></div>

    <div className="maker-input compact-settings-grid">
      <Field label="Botnaam" value={v.name} set={(value) => change({ ...v, name: value })} text />
      <Field label="Top-N volume" value={v.universe} set={(value) => change({ ...v, universe: value })} />
      <div className="position-settings-grid"><Field label="Totaal posities" value={totalDraft ?? v.positions} set={setTotalDraft} onBlur={commitTotal} /><Field label="LONG slots" value={longDraft ?? v.longSlots} set={setLongDraft} onBlur={commitLong} /><Field label="SHORT slots" value={shortDraft ?? v.shortSlots} set={setShortDraft} onBlur={commitShort} /></div>
      <Field label="Minimum leverage" value={v.minLeverage} set={(value) => change({ ...v, minLeverage: value })} />

      <section className="side-settings-block">
        <div className="side-settings-head"><div><small>GEÏNTEGREERD</small><b>LONG / SHORT · DCA & Take Profit</b></div><div className="tp-tabs">{(["PER_TRADE", "PORTFOLIO", "OFF"] as TpMode[]).map((mode) => <button key={mode} type="button" className={v.tpMode === mode ? "active" : ""} onClick={() => change({ ...v, tpMode: mode })}>{mode === "PER_TRADE" ? "Per trade" : mode === "PORTFOLIO" ? "Portfolio" : "Uit"}</button>)}</div></div>
        {v.tpMode === "PORTFOLIO" && <div className="portfolio-tp-row"><Field label="Portfolio TP (%)" value={v.portfolioTp} set={(value) => change({ ...v, portfolioTp: value })} /><span><small>Cycle start</small><b>{cycleStart ? `$${cycleStart.toFixed(2)}` : "—"}</b></span><span><small>Target</small><b>{target ? `$${target.toFixed(2)}` : "—"}</b></span><span><small>Equity</small><b>{currentEquity ? `$${currentEquity.toFixed(2)}` : "—"}</b></span>{portfolioWarning && <em>Target ligt al onder/huidige equity; na opslaan kan de bestaande Portfolio TP-cycle direct uitvoeren.</em>}</div>}
        {v.tpMode === "OFF" && <p className="tp-off-note">Automatische TP uit. DCA en overige strategie blijven actief.</p>}
        <div className="side-columns">
          <section className="side-card long"><b>LONG</b><Field label="Instap LONG" value={v.entryMarginLong} set={(value) => change({ ...v, entryMarginLong: value })} suffix="USDT" /><Field label="DCA-afstand LONG" value={v.longDcaDistance} set={(value) => change({ ...v, longDcaDistance: value })} suffix="%" /><Field label="DCA-bedrag LONG" value={v.longDcaAmount} set={(value) => change({ ...v, longDcaAmount: value })} suffix="USDT" /><Field label="Max DCA LONG" value={v.maxDcaLong} set={(value) => change({ ...v, maxDcaLong: value })} /><Field label="Take Profit LONG" value={v.longTp} set={(value) => change({ ...v, longTp: value })} suffix="%" disabled={v.tpMode !== "PER_TRADE"} /></section>
          <section className="side-card short"><b>SHORT</b><Field label="Instap SHORT" value={v.entryMarginShort} set={(value) => change({ ...v, entryMarginShort: value })} suffix="USDT" /><Field label="DCA-afstand SHORT" value={v.shortDcaDistance} set={(value) => change({ ...v, shortDcaDistance: value })} suffix="%" /><Field label="DCA-bedrag SHORT" value={v.shortDcaAmount} set={(value) => change({ ...v, shortDcaAmount: value })} suffix="USDT" /><Field label="Max DCA SHORT" value={v.maxDcaShort} set={(value) => change({ ...v, maxDcaShort: value })} /><Field label="Take Profit SHORT" value={v.shortTp} set={(value) => change({ ...v, shortTp: value })} suffix="%" disabled={v.tpMode !== "PER_TRADE"} /></section>
        </div>
      </section>

      <label className="manual-symbol-toggle"><span><b>Zelf munten kiezen</b><small>UIT = automatische Top-N. AAN = uitsluitend jouw geselecteerde Aster USDT perpetuals.</small></span><input type="checkbox" checked={v.manualEnabled} onChange={(event) => change({ ...v, manualEnabled: event.target.checked })} /></label>
      {v.manualEnabled && <div className="manual-symbol-picker"><div className="manual-symbol-search"><input value={marketSearch} onChange={(event) => setMarketSearch(event.target.value.toUpperCase())} onFocus={() => { if (!markets.length) void loadMarkets(); }} placeholder="Zoek BTC, HYPE, BTCUSDT…" /><button type="button" disabled={marketBusy || !marketQuery || !directMarket} onClick={() => { if (directMarket) addSymbol(directMarket); }}>+ toevoegen</button></div>{marketQuery && <div className="manual-symbol-results">{marketBusy ? <small>Markten laden…</small> : marketLoadError ? <button type="button" onClick={() => void loadMarkets()}>Laden mislukt · opnieuw proberen</button> : marketMatches.length ? marketMatches.map((symbol) => <button type="button" key={symbol} onClick={() => addSymbol(symbol)}>{symbol}<i>+</i></button>) : <small>Geen actieve Aster USDT perpetual gevonden.</small>}</div>}<div className="manual-symbol-selected">{v.manualSymbols.map((row) => { const preview = tierPreviews[row.symbol]; const leverage = preview?.entryPlan?.leverage || preview?.currentLeverage; return <div key={row.symbol}><div><b>{row.symbol}</b>{leverage ? <small>{leverage}×</small> : tierBusy ? <small>…</small> : null}<span><button type="button" className={row.side === "LONG" ? "active long" : ""} onClick={() => setSymbolSide(row.symbol, "LONG")}>LONG</button><button type="button" className={row.side === "SHORT" ? "active short" : ""} onClick={() => setSymbolSide(row.symbol, "SHORT")}>SHORT</button></span><button type="button" className="remove" onClick={() => removeSymbol(row.symbol)}>×</button></div>{preview?.entryOrderValid === false && <small className="inline-warning">Instapmargin te laag. Advies minimaal ${Number(preview.suggestedEntryMarginUsd ?? preview.minimumEntryMarginUsd ?? 0).toFixed(2)}.</small>}</div>; })}</div><p className="manual-symbol-summary">{v.manualSymbols.length} geselecteerd · {v.manualSymbols.filter((row) => row.side === "LONG").length} LONG · {v.manualSymbols.filter((row) => row.side === "SHORT").length} SHORT</p></div>}
    </div>

    <div className="maker-nav"><button disabled={busy || !dirty} onClick={() => action("save")}>Instellingen opslaan</button><button disabled={busy} onClick={() => action("simulate")}>Veilig simuleren</button><button disabled={busy} onClick={() => checkReadiness(false)}>Readiness controleren</button></div>
    {readiness && <p className="strategy-message">Readiness: {Boolean(state.liveReady) || Boolean(readiness.liveReady) ? "LIVE READY" : "nog niet live ready"}</p>}{message && <p className="strategy-message">{message}</p>}

    <style>{`
      #strategy-2-maker.botsettings-ref{--gold:#d6b55a;--green:#21d69a;--pink:#ff7892;background:radial-gradient(circle at 82% 4%,rgba(18,188,124,.13),transparent 34%),linear-gradient(180deg,#07110e,#030706);border:1px solid rgba(214,181,90,.54);border-radius:17px;padding:11px;box-shadow:0 18px 48px rgba(0,0,0,.36);overflow:hidden}
      #strategy-2-maker.botsettings-ref .strategy-title-row{margin-bottom:5px;align-items:center} #strategy-2-maker.botsettings-ref .strategy-title-row h2{margin:1px 0 0;font-size:21px;line-height:1} #strategy-2-maker.botsettings-ref .kicker{color:var(--gold);font-size:9px;letter-spacing:.16em}
      #strategy-2-maker.botsettings-ref .strategy-facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;margin:0 0 6px} #strategy-2-maker.botsettings-ref .strategy-facts span{padding:4px 3px;border:1px solid rgba(214,181,90,.22);border-radius:8px;background:rgba(255,255,255,.02);font-size:8.5px;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      #strategy-2-maker.botsettings-ref .compact-scan{display:grid;grid-template-columns:auto 1fr auto 1fr;gap:3px 6px;padding:5px 7px;margin:0 0 6px;border:1px solid rgba(33,214,154,.18);border-radius:10px;background:rgba(3,17,13,.82);font-size:9px;align-items:center} #strategy-2-maker.botsettings-ref .compact-scan small,#strategy-2-maker.botsettings-ref .compact-scan em{grid-column:1/-1;font-size:8px;opacity:.72}
      #strategy-2-maker.botsettings-ref .strategy-power-control{padding:6px 8px;min-height:43px;margin-bottom:6px;border:1px solid rgba(214,181,90,.25);border-radius:11px;background:rgba(7,25,19,.94)} #strategy-2-maker.botsettings-ref .strategy-power-control b{font-size:11px} #strategy-2-maker.botsettings-ref .strategy-power-control small{font-size:8px} #strategy-2-maker.botsettings-ref .strategy-power-control button{min-height:31px;padding:0 9px;border-radius:9px;font-size:9px}
      #strategy-2-maker.botsettings-ref .compact-settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px} #strategy-2-maker.botsettings-ref .compact-settings-grid>label,#strategy-2-maker.botsettings-ref .position-settings-grid label,#strategy-2-maker.botsettings-ref .side-card label,#strategy-2-maker.botsettings-ref .portfolio-tp-row label{margin:0;gap:2px;font-size:9px}
      #strategy-2-maker.botsettings-ref .compact-settings-grid input{height:33px;min-width:0;padding:0 8px;border-radius:8px;border:1px solid rgba(214,181,90,.27);background:rgba(0,0,0,.28);font-size:12px} #strategy-2-maker.botsettings-ref .compact-settings-grid input:focus{border-color:rgba(33,214,154,.74);box-shadow:0 0 0 2px rgba(33,214,154,.09)}
      #strategy-2-maker.botsettings-ref .position-settings-grid{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}
      #strategy-2-maker.botsettings-ref .side-settings-block{grid-column:1/-1;display:grid;gap:6px;padding:7px;border:1px solid rgba(214,181,90,.32);border-radius:12px;background:linear-gradient(180deg,rgba(5,22,16,.96),rgba(2,10,8,.96))}
      #strategy-2-maker.botsettings-ref .side-settings-head{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:end;gap:7px} #strategy-2-maker.botsettings-ref .side-settings-head>div:first-child{display:grid;gap:1px} #strategy-2-maker.botsettings-ref .side-settings-head small{font-size:7px;letter-spacing:.13em;color:var(--gold)} #strategy-2-maker.botsettings-ref .side-settings-head b{font-size:11px}
      #strategy-2-maker.botsettings-ref .tp-tabs{display:grid;grid-template-columns:repeat(3,1fr);gap:3px} #strategy-2-maker.botsettings-ref .tp-tabs button{min-height:28px;padding:0 6px;border-radius:8px;border:1px solid rgba(214,181,90,.20);background:#08100d;color:#9aa69f;font-size:8px;font-weight:800} #strategy-2-maker.botsettings-ref .tp-tabs button.active{color:#8ff4c6;border-color:rgba(33,214,154,.64);background:rgba(33,214,154,.11)}
      #strategy-2-maker.botsettings-ref .side-columns{display:grid;grid-template-columns:1fr 1fr;gap:5px} #strategy-2-maker.botsettings-ref .side-card{display:grid;gap:4px;padding:6px;border-radius:10px;background:rgba(255,255,255,.018)} #strategy-2-maker.botsettings-ref .side-card.long{border:1px solid rgba(33,214,154,.33)} #strategy-2-maker.botsettings-ref .side-card.short{border:1px solid rgba(255,120,146,.34)} #strategy-2-maker.botsettings-ref .side-card>b{font-size:10px} #strategy-2-maker.botsettings-ref .side-card.long>b{color:#67edb5} #strategy-2-maker.botsettings-ref .side-card.short>b{color:#ff90a4} #strategy-2-maker.botsettings-ref .side-card label span.field-wrap{border-color:inherit}
      #strategy-2-maker.botsettings-ref .portfolio-tp-row{display:grid;grid-template-columns:1.2fr repeat(3,.8fr);gap:5px;align-items:end;padding:5px;border-radius:9px;background:rgba(62,112,161,.08);border:1px solid rgba(95,151,207,.18)} #strategy-2-maker.botsettings-ref .portfolio-tp-row>span{display:grid;gap:1px;font-size:8px} #strategy-2-maker.botsettings-ref .portfolio-tp-row>span b{font-size:10px} #strategy-2-maker.botsettings-ref .portfolio-tp-row em{grid-column:1/-1;color:#ffc18f;font-size:8px;font-style:normal} #strategy-2-maker.botsettings-ref .tp-off-note{margin:0;padding:5px 6px;border-radius:8px;background:rgba(255,255,255,.03);font-size:8.5px;opacity:.8}
      #strategy-2-maker.botsettings-ref .manual-symbol-toggle{grid-column:1/-1;min-height:41px;margin:0;padding:6px 8px;border-radius:10px;border:1px solid rgba(214,181,90,.22)} #strategy-2-maker.botsettings-ref .manual-symbol-toggle b{font-size:10px} #strategy-2-maker.botsettings-ref .manual-symbol-toggle small{font-size:8px;line-height:1.2}
      #strategy-2-maker.botsettings-ref .manual-symbol-picker{grid-column:1/-1;margin:0} #strategy-2-maker.botsettings-ref .maker-nav{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;margin-top:7px;padding-bottom:max(3px,env(safe-area-inset-bottom))} #strategy-2-maker.botsettings-ref .maker-nav button{min-height:36px;padding:6px;border-radius:9px;font-size:8.5px;line-height:1.12} #strategy-2-maker.botsettings-ref .maker-nav button:first-child{border-color:rgba(33,214,154,.55);background:linear-gradient(180deg,rgba(33,214,154,.18),rgba(33,214,154,.07))}
      @media(max-width:430px){#strategy-2-maker.botsettings-ref{padding:9px;border-radius:14px}#strategy-2-maker.botsettings-ref .side-settings-head{grid-template-columns:1fr}#strategy-2-maker.botsettings-ref .tp-tabs{width:100%}#strategy-2-maker.botsettings-ref .portfolio-tp-row{grid-template-columns:1fr 1fr}#strategy-2-maker.botsettings-ref .side-columns{gap:4px}#strategy-2-maker.botsettings-ref .side-card{padding:5px}#strategy-2-maker.botsettings-ref .compact-settings-grid input{height:31px;font-size:11px}}
      @media(max-width:350px){#strategy-2-maker.botsettings-ref .side-columns{grid-template-columns:1fr}#strategy-2-maker.botsettings-ref .maker-nav{grid-template-columns:1fr}}
    `}</style>
  </article>;
}

function Field({ label, value, set, text = false, onBlur, disabled = false, suffix = "" }: { label: string; value: string; set: (value: string) => void; text?: boolean; onBlur?: () => void; disabled?: boolean; suffix?: string }) {
  return <label>{label}<span className="field-wrap" style={{ display: "flex", alignItems: "center", border: "1px solid rgba(214,181,90,.27)", borderRadius: 8, background: "rgba(0,0,0,.28)", overflow: "hidden", opacity: disabled ? .5 : 1 }}><input disabled={disabled} inputMode={text ? undefined : "decimal"} value={value} onChange={(event) => set(text ? event.target.value : event.target.value.replace(",", "."))} onBlur={onBlur} style={{ width: "100%", border: 0, background: "transparent", boxShadow: "none" }} />{suffix && <b style={{ paddingRight: 6, fontSize: 7.5, color: "#7e8a84" }}>{suffix}</b>}</span></label>;
}
