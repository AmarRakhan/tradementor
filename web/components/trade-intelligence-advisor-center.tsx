"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { useAuthSession } from "@/components/auth-provider";

type Tab = "positions" | "opportunities" | "losers" | "winners";
type AdviceTone = "green" | "gold" | "red" | "muted";

type AdvisorPosition = {
  symbol: string;
  side: "LONG" | "SHORT";
  notionalUsd: number;
  entryPrice: number;
  markPrice: number;
  pnlUsd: number;
  pnlPercent: number;
  dcaEligible: boolean;
  state: string;
};

type AdvisorSnapshot = {
  positions: AdvisorPosition[];
  equity: number | null;
  available: number | null;
  activeCapital: number | null;
  scannerLongCandidates: number;
  scannerShortCandidates: number;
  scannerFresh: boolean;
  live: boolean;
  fetchedAt: number;
};

const EMPTY: AdvisorSnapshot = {
  positions: [],
  equity: null,
  available: null,
  activeCapital: null,
  scannerLongCandidates: 0,
  scannerShortCandidates: 0,
  scannerFresh: false,
  live: false,
  fetchedAt: 0,
};

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? value as Record<string, unknown> : {};

const numberOrNull = (value: unknown): number | null => {
  const valueNumber = Number(value);
  return Number.isFinite(valueNumber) ? valueNumber : null;
};

const firstNumber = (objects: Record<string, unknown>[], keys: string[]) => {
  for (const object of objects) for (const key of keys) {
    const value = numberOrNull(object[key]);
    if (value !== null) return value;
  }
  return null;
};

const formatUsd = (value: number | null) =>
  value === null ? "—" : new Intl.NumberFormat("nl-NL", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);

const formatPercent = (value: number) =>
  `${value > 0 ? "+" : ""}${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value)}%`;

function normalizePosition(raw: unknown): AdvisorPosition | null {
  const row = record(raw);
  const symbol = String(row.symbol ?? "").toUpperCase().trim();
  const side = String(row.side ?? "").toUpperCase() === "SHORT" ? "SHORT" : String(row.side ?? "").toUpperCase() === "LONG" ? "LONG" : null;
  const entryPrice = Number(row.entryPrice);
  const markPrice = Number(row.markPrice);
  const pnlUsd = Number(row.unrealizedPnl ?? 0);
  const notionalUsd = Math.abs(Number(row.notionalUsd ?? 0));
  if (!symbol || !side || !Number.isFinite(entryPrice) || !Number.isFinite(markPrice) || entryPrice <= 0 || markPrice <= 0) return null;
  const rawReturn = side === "SHORT" ? (entryPrice - markPrice) / entryPrice * 100 : (markPrice - entryPrice) / entryPrice * 100;
  const state = String(row.state ?? row.status ?? row.strategyState ?? "").toUpperCase();
  const dcaEligible =
    row.dcaEligible === true ||
    row.dcaReady === true ||
    row.nextDcaEligible === true ||
    String(row.dcaStatus ?? "").toUpperCase() === "READY";
  return { symbol, side, notionalUsd, entryPrice, markPrice, pnlUsd: Number.isFinite(pnlUsd) ? pnlUsd : 0, pnlPercent: rawReturn, dcaEligible, state };
}

function parseSnapshot(payload: unknown): AdvisorSnapshot {
  const root = record(payload);
  const data = Object.keys(record(root.data)).length ? record(root.data) : root;
  const strategy2 = record(data.strategy2);
  const runtimeTruth = record(strategy2.runtimeTruth);
  const multiBb = record(strategy2.multiBb);
  const scanner = Object.keys(record(runtimeTruth.scannerDiagnostics)).length
    ? record(runtimeTruth.scannerDiagnostics)
    : record(multiBb.scannerDiagnostics);
  const longScanner = record(scanner.LONG);
  const shortScanner = record(scanner.SHORT);
  const updatedAtMs = firstNumber([scanner], ["updatedAtMs"]) ?? 0;
  const positions = (Array.isArray(data.positions) ? data.positions : []).map(normalizePosition).filter(Boolean) as AdvisorPosition[];
  const equity = firstNumber([data], ["equity", "walletBalance", "marginBalance"]);
  const available = firstNumber([data], ["availableBalance", "availableToTrade", "available"]);
  const activeCapital = firstNumber([data], ["activeTradeCapital", "totalMarginUsed"]);
  return {
    positions,
    equity,
    available,
    activeCapital,
    scannerLongCandidates: Math.max(0, Math.round(firstNumber([longScanner], ["zoneAllowed", "bbCandidates"]) ?? 0)),
    scannerShortCandidates: Math.max(0, Math.round(firstNumber([shortScanner], ["zoneAllowed", "bbCandidates"]) ?? 0)),
    scannerFresh: updatedAtMs > 0 && Date.now() - updatedAtMs < 120_000,
    live: data.configured === true || data.walletRecognized === true,
    fetchedAt: Date.now(),
  };
}

function recommendation(position: AdvisorPosition, available: number | null) {
  const protectedState = /HEDGED|RECOVERY|LOCK/.test(position.state);
  if (protectedState) return { label: "Geen actie", tone: "muted" as AdviceTone, reason: "Beschermde positie · hedge/recovery actief", action: "Bekijk" };
  if (position.pnlPercent >= 8) return { label: "Neem winst", tone: "green" as AdviceTone, reason: "Sterke winst · resultaat beschermen", action: "Neem winst" };
  if (position.pnlPercent <= -8 && position.dcaEligible && (available ?? 0) > 0) return { label: "Koop bij", tone: "green" as AdviceTone, reason: "DCA door runtime bevestigd · gemiddelde entry verbeteren", action: "Koop bij" };
  if (position.pnlPercent <= -8) return { label: "Volgen", tone: "gold" as AdviceTone, reason: "Zwaar verlies · wacht op bevestigde DCA/setup", action: "Bekijk" };
  if (position.pnlPercent > 0) return { label: "Vast houden", tone: "gold" as AdviceTone, reason: "Positie in winst · geen geforceerde actie", action: "Vast houden" };
  return { label: "Geen actie", tone: "muted" as AdviceTone, reason: "Geen bevestigde setup voor extra kapitaal", action: "Bekijk" };
}

function symbolName(symbol: string) {
  return symbol.replace(/USDT$|USDC$|BUSD$|USD$/i, "") || symbol;
}

export function TradeIntelligenceAdvisorCenter({
  dayRangePosition,
}: {
  dayRangePosition?: "low" | "middle" | "high" | null;
}) {
  const { user } = useAuthSession();
  const [snapshot, setSnapshot] = useState<AdvisorSnapshot>(EMPTY);
  const [tab, setTab] = useState<Tab>("positions");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user?.uid) return;
    let alive = true;
    const refresh = async () => {
      try {
        const payload = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" });
        if (!alive) return;
        setSnapshot(parseSnapshot(payload));
        setError("");
      } catch {
        if (!alive) return;
        setError("Live adviesdata tijdelijk niet beschikbaar");
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 15_000);
    const visible = () => { if (document.visibilityState === "visible") void refresh(); };
    document.addEventListener("visibilitychange", visible);
    return () => { alive = false; window.clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, [user?.uid]);

  const losers = useMemo(() => snapshot.positions.filter((position) => position.pnlPercent < 0).sort((a, b) => a.pnlPercent - b.pnlPercent), [snapshot.positions]);
  const winners = useMemo(() => snapshot.positions.filter((position) => position.pnlPercent > 0).sort((a, b) => b.pnlPercent - a.pnlPercent), [snapshot.positions]);
  const opportunities = snapshot.scannerLongCandidates + snapshot.scannerShortCandidates;

  const rows = useMemo(() => {
    const source = tab === "losers" ? losers : tab === "winners" ? winners : snapshot.positions;
    return [...source].sort((a, b) => Math.abs(b.pnlPercent) - Math.abs(a.pnlPercent)).slice(0, 6);
  }, [losers, snapshot.positions, tab, winners]);

  const equity = snapshot.equity ?? 0;
  const activeCapital = snapshot.activeCapital ?? Math.max(0, equity - (snapshot.available ?? 0));
  const deployedPercent = equity > 0 ? Math.max(0, Math.min(100, activeCapital / equity * 100)) : null;
  const availablePercent = equity > 0 && snapshot.available !== null ? Math.max(0, Math.min(100, snapshot.available / equity * 100)) : null;
  const riskLabel = deployedPercent === null ? "—" : deployedPercent < 55 ? "LAAG" : deployedPercent < 80 ? "NORMAAL" : "HOOG";
  const rangeCopy = dayRangePosition === "low"
    ? "Portfolio dicht bij de Low van vandaag"
    : dayRangePosition === "high"
      ? "Portfolio dicht bij de High van vandaag"
      : "Portfolio rond het midden van de dagrange";

  const navigateTo = (label: string) => {
    const candidates = Array.from(document.querySelectorAll<HTMLElement>("button,a,[role=button]"));
    const target = candidates.find((element) => (element.textContent || "").toUpperCase().includes(label.toUpperCase()));
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
    target?.focus?.();
  };

  return <section className="tia-center" data-reference="file_000000000cd88210a1cb98214824c4cc" aria-label="Trade Intelligence Advisor Center">
    <header className="tia-head">
      <div className="tia-mascot" aria-hidden="true"><img src="/trade-intelligence-mascot.svg" alt="" /></div>
      <div className="tia-heading">
        <div className="tia-title-row"><h2>Trade Intelligence Advisor Center</h2><span className={snapshot.live ? "tia-live live" : "tia-live"}><i />{snapshot.live ? "Live" : "Sync"}</span></div>
        <strong>Slimmere trades. Sterker portfolio.</strong>
        <p>AI-gedreven analyse op basis van jouw posities, marktsignalen en kapitaalbeheer.</p>
      </div>
      <button type="button" className="tia-settings" onClick={() => navigateTo("BOTINSTELLINGEN")}><span>⚙</span>Instellingen</button>
    </header>

    <div className="tia-context">
      <span className="tia-context-icon">◎</span>
      <div><strong>{rangeCopy}</strong><p>De dagrange is alleen portfolio-context. LONG/SHORT-advies wordt nooit uitsluitend uit deze grafiek afgeleid; positie- en scannersignalen blijven leidend.</p></div>
    </div>

    <nav className="tia-tabs" aria-label="Trade Intelligence filters">
      <button type="button" className={tab === "positions" ? "active" : ""} onClick={() => setTab("positions")}>▣ Mijn posities <b>({snapshot.positions.length})</b></button>
      <button type="button" className={tab === "opportunities" ? "active" : ""} onClick={() => setTab("opportunities")}>☆ Nieuwe kansen <b>({opportunities})</b></button>
      <button type="button" className={tab === "losers" ? "active" : ""} onClick={() => setTab("losers")}>↓ Verliezers <b>({losers.length})</b></button>
      <button type="button" className={tab === "winners" ? "active" : ""} onClick={() => setTab("winners")}>↑ Winnaars <b>({winners.length})</b></button>
    </nav>

    {tab === "opportunities" ? <div className="tia-opportunity-panel">
      <span>✦</span><div><strong>{snapshot.scannerFresh ? `${opportunities} bevestigde scannerkansen` : "Scannerkansen worden gecontroleerd"}</strong><p>{snapshot.scannerFresh ? `${snapshot.scannerLongCandidates} LONG · ${snapshot.scannerShortCandidates} SHORT. Open de scanner voor symboolniveau en bevestiging vóór een order.` : "Geen munt of richting wordt verzonnen wanneer de scannerdata niet vers genoeg is."}</p></div>
      <button type="button" onClick={() => navigateTo("SCANNER STATUS")}>Open scanner</button>
    </div> : <div className="tia-table" role="table" aria-label="Trade Intelligence aanbevelingen">
      <div className="tia-table-head" role="row">
        <span>Munt</span><span>Richting</span><span>Huidige positie</span><span>P&amp;L</span><span>Advies</span><span>Reden</span><span>Actie</span>
      </div>
      <div className="tia-table-body">
        {rows.map((position) => {
          const advice = recommendation(position, snapshot.available);
          return <div className="tia-row" role="row" key={`${position.symbol}-${position.side}`}>
            <div className="tia-symbol"><span>{symbolName(position.symbol).slice(0, 1)}</span><strong>{symbolName(position.symbol)}</strong><small>{position.symbol}</small></div>
            <div className={`tia-side ${position.side.toLowerCase()}`}><b>{position.side === "LONG" ? "↗" : "↘"}</b>{position.side}</div>
            <div className="tia-position"><strong>{formatUsd(position.notionalUsd)}</strong><small>entry {position.entryPrice.toLocaleString("nl-NL", { maximumFractionDigits: 6 })}</small></div>
            <div className={position.pnlPercent >= 0 ? "tia-pnl positive" : "tia-pnl negative"}><strong>{formatPercent(position.pnlPercent)}</strong><small>{formatUsd(position.pnlUsd)}</small></div>
            <div><span className={`tia-advice ${advice.tone}`}>{advice.label}</span></div>
            <div className="tia-reason">{advice.reason}</div>
            <div><button type="button" className={`tia-action ${advice.tone}`} onClick={() => navigateTo(advice.action === "Neem winst" ? "TRADECENTRUM" : "ACTIEVE POSITIES")}>{advice.action}</button></div>
          </div>;
        })}
        {!rows.length ? <div className="tia-empty">{error || "Geen posities in deze selectie."}</div> : null}
      </div>
    </div>}

    <footer className="tia-summary">
      <article><span className="pie">◕</span><div><small>Portfoliorisico</small><strong className={riskLabel === "HOOG" ? "warning" : ""}>{riskLabel}</strong></div></article>
      <article><span>◉</span><div><small>Beschikbaar kapitaal</small><strong>{formatUsd(snapshot.available)}</strong></div></article>
      <article><span>◔</span><div><small>Inzet in posities</small><strong>{deployedPercent === null ? "—" : `${deployedPercent.toFixed(1).replace(".", ",")}%`}</strong></div></article>
      <article><span>⬡</span><div><small>Advies focus</small><strong>{availablePercent !== null && availablePercent < 20 ? "Kapitaal beschermen" : "Selectief handelen"}</strong><em>Kwaliteit boven kwantiteit.</em></div></article>
    </footer>
  </section>;
}
