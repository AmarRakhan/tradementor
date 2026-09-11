"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";
import {
  AsterProfitLockLadderPanel,
  DEFAULT_PROFIT_LOCK_LEVELS,
  parseProfitLockLevels,
  validateProfitLockLevels,
  type ProfitLockLevelDraft,
} from "./aster-profit-lock-ladder-panel";

type PositionSummary = {
  symbol: string;
  longNotional: number;
  shortNotional: number;
  hedgePercent: number;
  cycleProfit: number;
  highestCycleProfit: number;
  currentLevelIndex: number;
  currentTargetHedgePercent: number;
  nextLevel?: { profitUsd: number; hedgePercent: number } | null;
  dcaCount: number;
  status: string;
};

type ProfitLockSummary = {
  enabled?: boolean;
  status?: string;
  hedgeCoveragePercent?: number;
  longExposureUsd?: number;
  profitLockShortExposureUsd?: number;
  positionCount?: number;
  hedgedPositionCount?: number;
  normalShortConflicts?: string[];
  positions?: PositionSummary[];
};

const REFERENCE = "file_00000000e8dc82108202dd2e1397c131";
const money = (value: unknown) => `US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(Number(value) || 0)}`;
const signedMoney = (value: unknown) => `${Number(value) >= 0 ? "+" : "-"}${money(Math.abs(Number(value) || 0))}`;
const percent = (value: unknown) => `${new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 1 }).format(Number(value) || 0)}%`;

function extract(snapshot: Record<string, unknown>) {
  const strategy2 = snapshot.strategy2 && typeof snapshot.strategy2 === "object" ? snapshot.strategy2 as Record<string, unknown> : {};
  const settings = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Record<string, unknown> : {};
  const report = strategy2.multiBb && typeof strategy2.multiBb === "object"
    ? strategy2.multiBb as Record<string, unknown>
    : strategy2.multiBbReport && typeof strategy2.multiBbReport === "object"
      ? strategy2.multiBbReport as Record<string, unknown>
      : {};
  const summary = report.profitLockLadder && typeof report.profitLockLadder === "object"
    ? report.profitLockLadder as ProfitLockSummary
    : {};
  return { settings, summary };
}

export function AsterProfitLockLadderBridge() {
  const [settingsHost, setSettingsHost] = useState<HTMLElement | null>(null);
  const [snapshotHost, setSnapshotHost] = useState<HTMLElement | null>(null);
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [enabled, setEnabled] = useState(false);
  const [levels, setLevels] = useState<ProfitLockLevelDraft[]>(DEFAULT_PROFIT_LOCK_LEVELS.map((row) => ({ ...row })));
  const [summary, setSummary] = useState<ProfitLockSummary>({});
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [detailOpen, setDetailOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const snapshot = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
      const next = extract(snapshot);
      setSettings(next.settings);
      setSummary(next.summary);
      if (!dirty) {
        setEnabled(next.settings.profitLockLadderEnabled === true);
        setLevels(parseProfitLockLevels(next.settings.profitLockLevels));
      }
    } catch {
      // Existing settings remain authoritative while a refresh is temporarily unavailable.
    }
  }, [dirty]);

  useEffect(() => {
    let frame = 0;
    let alive = true;
    const mount = () => {
      if (!alive) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const settingsGrid = document.querySelector<HTMLElement>("#strategy-2-maker .compact-settings-grid");
        if (settingsGrid) {
          let host = document.getElementById("profit-lock-ladder-settings-host");
          if (!host) { host = document.createElement("div"); host.id = "profit-lock-ladder-settings-host"; }
          const before = settingsGrid.querySelector<HTMLElement>(".side-settings-block");
          if (host.parentElement !== settingsGrid) settingsGrid.insertBefore(host, before || null);
          setSettingsHost(host);
        } else setSettingsHost(null);

        const snapshot = document.querySelector<HTMLElement>(".aster-portfolio-snapshot");
        const hedge = snapshot?.querySelector<HTMLElement>(".aps-hedge-row");
        if (snapshot && hedge) {
          let host = document.getElementById("profit-lock-ladder-snapshot-host");
          if (!host) { host = document.createElement("div"); host.id = "profit-lock-ladder-snapshot-host"; }
          if (host.parentElement !== snapshot || host.previousElementSibling !== hedge) hedge.insertAdjacentElement("afterend", host);
          setSnapshotHost(host);
        } else setSnapshotHost(null);
      });
    };
    const observer = new MutationObserver(mount);
    observer.observe(document.body, { childList: true, subtree: true });
    mount();
    return () => {
      alive = false; observer.disconnect(); cancelAnimationFrame(frame);
      document.getElementById("profit-lock-ladder-settings-host")?.remove();
      document.getElementById("profit-lock-ladder-snapshot-host")?.remove();
    };
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const conflictCount = Array.isArray(summary.normalShortConflicts) ? summary.normalShortConflicts.length : 0;
  const rows = Array.isArray(summary.positions) ? summary.positions : [];
  const coverage = Number(summary.hedgeCoveragePercent || 0);

  const setMode = (next: boolean) => {
    setEnabled(next);
    setDirty(true);
    setMessage(next ? "Profit Lock Ladder geselecteerd. Sla op om LONG-only actief te maken." : "Profit Lock Ladder wordt uitgeschakeld na opslaan.");
  };
  const setLadder = (next: ProfitLockLevelDraft[]) => { setLevels(next); setDirty(true); setMessage(""); };

  async function save() {
    const validation = enabled ? validateProfitLockLevels(levels) : null;
    if (validation) { setMessage(validation); return; }
    setBusy(true); setMessage("");
    try {
      const payloadLevels = levels.map((row) => ({
        profitUsd: Number(String(row.profitUsd).replace(",", ".")),
        hedgePercent: Number(String(row.hedgePercent).replace(",", ".")),
      }));
      // Always merge into exchange-backed server truth at the moment of save.
      // The bridge refreshes periodically, so its local settings snapshot can be
      // older than a Bot Settings save that happened a few seconds earlier.
      const latestSnapshot = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
      const latestSettings = extract(latestSnapshot).settings;
      const nextSettings = { ...latestSettings, profitLockLadderEnabled: enabled, profitLockLevels: payloadLevels };
      const response = await authenticatedRequest("/api/exchanges/aster/strategy2/settings", {
        method: "PUT",
        body: JSON.stringify({ settings: nextSettings }),
      }) as Record<string, unknown>;
      const strategy2 = response.strategy2 && typeof response.strategy2 === "object" ? response.strategy2 as Record<string, unknown> : {};
      const saved = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Record<string, unknown> : nextSettings;
      setSettings(saved);
      setEnabled(saved.profitLockLadderEnabled === true);
      setLevels(parseProfitLockLevels(saved.profitLockLevels));
      setDirty(false);
      setMessage(saved.profitLockLadderEnabled === true
        ? "Profit Lock Ladder opgeslagen · primaire trading is LONG-only; bestaande normale SHORTs worden niet automatisch overgenomen."
        : "Profit Lock Ladder staat uit · bestaande tradinginstellingen blijven van toepassing.");
      window.dispatchEvent(new Event("aster-strategy2-settings-changed"));
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Profit Lock Ladder kon niet worden opgeslagen.");
    } finally { setBusy(false); }
  }

  const settingsUi = settingsHost ? createPortal(<div className="pll-bridge-wrap" data-reference={REFERENCE}>
    <AsterProfitLockLadderPanel enabled={enabled} levels={levels} conflictCount={conflictCount} onEnabledChange={setMode} onLevelsChange={setLadder} />
    <div className="pll-save-row"><span>{message || (dirty ? "Wijzigingen nog niet opgeslagen." : enabled ? "Profit Lock Ladder actief in opgeslagen configuratie." : "Optioneel · huidige trading blijft ongewijzigd zolang dit uit staat.")}</span><button type="button" disabled={busy || !dirty} onClick={save}>{busy ? "Opslaan…" : "Profit Lock opslaan"}</button></div>
    <style>{`.pll-bridge-wrap{display:contents}.pll-save-row{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:-1px;padding:6px 8px;border:1px solid rgba(33,214,154,.16);border-radius:9px;background:rgba(3,17,13,.72)}.pll-save-row span{color:#8fa39a;font-size:8px;line-height:1.3}.pll-save-row button{min-height:30px;padding:0 10px;border:1px solid rgba(33,214,154,.52);border-radius:8px;background:rgba(19,115,78,.25);color:#8ff4c6;font-size:8px;font-weight:900;white-space:nowrap}.pll-save-row button:disabled{opacity:.38}@media(max-width:430px){.pll-save-row{align-items:stretch;flex-direction:column}.pll-save-row button{width:100%}}`}</style>
  </div>, settingsHost) : null;

  const snapshotUi = snapshotHost && enabled ? createPortal(<>
    <button type="button" className="pll-snapshot-status" data-reference={REFERENCE} onClick={() => setDetailOpen(true)}>
      <span className="pll-lock">◆</span><span><small>PROFIT LOCK LADDER · ACTIEF</small><strong>{percent(coverage)} hedge dekking</strong><em>{Number(summary.hedgedPositionCount || 0)} / {Number(summary.positionCount || rows.length)} posities gehedged</em></span><b>›</b>
    </button>
    <style>{`.pll-snapshot-status{width:100%;display:grid;grid-template-columns:30px 1fr auto;align-items:center;gap:8px;margin:7px 0 0;padding:8px 10px;border:1px solid rgba(25,229,151,.38);border-radius:11px;background:linear-gradient(100deg,rgba(5,44,31,.88),rgba(3,20,15,.92));color:#eaf6f0;text-align:left;box-shadow:inset 0 0 18px rgba(25,229,151,.035)}.pll-snapshot-status .pll-lock{display:grid;place-items:center;width:28px;height:28px;border:1px solid rgba(39,235,160,.5);border-radius:50%;color:#34eda7;box-shadow:0 0 12px rgba(39,235,160,.13)}.pll-snapshot-status>span:nth-child(2){display:grid;gap:1px}.pll-snapshot-status small{color:#49eeb0;font-size:7px;letter-spacing:.1em}.pll-snapshot-status strong{font-size:12px}.pll-snapshot-status em{color:#879d92;font-size:7.5px;font-style:normal}.pll-snapshot-status>b{color:#54edb6;font-size:21px}`}</style>
  </>, snapshotHost) : null;

  const detail = detailOpen && enabled ? createPortal(<div className="pll-detail-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setDetailOpen(false); }}>
    <section className="pll-detail" role="dialog" aria-modal="true" aria-label="Profit Lock Ladder detail" data-reference={REFERENCE}>
      <header><div><small>PROFIT LOCK LADDER</small><h3>Hedge dekking</h3><p>Gewogen Profit Lock SHORT tegenover de actuele LONG exposure.</p></div><button type="button" onClick={() => setDetailOpen(false)}>×</button></header>
      <div className="pll-detail-metrics"><article><small>HEDGE DEKKING</small><strong>{percent(coverage)}</strong></article><article><small>LONG EXPOSURE</small><strong>{money(summary.longExposureUsd)}</strong></article><article><small>PROFIT LOCK SHORT</small><strong>{money(summary.profitLockShortExposureUsd)}</strong></article></div>
      {conflictCount ? <div className="pll-detail-warning">⚠ {conflictCount} normale SHORT-{conflictCount === 1 ? "positie blokkeert" : "posities blokkeren"} Profit Lock-uitvoering. Deze worden niet automatisch gesloten.</div> : null}
      <div className="pll-detail-table"><div className="head"><span>Coin</span><span>LONG</span><span>SHORT</span><span>Hedge</span><span>Cycle</span><span>Volgende</span></div>{rows.length ? rows.map((row) => <div className="row" key={row.symbol}><strong>{row.symbol.replace(/USDT$/, "")}</strong><span>{money(row.longNotional)}</span><span>{money(row.shortNotional)}</span><b>{percent(row.hedgePercent)}</b><em className={row.cycleProfit >= 0 ? "positive" : "negative"}>{signedMoney(row.cycleProfit)}</em><span>{row.nextLevel ? `+$${row.nextLevel.profitUsd} → ${row.nextLevel.hedgePercent}%` : "100% / exit"}<small>{row.dcaCount} DCA</small></span></div>) : <p className="empty">Nog geen actieve LONG-cycles in Profit Lock Ladder.</p>}</div>
      <footer><span>SHORT wordt binnen een cycle niet automatisch afgebouwd. 100% hedge sluit die coin-cycle en geeft de LONG-seat vrij voor een nieuwe start.</span><button type="button" onClick={() => setDetailOpen(false)}>Sluiten</button></footer>
    </section>
    <style>{`.pll-detail-backdrop{position:fixed;z-index:99999;inset:0;display:grid;place-items:end center;background:rgba(0,0,0,.68);backdrop-filter:blur(4px)}.pll-detail{width:min(760px,100%);max-height:min(84vh,760px);overflow:auto;padding:15px;border:1px solid rgba(31,231,154,.42);border-radius:18px 18px 0 0;background:linear-gradient(180deg,#07150f,#020706);color:#eaf2ee;box-shadow:0 -20px 70px rgba(0,0,0,.55)}.pll-detail header{display:flex;justify-content:space-between;gap:10px}.pll-detail header small{color:#35eca8;font-size:8px;letter-spacing:.12em}.pll-detail h3{margin:2px 0;font-size:20px}.pll-detail header p{margin:0;color:#83958c;font-size:9px}.pll-detail header>button{width:34px;height:34px;border:1px solid rgba(80,118,100,.4);border-radius:50%;background:#0b1712;color:#c8d5ce;font-size:20px}.pll-detail-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:12px 0}.pll-detail-metrics article{display:grid;gap:3px;padding:9px;border:1px solid rgba(49,105,79,.35);border-radius:10px;background:rgba(12,32,24,.72)}.pll-detail-metrics small{font-size:7px;color:#789087}.pll-detail-metrics strong{font-size:13px}.pll-detail-warning{margin:7px 0;padding:8px;border:1px solid rgba(255,139,92,.48);border-radius:9px;background:rgba(115,48,20,.22);color:#ffc09e;font-size:8px}.pll-detail-table{border:1px solid rgba(48,89,71,.45);border-radius:11px;overflow:auto}.pll-detail-table .head,.pll-detail-table .row{display:grid;grid-template-columns:80px repeat(4,minmax(92px,1fr)) minmax(120px,1.2fr);align-items:center;min-width:650px}.pll-detail-table .head{min-height:29px;background:#08110d;color:#71867c;font-size:7px;text-transform:uppercase}.pll-detail-table .row{min-height:45px;border-top:1px solid rgba(48,89,71,.3);font-size:8px}.pll-detail-table .head>*,.pll-detail-table .row>*{padding:6px 8px}.pll-detail-table .row>strong{color:#e7f0eb}.pll-detail-table .row>b{color:#5ceeb7}.pll-detail-table em{font-style:normal}.pll-detail-table em.positive{color:#44eaaa}.pll-detail-table em.negative{color:#ff8198}.pll-detail-table .row span:last-child{display:grid;gap:1px}.pll-detail-table .row small{color:#64796f;font-size:6.8px}.pll-detail-table .empty{padding:18px;color:#768b81;font-size:9px}.pll-detail footer{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:10px}.pll-detail footer span{max-width:560px;color:#81948a;font-size:8px;line-height:1.4}.pll-detail footer button{min-width:100px;height:34px;border:1px solid rgba(30,224,148,.44);border-radius:9px;background:rgba(18,104,72,.25);color:#82f3c5;font-weight:800}@media(max-width:520px){.pll-detail{padding:11px}.pll-detail-metrics{grid-template-columns:1fr 1fr}.pll-detail-metrics article:first-child{grid-column:1/-1}.pll-detail footer{align-items:stretch;flex-direction:column}.pll-detail footer button{width:100%}}`}</style>
  </div>, document.body) : null;

  return <>{settingsUi}{snapshotUi}{detail}</>;
}
