"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { strategy2ServerStatus } from "@/lib/aster-strategy2-server-status.mjs";

type ManualSide = "LONG" | "SHORT";
type ManualSymbol = { symbol: string; side: ManualSide };
type TierPreview = {
  symbol: string;
  tiers: Array<{ floor: number; cap: number; maxLeverage: number }>;
  entryPlan?: { leverage: number } | null;
  currentLeverage?: number;
  minimumExecutableNotionalUsd?: number;
  minimumEntryMarginUsd?: number;
  suggestedEntryMarginUsd?: number;
  configuredEntryMarginUsd?: number;
  entryOrderValid?: boolean;
};
type Values = {
  name: string; universe: string; positions: string; longSlots: string; shortSlots: string;
  minLeverage: string; entryMargin: string; dcaDistance: string; dcaMargin: string;
  maxDca: string; tp: string; tpEnabled: boolean; mode: "paper" | "live";
  manualEnabled: boolean; manualSymbols: ManualSymbol[];
};

const initial: Values = {
  name: "Aster Multi DCA", universe: "30", positions: "30", longSlots: "20", shortSlots: "10",
  minLeverage: "50", entryMargin: "5", dcaDistance: "0.30", dcaMargin: "2", maxDca: "3", tp: "1.5", tpEnabled: true, mode: "live",
  manualEnabled: false, manualSymbols: [],
};
const MAX_DCA = 500;
const n = (value: string) => Number(value) || 0;
const clampInt = (value: number, min: number, max: number) => Math.max(min, Math.min(max, Math.round(value || 0)));
const parseManualSymbols = (value: unknown): ManualSymbol[] => Array.isArray(value) ? value.flatMap((row) => {
  if (!row || typeof row !== "object") return [];
  const item = row as Record<string, unknown>;
  const symbol = String(item.symbol || "").toUpperCase();
  const side = String(item.side || "").toUpperCase();
  return symbol && (side === "LONG" || side === "SHORT") ? [{ symbol, side: side as ManualSide }] : [];
}) : [];

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
  const [tierPreviews, setTierPreviews] = useState<Record<string, TierPreview>>({});
  const [tierBusy, setTierBusy] = useState(false);
  const [totalDraft, setTotalDraft] = useState<string | null>(null);
  const snapshotState = (snapshot?.strategy2 && typeof snapshot.strategy2 === "object" ? snapshot.strategy2 : {}) as Record<string, unknown>;
  const status = strategy2ServerStatus(snapshotState, confirmedState, serverConfirmed);
  const state = status.state as Record<string, unknown>;

  useEffect(() => {
    if (dirty) return;
    const x = state.settings as Record<string, unknown> | undefined;
    if (!x || String(x.engine || x.strategyKind) !== "multi_bb_v1") return;
    const longSlots = clampInt(Number(x.longSlots ?? 20), 0, 25);
    const shortSlots = clampInt(Number(x.shortSlots ?? 10), 0, 25);
    setV({
      name: String(x.name || initial.name), universe: String(x.universeTopN ?? 30), positions: String(Math.min(50, longSlots + shortSlots)),
      longSlots: String(longSlots), shortSlots: String(shortSlots), minLeverage: String(x.minimumLeverage ?? 50),
      entryMargin: String(x.entrySizingMode === "margin" ? (x.entryMarginUsd ?? 5) : (x.entryNotionalUsd ?? x.baseNotional ?? 5)),
      dcaDistance: String(Number(x.dcaDistance ?? .003) * 100), dcaMargin: String(x.dcaMarginUsd ?? 2), maxDca: String(clampInt(Number(x.maxDca ?? 3), 0, MAX_DCA)),
      tp: String(Number(x.takeProfit ?? .015) * 100), tpEnabled: x.takeProfitEnabled !== false, mode: x.mode === "paper" ? "paper" : "live",
      manualEnabled: x.manualSymbolSelectionEnabled === true, manualSymbols: parseManualSymbols(x.manualSymbols),
    });
    setTotalDraft(null);
  }, [state.settings, dirty]);

  const change = (next: Values) => { setV(next); setDirty(true); setMessage(""); };
  const settings = useMemo(() => {
    const longSlots = clampInt(n(v.longSlots), 0, 25);
    const shortSlots = clampInt(n(v.shortSlots), 0, 25);
    return {
      engine: "multi_bb_v1", strategyKind: "multi_bb_v1", name: v.name, mode: v.mode,
      universeTopN: Math.max(1, Math.round(n(v.universe))), maximumPositions: Math.min(50, longSlots + shortSlots), longSlots, shortSlots,
      minimumLeverage: Math.max(1, Math.round(n(v.minLeverage))),
      entryMarginUsd: n(v.entryMargin),
      entryNotionalUsd: n(v.entryMargin) * Math.max(1, Math.round(n(v.minLeverage))),
      entrySizingMode: "margin",
      dcaDistance: n(v.dcaDistance) / 100, dcaMarginUsd: n(v.dcaMargin), maxDca: clampInt(n(v.maxDca), 0, MAX_DCA), unlimitedDca: false,
      takeProfit: n(v.tp) / 100, takeProfitEnabled: v.tpEnabled, entryMode: "immediate_fill", marginMode: "cross", autoRestart: true,
      manualSymbolSelectionEnabled: v.manualEnabled, manualSymbols: v.manualSymbols,
    };
  }, [v]);

  const setTotal = (raw: string) => {
    const total = clampInt(Number(raw), 1, 50);
    const oldLong = clampInt(n(v.longSlots), 0, 25);
    const oldShort = clampInt(n(v.shortSlots), 0, 25);
    const oldTotal = Math.max(1, oldLong + oldShort);
    let long = Math.min(25, Math.round(total * oldLong / oldTotal));
    let short = Math.min(25, total - long);
    if (long + short < total) long = Math.min(25, total - short);
    change({ ...v, positions: String(long + short), longSlots: String(long), shortSlots: String(short) });
  };
  const commitTotal = () => {
    const raw = String(totalDraft ?? v.positions).trim();
    setTotalDraft(null);
    if (!raw) return;
    setTotal(raw);
  };
  const setLong = (raw: string) => { const long = clampInt(Number(raw), 0, 25); const short = clampInt(n(v.shortSlots), 0, 25); change({ ...v, positions: String(long + short), longSlots: String(long), shortSlots: String(short) }); };
  const setShort = (raw: string) => { const short = clampInt(Number(raw), 0, 25); const long = clampInt(n(v.longSlots), 0, 25); change({ ...v, positions: String(long + short), longSlots: String(long), shortSlots: String(short) }); };

  async function loadMarkets() {
    if (marketBusy) return;
    setMarketAttempted(true); setMarketBusy(true);
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/focus/markets") as Record<string, unknown>;
      const ranking = Array.isArray(result.ranking) ? result.ranking : [];
      setMarkets(ranking.flatMap((row) => row && typeof row === "object" ? [String((row as Record<string, unknown>).symbol || "").toUpperCase()] : []).filter(Boolean));
    } catch (error) { setMessage(error instanceof Error ? error.message : "Aster-markten konden niet worden geladen."); }
    finally { setMarketBusy(false); }
  }
  useEffect(() => { if (v.manualEnabled && !marketAttempted) void loadMarkets(); }, [v.manualEnabled, marketAttempted]);
  useEffect(() => {
    if (!v.manualEnabled || !v.manualSymbols.length) { setTierPreviews({}); return; }
    let cancelled = false; setTierBusy(true);
    void Promise.all(v.manualSymbols.map(async ({ symbol }) => {
      const q = new URLSearchParams({ symbol, minimumLeverage: String(Math.max(1, Math.round(n(v.minLeverage)))), entryMarginUsd: String(Math.max(.01, n(v.entryMargin))), dcaMarginUsd: String(Math.max(.01, n(v.dcaMargin))) });
      const result = await authenticatedRequest(`/api/exchanges/aster/strategy2/leverage-tiers?${q.toString()}`) as TierPreview;
      return [symbol, result] as const;
    })).then((rows) => { if (!cancelled) setTierPreviews(Object.fromEntries(rows)); }).catch((error) => { if (!cancelled) setMessage(error instanceof Error ? error.message : "Leverage tiers konden niet worden geladen."); }).finally(() => { if (!cancelled) setTierBusy(false); });
    return () => { cancelled = true; };
  }, [v.manualEnabled, v.manualSymbols, v.minLeverage, v.entryMargin, v.dcaMargin]);

  const selected = new Set(v.manualSymbols.map((row) => row.symbol));
  const marketMatches = markets.filter((symbol) => !selected.has(symbol) && symbol.includes(marketSearch.trim().toUpperCase())).slice(0, 12);
  const addSymbol = (symbol: string) => { if (!symbol || selected.has(symbol)) return; change({ ...v, manualSymbols: [...v.manualSymbols, { symbol, side: "LONG" }] }); setMarketSearch(""); };
  const setSymbolSide = (symbol: string, side: ManualSide) => change({ ...v, manualSymbols: v.manualSymbols.map((row) => row.symbol === symbol ? { ...row, side } : row) });
  const removeSymbol = (symbol: string) => change({ ...v, manualSymbols: v.manualSymbols.filter((row) => row.symbol !== symbol) });

  async function action(kind: "save" | "simulate" | "start" | "stop") {
    setBusy(true); setMessage("");
    try {
      if (settings.longSlots + settings.shortSlots < 1 || settings.longSlots > 25 || settings.shortSlots > 25 || settings.maximumPositions > 50) throw new Error("Positielimieten zijn ongeldig: maximaal 25 LONG + 25 SHORT (50 totaal).");
      if (settings.maxDca > MAX_DCA) throw new Error(`Globale DCA-limiet mag maximaal ${MAX_DCA} zijn.`);
      if (settings.takeProfitEnabled && (!Number.isFinite(Number(v.tp.replace(",", "."))) || Number(v.tp.replace(",", ".")) <= 0)) throw new Error("Take Profit moet een positief numeriek percentage zijn.");
      if (settings.entryMarginUsd * settings.minimumLeverage < 5) throw new Error(`Startmargin te laag: ${settings.entryMarginUsd} USDT × ${settings.minimumLeverage} is minder dan de Aster-minimumorder van circa 5 USDT. Verhoog de startmargin naar minimaal ${(5 / settings.minimumLeverage).toFixed(2)} USDT; per markt kan iets meer nodig zijn.`);
      if (v.manualEnabled && !v.manualSymbols.length) throw new Error("Selecteer minimaal één Aster USDT perpetual of zet handmatige selectie uit.");
      if (kind === "start" && v.manualEnabled) {
        const blocked = v.manualSymbols.map((row) => tierPreviews[row.symbol]).filter((row) => row?.entryOrderValid === false);
        if (blocked.length) throw new Error(`${blocked[0].symbol}: startmargin voldoet niet aan de actuele Aster minimumorder.`);
      }
      const route = kind === "save" ? "settings" : kind;
      const method = kind === "save" ? "PUT" : "POST";
      const body = kind === "start" ? { confirm: true, settings } : kind === "stop" ? { confirm: true } : { settings };
      const result = await authenticatedRequest(`/api/exchanges/aster/strategy2/${route}`, { method, body: JSON.stringify(body) }) as Record<string, unknown>;
      const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null;
      if (confirmed) { setConfirmedState(confirmed); onConfirmed(confirmed); }
      if (kind === "save") { setDirty(false); setMessage("Instellingen server-side opgeslagen en bevestigd."); }
      else if (kind === "simulate") setMessage("Configuratie gesimuleerd: 0 orders verzonden.");
      else if (kind === "stop") setMessage("Bot-stop door server verwerkt.");
      else {
        const firstTick = result.firstTick && typeof result.firstTick === "object" ? result.firstTick as Record<string, unknown> : null;
        const reason = String(firstTick?.reason || confirmed?.lastReason || "").trim();
        setMessage(result.started === true && confirmed?.enabled === true ? `Bot server-side gestart${reason ? ` · ${reason}` : ""}.` : `Start niet bevestigd${reason ? `: ${reason}` : "."}`);
      }
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

  const enabled = status.enabled === true;
  const liveReady = status.liveReady === true || (!status.pending && readiness?.liveReady === true);
  const rawReport = (state.multiBb && typeof state.multiBb === "object" ? state.multiBb : {}) as Record<string, unknown>;
  const settingsVersion = Number((state.settings as Record<string, unknown> | undefined)?.version ?? state.configVersion ?? 0);
  const reportVersion = Number(rawReport.configVersion ?? 0);
  // Legacy servers do not version their reports yet. Keep their live counts
  // and candidate ranking, but never show a minimum-order rejection when its
  // configured notional differs from the settings currently on screen.
  const report = rawReport;
  const rawEntryReason = String(report.entryReason ?? state.lastReason ?? "").trim();
  const reportedNotional = rawEntryReason.match(/ingesteld bedrag\s+([0-9]+(?:\.[0-9]+)?)\s+USD/i);
  const reasonMatchesSettings = reportVersion > 0
    ? reportVersion === settingsVersion
    : !reportedNotional || Math.abs(Number(reportedNotional[1]) - settings.entryNotionalUsd) < 0.000001;
  const activeLong = Number(report.activeLong ?? state.longLegs ?? 0);
  const activeShort = Number(report.activeShort ?? state.shortLegs ?? 0);
  const remainingLong = Number(report.remainingLong ?? Math.max(0, n(v.longSlots) - activeLong));
  const remainingShort = Number(report.remainingShort ?? Math.max(0, n(v.shortSlots) - activeShort));
  const entryReason = reasonMatchesSettings ? rawEntryReason : "";
  const candidateCount = Number(report.candidateCount ?? (Array.isArray(report.rankedTopN) ? report.rankedTopN.length : 0));
  const scannedCandidateCount = Number(report.scannedCandidateCount ?? 0);
  const minimumOrderRejectedCount = Number(report.minimumOrderRejectedCount ?? 0);
  const nextRequiredEntryMarginUsd = Number(report.nextRequiredEntryMarginUsd ?? 0);
  const accountPositionCount = Number(report.accountPositionCount ?? 0);
  const untrackedAccountPositionCount = Number(report.untrackedAccountPositionCount ?? 0);
  const scanSummary = scannedCandidateCount > 0
    ? `${candidateCount} kandidaten · ${scannedCandidateCount} onderzocht${minimumOrderRejectedCount > 0 ? ` · ${minimumOrderRejectedCount} onder minimumorder` : ""}`
    : `${candidateCount} kandidaten`;
  async function toggleLive() { if (status.pending) return; if (busy) return; if (dirty) { setMessage("Sla eerst de gewijzigde instellingen op; daarna kun je de bot direct aan- of uitzetten."); return; } if (enabled) return action("stop"); if (liveReady) return action("start"); return checkReadiness(true); }

  return <article id="strategy-2-maker" className="strategy-card strategy-two-card">
    <div className="strategy-title-row"><div><span className="kicker">ASTER BOT</span><h2>Botinstellingen</h2></div><span className={`strategy-state ${enabled ? "on" : ""}`}>{status.pending ? "BEZIG" : enabled ? "AAN" : "UIT"}</span></div>
    <p className="strategy-intro">Alle actieve instellingen staan direct hieronder. Geen wizard; de door de server bevestigde configuratie is leidend.</p>
    <div className="strategy-facts"><span>{v.longSlots} LONG / 25</span><span>{v.shortSlots} SHORT / 25</span><span>{Number(v.longSlots) + Number(v.shortSlots)} / 50 totaal</span><span>DCA globaal max {v.maxDca}</span><span>TP {v.tpEnabled ? `${v.tp}%` : "UIT"}</span><span>CROSS</span></div>
    <div className="strategy-message compact-scan"><b>Botposities:</b> {activeLong}L · {activeShort}S <b>Vrije botslots:</b> {remainingLong}L · {remainingShort}S <small>{scanSummary} · dashboard telt alle Aster-posities</small>{accountPositionCount > 0 && <small>{accountPositionCount} exchangeposities{untrackedAccountPositionCount > 0 ? ` · ${untrackedAccountPositionCount} niet gekoppeld aan Strategy 2` : ""}</small>}{dirty && <b>Niet opgeslagen</b>}{entryReason && remainingLong + remainingShort > 0 && <span className="entry-hold-reason"><b>Actuele reden:</b> {entryReason}{nextRequiredEntryMarginUsd > settings.entryMarginUsd ? ` · Benodigd voor volgende kandidaat: circa ${nextRequiredEntryMarginUsd.toFixed(2)} USDT.` : ""}</span>}</div>

    <div className={`strategy-power-control ${enabled ? "enabled" : "ready"}`}><span><b>Aster live bot</b><small>{dirty ? "eerst wijzigingen opslaan" : status.pending ? "server verwerkt wijziging…" : enabled ? "server bevestigt actief" : "uit"}</small></span><button type="button" role="switch" aria-checked={enabled} disabled={busy || status.pending} onClick={toggleLive}><i />{busy ? "Bezig…" : enabled ? "Uitschakelen" : "Inschakelen"}</button></div>

    <div className="maker-input compact-settings-grid">
      <Field label="Botnaam" value={v.name} set={(value) => change({ ...v, name: value })} text />
      <Field label="Top-N volume" value={v.universe} set={(value) => change({ ...v, universe: value })} />
      <div className="position-settings-grid">
        <Field label="Totaal posities (max 50)" value={totalDraft ?? v.positions} set={setTotalDraft} onBlur={commitTotal} />
        <Field label="LONG slots (max 25)" value={v.longSlots} set={setLong} />
        <Field label="SHORT slots (max 25)" value={v.shortSlots} set={setShort} />
      </div>
      <Field label="Minimum leverage (×)" value={v.minLeverage} set={(value) => change({ ...v, minLeverage: value })} />
      <Field label="Start margin (USDT)" value={v.entryMargin} set={(value) => change({ ...v, entryMargin: value })} />
      <Field label="DCA afstand (%)" value={v.dcaDistance} set={(value) => change({ ...v, dcaDistance: value })} />
      <Field label="DCA margin (USDT)" value={v.dcaMargin} set={(value) => change({ ...v, dcaMargin: value })} />
      <Field label={`Globale DCA-limiet (0–${MAX_DCA})`} value={v.maxDca} set={(value) => change({ ...v, maxDca: value })} />
      <div className={`tp-setting ${v.tpEnabled ? "enabled" : "disabled"}`}>
        <label className="tp-toggle-row"><span><b>Take Profit</b><small>{v.tpEnabled ? "Automatisch sluiten is actief" : "Automatisch sluiten is volledig uit"}</small></span><button type="button" role="switch" aria-checked={v.tpEnabled} className="tp-toggle" onClick={() => change({ ...v, tpEnabled: !v.tpEnabled })}><i />{v.tpEnabled ? "AAN" : "UIT"}</button></label>
        <Field label="Take Profit (%)" value={v.tp} set={(value) => change({ ...v, tp: value })} disabled={!v.tpEnabled} />
      </div>

      <label className="manual-symbol-toggle"><span><b>Zelf munten kiezen</b><small>UIT = automatische Top-N. AAN = uitsluitend jouw geselecteerde Aster USDT perpetuals.</small></span><input type="checkbox" checked={v.manualEnabled} onChange={(event) => change({ ...v, manualEnabled: event.target.checked })} /></label>
      {v.manualEnabled && <div className="manual-symbol-picker">
        <div className="manual-symbol-search"><input value={marketSearch} onChange={(event) => setMarketSearch(event.target.value.toUpperCase())} onFocus={() => { if (!markets.length) void loadMarkets(); }} placeholder="Zoek BTC, HYPE, BTCUSDT…" /><button type="button" disabled={marketBusy || !marketSearch.trim()} onClick={() => { const exact = markets.find((symbol) => symbol === marketSearch.trim().toUpperCase()); if (exact) addSymbol(exact); }}>+ toevoegen</button></div>
        {marketSearch.trim() && <div className="manual-symbol-results">{marketBusy ? <small>Markten laden…</small> : marketMatches.length ? marketMatches.map((symbol) => <button type="button" key={symbol} onClick={() => addSymbol(symbol)}>{symbol}<i>+</i></button>) : <small>Geen actieve Aster USDT perpetual gevonden.</small>}</div>}
        <div className="manual-symbol-selected">{v.manualSymbols.map((row) => { const preview = tierPreviews[row.symbol]; const leverage = preview?.entryPlan?.leverage || preview?.currentLeverage; return <div key={row.symbol} style={{ display: "grid", gap: 6 }}><div style={{ display: "flex", alignItems: "center", gap: 8 }}><b>{row.symbol}</b>{leverage ? <small>max/gekozen {leverage}×</small> : tierBusy ? <small>leverage laden…</small> : null}<span><button type="button" className={row.side === "LONG" ? "active long" : ""} onClick={() => setSymbolSide(row.symbol, "LONG")}>LONG</button><button type="button" className={row.side === "SHORT" ? "active short" : ""} onClick={() => setSymbolSide(row.symbol, "SHORT")}>SHORT</button></span><button type="button" className="remove" onClick={() => removeSymbol(row.symbol)} aria-label={`${row.symbol} verwijderen`}>×</button></div>{preview?.entryOrderValid === false && <small className="inline-warning">Startmargin te laag voor de actuele Aster minimumorder. Advies minimaal ${Number(preview.suggestedEntryMarginUsd ?? preview.minimumEntryMarginUsd ?? 0).toFixed(2)}.</small>}</div>; })}</div>
        <p className="manual-symbol-summary">{v.manualSymbols.length} geselecteerd · {v.manualSymbols.filter((row) => row.side === "LONG").length} LONG · {v.manualSymbols.filter((row) => row.side === "SHORT").length} SHORT</p>
      </div>}
    </div>

    <div className="maker-nav" style={{ marginTop: 16 }}><button disabled={busy || !dirty} onClick={() => action("save")}>Instellingen opslaan</button><button disabled={busy} onClick={() => action("simulate")}>Veilig simuleren</button><button disabled={busy} onClick={checkReadiness}>Readiness controleren</button></div>
    {readiness && <p className="strategy-message">Readiness: {Boolean(readiness.liveReady) ? "LIVE READY" : "nog niet live ready"}</p>}
    {message && <p className="strategy-message">{message}</p>}
  </article>;
}

function Field({ label, value, set, text = false, onBlur, disabled = false }: { label: string; value: string; set: (value: string) => void; text?: boolean; onBlur?: () => void; disabled?: boolean }) {
  return <label>{label}<input disabled={disabled} inputMode={text ? undefined : "decimal"} value={value} onChange={(event) => set(text ? event.target.value : event.target.value.replace(",", "."))} onBlur={onBlur} /></label>;
}
