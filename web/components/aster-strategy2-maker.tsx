"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { strategy2ServerStatus } from "@/lib/aster-strategy2-server-status.mjs";

type Side = "LONG" | "SHORT";
type Profile = {
  entryMarginUsd: number;
  minimumLeverage: number;
  dcaDistance: number;
  dcaMarginUsd: number;
  maxDca: number;
  unlimitedDca: boolean;
  takeProfit: number;
  autoRestart: boolean;
};
type ManualSymbol = { symbol: string; side: Side };
type Draft = {
  name: string;
  mode: "paper" | "live";
  universeTopN: number;
  maximumPositions: number;
  longSlots: number;
  shortSlots: number;
  manualSymbolSelectionEnabled: boolean;
  manualSymbols: ManualSymbol[];
  standardLong: Profile;
  standardShort: Profile;
  pairOverrides: Record<string, Partial<Profile>>;
};

const DEFAULT_PROFILE: Profile = {
  entryMarginUsd: 5,
  minimumLeverage: 50,
  dcaDistance: 0.003,
  dcaMarginUsd: 2,
  maxDca: 3,
  unlimitedDca: false,
  takeProfit: 0.015,
  autoRestart: true,
};
const DEFAULT_DRAFT: Draft = {
  name: "Aster Multi DCA",
  mode: "live",
  universeTopN: 30,
  maximumPositions: 30,
  longSlots: 20,
  shortSlots: 10,
  manualSymbolSelectionEnabled: false,
  manualSymbols: [],
  standardLong: { ...DEFAULT_PROFILE },
  standardShort: { ...DEFAULT_PROFILE },
  pairOverrides: {},
};

const record = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const num = (value: unknown, fallback: number) => { const n = Number(value); return Number.isFinite(n) ? n : fallback; };
const bool = (value: unknown, fallback: boolean) => typeof value === "boolean" ? value : fallback;
const percent = (value: number) => Number((value * 100).toFixed(4));
const fromPercent = (value: string, fallback: number) => { const n = Number(value.replace(",", ".")); return Number.isFinite(n) ? n / 100 : fallback; };

function parseProfile(value: unknown, fallback: Profile): Profile {
  const row = record(value);
  return {
    entryMarginUsd: num(row.entryMarginUsd, fallback.entryMarginUsd),
    minimumLeverage: num(row.minimumLeverage, fallback.minimumLeverage),
    dcaDistance: num(row.dcaDistance, fallback.dcaDistance),
    dcaMarginUsd: num(row.dcaMarginUsd, fallback.dcaMarginUsd),
    maxDca: Math.max(0, Math.round(num(row.maxDca, fallback.maxDca))),
    unlimitedDca: bool(row.unlimitedDca, fallback.unlimitedDca),
    takeProfit: num(row.takeProfit, fallback.takeProfit),
    autoRestart: bool(row.autoRestart, fallback.autoRestart),
  };
}

function parseManualSymbols(value: unknown): ManualSymbol[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const row = record(item); const symbol = String(row.symbol || "").toUpperCase().trim(); const side = String(row.side || "").toUpperCase();
    return symbol.endsWith("USDT") && (side === "LONG" || side === "SHORT") ? [{ symbol, side: side as Side }] : [];
  });
}

function draftFromSettings(value: unknown): Draft {
  const x = record(value);
  const base: Profile = {
    entryMarginUsd: num(x.entryMarginUsd, DEFAULT_PROFILE.entryMarginUsd),
    minimumLeverage: num(x.minimumLeverage, DEFAULT_PROFILE.minimumLeverage),
    dcaDistance: num(x.dcaDistance, DEFAULT_PROFILE.dcaDistance),
    dcaMarginUsd: num(x.dcaMarginUsd, DEFAULT_PROFILE.dcaMarginUsd),
    maxDca: Math.max(0, Math.round(num(x.maxDca, DEFAULT_PROFILE.maxDca))),
    unlimitedDca: bool(x.unlimitedDca, DEFAULT_PROFILE.unlimitedDca),
    takeProfit: num(x.takeProfit, DEFAULT_PROFILE.takeProfit),
    autoRestart: bool(x.autoRestart, true),
  };
  const overrides = record(x.pairOverrides);
  const normalizedOverrides: Record<string, Partial<Profile>> = {};
  for (const [symbol, raw] of Object.entries(overrides)) {
    const row = record(raw); const key = symbol.toUpperCase().trim();
    if (!key.endsWith("USDT")) continue;
    const out: Partial<Profile> = {};
    if (row.entryMarginUsd !== undefined) out.entryMarginUsd = num(row.entryMarginUsd, base.entryMarginUsd);
    if (row.minimumLeverage !== undefined) out.minimumLeverage = num(row.minimumLeverage, base.minimumLeverage);
    if (row.dcaDistance !== undefined) out.dcaDistance = num(row.dcaDistance, base.dcaDistance);
    if (row.dcaMarginUsd !== undefined) out.dcaMarginUsd = num(row.dcaMarginUsd, base.dcaMarginUsd);
    if (row.maxDca !== undefined) out.maxDca = Math.max(0, Math.round(num(row.maxDca, base.maxDca)));
    if (row.unlimitedDca !== undefined) out.unlimitedDca = bool(row.unlimitedDca, base.unlimitedDca);
    if (row.takeProfit !== undefined) out.takeProfit = num(row.takeProfit, base.takeProfit);
    if (row.autoRestart !== undefined) out.autoRestart = bool(row.autoRestart, base.autoRestart);
    if (Object.keys(out).length) normalizedOverrides[key] = out;
  }
  const total = Math.max(1, Math.round(num(x.maximumPositions, DEFAULT_DRAFT.maximumPositions)));
  const longSlots = Math.max(0, Math.min(total, Math.round(num(x.longSlots, DEFAULT_DRAFT.longSlots))));
  return {
    name: String(x.name || DEFAULT_DRAFT.name),
    mode: x.mode === "paper" ? "paper" : "live",
    universeTopN: Math.max(1, Math.round(num(x.universeTopN, DEFAULT_DRAFT.universeTopN))),
    maximumPositions: total,
    longSlots,
    shortSlots: Math.max(0, Math.min(total, Math.round(num(x.shortSlots, total - longSlots)))),
    manualSymbolSelectionEnabled: x.manualSymbolSelectionEnabled === true,
    manualSymbols: parseManualSymbols(x.manualSymbols),
    standardLong: parseProfile(x.standardLong, base),
    standardShort: parseProfile(x.standardShort, base),
    pairOverrides: normalizedOverrides,
  };
}

function serializeDraft(draft: Draft, previous: Record<string, unknown>) {
  const total = Math.max(1, Math.round(draft.maximumPositions));
  const longSlots = Math.max(0, Math.min(total, Math.round(draft.longSlots)));
  const shortSlots = Math.max(0, total - longSlots);
  return {
    ...previous,
    engine: "multi_bb_v1",
    strategyKind: "multi_bb_v1",
    name: draft.name,
    mode: draft.mode,
    universeTopN: Math.max(1, Math.round(draft.universeTopN)),
    maximumPositions: total,
    longSlots,
    shortSlots,
    marginMode: "cross",
    entryMode: "immediate_fill",
    autoRestart: true,
    manualSymbolSelectionEnabled: draft.manualSymbolSelectionEnabled,
    manualSymbols: draft.manualSymbols,
    standardLong: draft.standardLong,
    standardShort: draft.standardShort,
    pairOverrides: draft.pairOverrides,
    // Legacy top-level values stay valid for older runtime readers; STANDARD LONG is the safe fallback.
    entryMarginUsd: draft.standardLong.entryMarginUsd,
    entrySizingMode: "margin",
    minimumLeverage: draft.standardLong.minimumLeverage,
    dcaDistance: draft.standardLong.dcaDistance,
    dcaMarginUsd: draft.standardLong.dcaMarginUsd,
    maxDca: draft.standardLong.maxDca,
    unlimitedDca: draft.standardLong.unlimitedDca,
    takeProfit: draft.standardLong.takeProfit,
  };
}

export function AsterStrategy2Maker({ snapshot, serverConfirmed, onConfirmed, onChanged }: { snapshot: Record<string, unknown> | null; serverConfirmed: boolean; onConfirmed: (strategy2: Record<string, unknown>) => void; onChanged: () => void }) {
  const [draft, setDraft] = useState<Draft>(DEFAULT_DRAFT);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [readiness, setReadiness] = useState<Record<string, unknown> | null>(null);
  const [confirmedState, setConfirmedState] = useState<Record<string, unknown> | null>(null);
  const [pairSymbol, setPairSymbol] = useState("BTCUSDT");
  const snapshotState = record(snapshot?.strategy2);
  const status = strategy2ServerStatus(snapshotState, confirmedState, serverConfirmed);
  const state = status.state as Record<string, unknown>;
  const serverSettings = record(state.settings);

  useEffect(() => {
    if (dirty || !Object.keys(serverSettings).length) return;
    setDraft(draftFromSettings(serverSettings));
  }, [serverSettings, dirty]);

  const settings = useMemo(() => serializeDraft(draft, serverSettings), [draft, serverSettings]);
  const enabled = status.enabled === true;
  const liveReady = status.liveReady === true || (!status.pending && readiness?.liveReady === true);
  const report = record(state.multiBb);
  const normalizedPair = pairSymbol.toUpperCase().replace(/[^A-Z0-9]/g, "");
  const pairOverride = draft.pairOverrides[normalizedPair] || {};
  const pairStandard = draft.standardLong;
  const pairEffective = { ...pairStandard, ...pairOverride };

  const change = (next: Draft) => { setDraft(next); setDirty(true); setMessage(""); };
  const setTotal = (value: number) => {
    const total = Math.max(1, Math.round(value || 1)); const longSlots = Math.min(total, draft.longSlots);
    change({ ...draft, maximumPositions: total, longSlots, shortSlots: total - longSlots });
  };
  const setLongSlots = (value: number) => {
    const longSlots = Math.max(0, Math.min(draft.maximumPositions, Math.round(value || 0)));
    change({ ...draft, longSlots, shortSlots: draft.maximumPositions - longSlots });
  };

  async function action(kind: "save" | "simulate" | "start" | "stop") {
    if (busy) return;
    setBusy(true); setMessage("");
    try {
      const route = kind === "save" ? "settings" : kind;
      const method = kind === "save" ? "PUT" : "POST";
      const body = kind === "start" ? { confirm: true, settings } : kind === "stop" ? { confirm: true } : { settings };
      const result = await authenticatedRequest(`/api/exchanges/aster/strategy2/${route}`, { method, body: JSON.stringify(body) }) as Record<string, unknown>;
      const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null;
      if (confirmed) { setConfirmedState(confirmed); onConfirmed(confirmed); }
      if (kind === "save") { setDirty(false); setMessage("Aster Bot-instellingen server-side opgeslagen. Actieve posities zijn niet gereset of gesloten."); }
      else if (kind === "simulate") setMessage("Configuratie gevalideerd; 0 orders verzonden.");
      else if (kind === "stop") setMessage("Aster Bot gestopt; bestaande posities zijn niet automatisch gesloten.");
      else setMessage(result.started === true ? "Aster Bot is server-side ingeschakeld." : `Start niet bevestigd${result.reason ? `: ${String(result.reason)}` : "."}`);
      await Promise.resolve(onChanged());
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Actie mislukt");
    } finally { setBusy(false); }
  }

  async function checkReadiness() {
    if (busy) return;
    setBusy(true); setMessage("");
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/readiness") as Record<string, unknown>;
      setReadiness(result);
      setMessage(result.liveReady === true ? "LIVE READY bevestigd." : "Readiness gecontroleerd; live-uitvoering is nog niet volledig vrijgegeven.");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Readiness mislukt"); }
    finally { setBusy(false); }
  }

  async function toggleLive() {
    if (status.pending || busy) return;
    if (enabled) return action("stop");
    if (liveReady) return action("start");
    return checkReadiness();
  }

  function setPairOverride(next: Partial<Profile>) {
    if (!normalizedPair.endsWith("USDT")) return;
    change({ ...draft, pairOverrides: { ...draft.pairOverrides, [normalizedPair]: { ...pairOverride, ...next } } });
  }
  function resetPairOverride() {
    const next = { ...draft.pairOverrides }; delete next[normalizedPair];
    change({ ...draft, pairOverrides: next });
  }

  return <article id="strategy-2-maker" className="strategy-card strategy-two-card aster-bot-direct-settings">
    <div className="strategy-title-row"><div><span className="kicker">ASTER BOT</span><h2>Instellingen</h2></div><span className={`strategy-state ${enabled ? "on" : ""}`}>{enabled ? "AAN" : "UIT"}</span></div>
    <p>Één direct instellingenpaneel. Hiërarchie: globale defaults → STANDARD LONG/SHORT → pair override. Er is geen wizard en opslaan start geen trade.</p>
    <div className="strategy-facts"><span>Top {draft.universeTopN}</span><span>{draft.longSlots} LONG · {draft.shortSlots} SHORT</span><span>STANDARD LONG {draft.standardLong.minimumLeverage}×</span><span>STANDARD SHORT {draft.standardShort.minimumLeverage}×</span><span>{Object.keys(draft.pairOverrides).length} CUSTOM</span><span>CROSS</span></div>
    <div className="strategy-message"><b>Actieve trades beschermd:</b> instellingen worden opgeslagen zonder cycle reset, zonder fillverlies en zonder automatische close. Pair maxDca kan bijvoorbeeld van 3 naar 5 worden verhoogd terwijl dcaCount 3 behouden blijft.<br/><b>Laatste scan:</b> {String(report.activeLong ?? state.longLegs ?? 0)} LONG · {String(report.activeShort ?? state.shortLegs ?? 0)} SHORT.</div>

    <div className={`strategy-power-control ${enabled ? "enabled" : "ready"}`}><span><b>Aster Bot live</b><small>{enabled ? "server-side actief" : "uit · handmatig inschakelen"}</small></span><button type="button" role="switch" aria-checked={enabled} disabled={busy || status.pending} onClick={() => void toggleLive()}><i />{enabled ? "Uitschakelen" : "Inschakelen"}</button></div>

    <details className="strategy-settings-group" open><summary>Globale defaults & capaciteit</summary><div className="maker-input direct-settings-grid">
      <Field label="Naam" value={draft.name} onChange={(value) => change({ ...draft, name: value })}/>
      <NumberField label="Top-N volume" value={draft.universeTopN} min={1} max={200} onChange={(value) => change({ ...draft, universeTopN: Math.round(value) })}/>
      <NumberField label="Totaal posities" value={draft.maximumPositions} min={1} max={200} onChange={setTotal}/>
      <NumberField label="LONG slots" value={draft.longSlots} min={0} max={draft.maximumPositions} onChange={setLongSlots}/>
      <label>SHORT slots<input value={draft.shortSlots} readOnly aria-readonly="true"/></label>
      <label>Modus<select value={draft.mode} onChange={(event) => change({ ...draft, mode: event.target.value === "paper" ? "paper" : "live" })}><option value="live">Live</option><option value="paper">Paper</option></select></label>
      <label className="manual-symbol-toggle"><span><b>Zelf munten kiezen</b><small>UIT = automatische Top-N scanner. AAN = alleen onderstaande pairs.</small></span><input type="checkbox" checked={draft.manualSymbolSelectionEnabled} onChange={(event) => change({ ...draft, manualSymbolSelectionEnabled: event.target.checked })}/></label>
      {draft.manualSymbolSelectionEnabled && <Field label="Handmatige pairs" value={draft.manualSymbols.map((item) => `${item.symbol}:${item.side}`).join(", ")} onChange={(value) => change({ ...draft, manualSymbols: value.split(",").flatMap((part) => { const [rawSymbol, rawSide] = part.trim().toUpperCase().split(":"); const side = rawSide === "SHORT" ? "SHORT" : "LONG"; const symbol = rawSymbol?.trim(); return symbol?.endsWith("USDT") ? [{ symbol, side } as ManualSymbol] : []; }) })}/>}
    </div></details>

    <div className="direct-profile-grid">
      <ProfilePanel side="LONG" profile={draft.standardLong} onChange={(profile) => change({ ...draft, standardLong: profile })}/>
      <ProfilePanel side="SHORT" profile={draft.standardShort} onChange={(profile) => change({ ...draft, standardShort: profile })}/>
    </div>

    <details className="strategy-settings-group" open><summary>Pair override <span className="interface-safe-badge">CUSTOM</span></summary><div className="maker-input direct-settings-grid">
      <Field label="Pair" value={pairSymbol} onChange={setPairSymbol}/>
      <div className="maker-summary"><b>{normalizedPair || "Pair"} {draft.pairOverrides[normalizedPair] ? "· CUSTOM" : "· STANDARD"}</b><span>Niet ingevulde velden erven van STANDARD LONG/SHORT. Deze override blijft server-side bestaan tot Reset naar standaard.</span></div>
      <NumberField label="Max DCA" value={Number(pairEffective.maxDca)} min={0} max={999} onChange={(value) => setPairOverride({ maxDca: Math.round(value), unlimitedDca: false })}/>
      <NumberField label="DCA bedrag (USDT margin)" value={Number(pairEffective.dcaMarginUsd)} min={0.01} step={0.01} onChange={(value) => setPairOverride({ dcaMarginUsd: value })}/>
      <NumberField label="DCA afstand (%)" value={percent(Number(pairEffective.dcaDistance))} min={0.01} step={0.01} onChange={(value) => setPairOverride({ dcaDistance: value / 100 })}/>
      <NumberField label="Take Profit (%)" value={percent(Number(pairEffective.takeProfit))} min={0.1} step={0.1} onChange={(value) => setPairOverride({ takeProfit: value / 100 })}/>
      <button type="button" className="expand-settings" onClick={resetPairOverride} disabled={!draft.pairOverrides[normalizedPair]}>Reset naar standaard</button>
    </div></details>

    <div className="maker-nav direct-save-bar"><button type="button" disabled={!dirty || busy} onClick={() => void action("save")}>{busy ? "Bezig…" : dirty ? "Wijzigingen opslaan" : "Opgeslagen"}</button><button type="button" disabled={busy} onClick={() => void action("simulate")}>Test configuratie</button><button type="button" disabled={busy} onClick={() => void checkReadiness()}>Controleer live-gereedheid</button></div>
    {dirty && <p className="strategy-message">Niet-opgeslagen wijzigingen. Quick trades blijven de laatst server-side opgeslagen profielen gebruiken tot je Opslaan kiest.</p>}
    {readiness && <p className="strategy-message">Readiness: {readiness.liveReady === true ? "LIVE READY" : "nog niet volledig live ready"}</p>}
    {message && <p className="strategy-message">{message}</p>}
  </article>;
}

function ProfilePanel({ side, profile, onChange }: { side: Side; profile: Profile; onChange: (profile: Profile) => void }) {
  return <details className={`strategy-settings-group profile-${side.toLowerCase()}`} open><summary>STANDARD {side}</summary><div className="maker-input direct-settings-grid">
    <NumberField label="Start margin (USDT)" value={profile.entryMarginUsd} min={0.01} step={0.01} onChange={(value) => onChange({ ...profile, entryMarginUsd: value })}/>
    <NumberField label="Minimum leverage (×)" value={profile.minimumLeverage} min={1} max={300} onChange={(value) => onChange({ ...profile, minimumLeverage: Math.round(value) })}/>
    <NumberField label="DCA afstand (%)" value={percent(profile.dcaDistance)} min={0.01} step={0.01} onChange={(value) => onChange({ ...profile, dcaDistance: value / 100 })}/>
    <NumberField label="DCA margin (USDT)" value={profile.dcaMarginUsd} min={0.01} step={0.01} onChange={(value) => onChange({ ...profile, dcaMarginUsd: value })}/>
    {!profile.unlimitedDca && <NumberField label="Max DCA" value={profile.maxDca} min={0} max={999} onChange={(value) => onChange({ ...profile, maxDca: Math.round(value) })}/>} 
    <label className="manual-symbol-toggle"><span><b>Onbeperkt DCA</b><small>Exchange-, leverage-, margin- en duplicatechecks blijven verplicht.</small></span><input type="checkbox" checked={profile.unlimitedDca} onChange={(event) => onChange({ ...profile, unlimitedDca: event.target.checked })}/></label>
    <NumberField label="Take Profit (%)" value={percent(profile.takeProfit)} min={0.1} max={20} step={0.1} onChange={(value) => onChange({ ...profile, takeProfit: value / 100 })}/>
    <label className="manual-symbol-toggle"><span><b>Auto-herstart na TP</b><small>Nieuwe cycle gebruikt dan de op dat moment geldende opgeslagen defaults.</small></span><input type="checkbox" checked={profile.autoRestart} onChange={(event) => onChange({ ...profile, autoRestart: event.target.checked })}/></label>
  </div></details>;
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label>{label}<input value={value} onChange={(event) => onChange(event.target.value)}/></label>; }
function NumberField({ label, value, onChange, min, max, step = 1 }: { label: string; value: number; onChange: (value: number) => void; min?: number; max?: number; step?: number }) {
  return <label>{label}<input type="number" value={Number.isFinite(value) ? value : 0} min={min} max={max} step={step} onChange={(event) => { const n = Number(event.target.value); if (Number.isFinite(n)) onChange(n); }}/></label>;
}
