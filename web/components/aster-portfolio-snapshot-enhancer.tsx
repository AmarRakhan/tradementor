"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";

type Tone = "positive" | "negative" | "neutral";
type ProfitScope = "LONG" | "SHORT" | "ALL";

type SnapshotValues = {
  equity: string;
  available: string;
  activeCapital: string;
  activePositions: string;
  realized: string;
  tradesClosed: string;
  longs: string;
  shorts: string;
  dca: string;
  liquidation: string;
  todayGrowth: string;
  averageDailyGrowth: string;
  realizedTone: Tone;
  todayGrowthTone: Tone;
  averageDailyGrowthTone: Tone;
  riskTone: "safe" | "caution" | "high" | "critical" | "unknown";
  closeDisabled: boolean;
  closeBusy: boolean;
};

type ProfitBucket = {
  eligibleCount: number;
  totalProfitUsd: number;
};

type ProfitPreview = {
  reliable: true;
  minimumProfitUsd: number;
  comparison: "greater_than_or_equal";
  long: ProfitBucket;
  short: ProfitBucket;
  all: ProfitBucket;
};

const EMPTY: SnapshotValues = {
  equity: "—", available: "—", activeCapital: "—", activePositions: "—",
  realized: "—", tradesClosed: "—", longs: "—", shorts: "—", dca: "—",
  liquidation: "—", todayGrowth: "—", averageDailyGrowth: "—",
  realizedTone: "neutral", todayGrowthTone: "neutral", averageDailyGrowthTone: "neutral", riskTone: "unknown",
  closeDisabled: true, closeBusy: false,
};

const REFERENCE = "https://chatgpt.com/s/m_6a9e9a59189881918875e6317fdfc847";

function directText(element: Element | null, selector: string) {
  return element?.querySelector<HTMLElement>(selector)?.textContent?.trim() || "—";
}

function metric(label: string) {
  const rows = Array.from(document.querySelectorAll<HTMLElement>(".metric-strip .metric"));
  const row = rows.find((item) => item.querySelector("span")?.textContent?.trim().toUpperCase() === label);
  return row ? directText(row, "strong") : "—";
}

function percentageTone(value: string): Tone {
  if (value === "—") return "neutral";
  const parsed = Number(value.replace("%", "").replace("+", "").replace(",", ".").trim());
  return Number.isFinite(parsed) && parsed > 0 ? "positive" : Number.isFinite(parsed) && parsed < 0 ? "negative" : "neutral";
}

function readSnapshot(): SnapshotValues {
  const realizedRow = Array.from(document.querySelectorAll<HTMLElement>(".metric-strip .metric")).find((item) =>
    item.querySelector("span")?.textContent?.trim().toUpperCase() === "GESLOTEN RESULTAAT VANDAAG",
  );
  const realized = realizedRow ? directText(realizedRow, "strong") : "—";
  const tradesClosed = directText(document.querySelector(".realized-trades-count"), "strong");
  const indexSummary = document.querySelector<HTMLElement>(".active-trades-index > small")?.textContent || "";
  const counts = indexSummary.match(/(\d+)\s*posities\s*·\s*(\d+)L\s*\/\s*(\d+)S\s*·\s*(\d+)\s*DCA/i);
  const risk = document.querySelector<HTMLElement>(".liquidation-risk");
  const riskClass = risk?.className || "";
  const closeButton = document.querySelector<HTMLButtonElement>(".portfolio-close-all");
  const dailyGrowth = document.querySelector<HTMLElement>(".portfolio-growth-daily");
  const dailyValues = dailyGrowth ? Array.from(dailyGrowth.querySelectorAll<HTMLElement>("strong")) : [];
  const todayGrowth = dailyValues[0]?.textContent?.trim() || "—";
  const averageDailyGrowth = dailyValues[1]?.textContent?.trim() || "—";
  return {
    equity: metric("PORTFOLIOWAARDE"),
    available: metric("AVAILABLE TO TRADE"),
    activeCapital: metric("ACTIVE TRADE CAPITAL"),
    activePositions: metric("ACTIEVE POSITIES"),
    realized,
    tradesClosed,
    longs: counts?.[2] || "—",
    shorts: counts?.[3] || "—",
    dca: counts?.[4] || "—",
    liquidation: directText(risk, ".risk-core strong"),
    todayGrowth,
    averageDailyGrowth,
    realizedTone: realizedRow?.classList.contains("positive") ? "positive" : realizedRow?.classList.contains("negative") ? "negative" : "neutral",
    todayGrowthTone: percentageTone(todayGrowth),
    averageDailyGrowthTone: percentageTone(averageDailyGrowth),
    riskTone: riskClass.includes("risk-safe") ? "safe" : riskClass.includes("risk-caution") ? "caution" : riskClass.includes("risk-high") ? "high" : riskClass.includes("risk-critical") ? "critical" : "unknown",
    closeDisabled: !closeButton || closeButton.disabled,
    closeBusy: Boolean(closeButton && /sluiten…|bezig|wachten/i.test(closeButton.textContent || "")),
  };
}

function valuesEqual(a: SnapshotValues, b: SnapshotValues) {
  return Object.keys(a).every((key) => a[key as keyof SnapshotValues] === b[key as keyof SnapshotValues]);
}

function Icon({ name }: { name: "wallet" | "coins" | "capital" | "positions" | "result" | "trades" | "balance" | "dca" | "shield" | "growth" | "calendar" }) {
  const common = { width: 27, height: 27, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  if (name === "wallet") return <svg {...common}><path d="M4 7.5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2h12"/><path d="M15 12h6v4h-6a2 2 0 0 1 0-4Z"/></svg>;
  if (name === "coins") return <svg {...common}><ellipse cx="9" cy="6" rx="5" ry="2.5"/><path d="M4 6v4c0 1.4 2.2 2.5 5 2.5s5-1.1 5-2.5V6M4 10v4c0 1.4 2.2 2.5 5 2.5 1.2 0 2.3-.2 3.2-.6"/><ellipse cx="16.5" cy="15.5" rx="4.5" ry="2.3"/><path d="M12 15.5v3.2c0 1.3 2 2.3 4.5 2.3s4.5-1 4.5-2.3v-3.2"/></svg>;
  if (name === "capital") return <svg {...common}><circle cx="12" cy="12" r="8"/><path d="m12 12 4-4M12 12l-2 5"/></svg>;
  if (name === "positions") return <svg {...common}><path d="M5 19V13M10 19V8M15 19V11M20 19V4"/></svg>;
  if (name === "result") return <svg {...common}><path d="M3 5v14h18"/><path d="m5 9 4 4 4-6 6 5"/><path d="m16 12 3 .2-.2 3"/></svg>;
  if (name === "trades") return <svg {...common}><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h5"/></svg>;
  if (name === "balance") return <svg {...common}><path d="m3 16 5-5 4 3 7-8"/><path d="M16 6h3v3"/></svg>;
  if (name === "dca") return <svg {...common}><path d="m12 3 7 4-7 4-7-4 7-4Z"/><path d="m5 11 7 4 7-4M5 15l7 4 7-4"/></svg>;
  if (name === "growth") return <svg {...common}><path d="M4 19V12M10 19V8M16 19V4"/><path d="M3 21h18"/></svg>;
  if (name === "calendar") return <svg {...common}><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/></svg>;
  return <svg {...common}><path d="M12 3 5 6v5c0 4.7 2.8 8.2 7 10 4.2-1.8 7-5.3 7-10V6l-7-3Z"/><path d="m9 12 2 2 4-5"/></svg>;
}

function MetricCard({ icon, label, value, tone = "normal" }: { icon: Parameters<typeof Icon>[0]["name"]; label: string; value: string; tone?: "normal" | "positive" | "negative" }) {
  return <article className={`aps-metric aps-${tone}`}><span className="aps-icon"><Icon name={icon} /></span><div><small>{label}</small><strong>{value}</strong></div></article>;
}

function GrowthCard({ icon, label, value, tone }: { icon: "growth" | "calendar"; label: string; value: string; tone: Tone }) {
  return <article className={`aps-growth-card aps-${tone}`}><span className="aps-icon"><Icon name={icon} /></span><div><small>{label}</small><strong>{value}</strong></div></article>;
}

function profitMoney(value: number | undefined) {
  if (value === undefined || !Number.isFinite(value)) return "—";
  return `+US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.max(0, value))}`;
}

function ProfitAction({
  scope,
  label,
  bucket,
  busy,
  onClick,
}: {
  scope: ProfitScope;
  label: string;
  bucket: ProfitBucket | null;
  busy: boolean;
  onClick: (scope: ProfitScope) => void;
}) {
  const count = bucket?.eligibleCount ?? 0;
  const countLabel = bucket ? `${count} ${count === 1 ? "positie" : "posities"}` : "—";
  const icon = scope === "LONG" ? "↗" : scope === "SHORT" ? "↘" : "◎";
  return <button
    type="button"
    className={`aps-profit-action aps-profit-${scope.toLowerCase()}`}
    disabled={!bucket || count === 0 || busy}
    onClick={() => onClick(scope)}
    aria-label={`${label}, ${profitMoney(bucket?.totalProfitUsd)}, ${countLabel}`}
  >
    <span className="aps-profit-icon" aria-hidden="true">{icon}</span>
    <span className="aps-profit-copy">
      <b>{busy ? "Bezig…" : label}</b>
      <strong>{profitMoney(bucket?.totalProfitUsd)}</strong>
      <small>{countLabel}</small>
    </span>
  </button>;
}

function Snapshot({
  values,
  profitPreview,
  profitBusy,
  onCloseAll,
  onCloseProfit,
}: {
  values: SnapshotValues;
  profitPreview: ProfitPreview | null;
  profitBusy: ProfitScope | null;
  onCloseAll: () => void;
  onCloseProfit: (scope: ProfitScope) => void;
}) {
  return <section className="aster-portfolio-snapshot" aria-label="Portfolio Snapshot" data-reference={REFERENCE}>
    <header>
      <div className="aps-title-icon"><Icon name="positions" /></div>
      <h2>PORTFOLIO SNAPSHOT</h2>
      <div className="aps-header-actions">
        <span className="aps-live"><i />Live</span>
        <button type="button" className="aps-close-all" disabled={values.closeDisabled} onClick={onCloseAll}>{values.closeBusy ? "SLUITEN…" : "ALLES SLUITEN"}</button>
      </div>
    </header>
    <div className="aps-grid">
      <MetricCard icon="wallet" label="PORTFOLIOWAARDE" value={values.equity} />
      <MetricCard icon="coins" label="AVAILABLE TO TRADE" value={values.available} />
      <MetricCard icon="capital" label="ACTIEF TRADE CAPITAL" value={values.activeCapital} />
      <MetricCard icon="positions" label="ACTIEVE POSITIES" value={values.activePositions} />
      <MetricCard icon="result" label="GESLOTEN RESULTAAT" value={values.realized} tone={values.realizedTone === "positive" ? "positive" : values.realizedTone === "negative" ? "negative" : "normal"} />
      <MetricCard icon="trades" label="TRADES GESLOTEN" value={values.tradesClosed} />
    </div>
    <div className="aps-status-row">
      <div className="aps-status aps-balance"><Icon name="balance" /><strong><b>{values.longs}L</b><span>/</span><em>{values.shorts}S</em></strong></div>
      <div className="aps-status"><Icon name="dca" /><strong>{values.dca} DCA</strong></div>
      <div className={`aps-status aps-risk aps-risk-${values.riskTone}`}><Icon name="shield" /><span><small>LIQUIDATIERISICO</small><strong>{values.liquidation}</strong></span></div>
    </div>
    <div className="aps-growth-row">
      <GrowthCard icon="growth" label="RENDEMENT VANDAAG" value={values.todayGrowth} tone={values.todayGrowthTone} />
      <GrowthCard icon="calendar" label="GEMIDDELD PER DAG" value={values.averageDailyGrowth} tone={values.averageDailyGrowthTone} />
    </div>
    <div className="aps-profit-row" aria-label="Winstposities sluiten">
      <ProfitAction scope="LONG" label="Close Long" bucket={profitPreview?.long ?? null} busy={profitBusy === "LONG"} onClick={onCloseProfit} />
      <ProfitAction scope="SHORT" label="Close Short" bucket={profitPreview?.short ?? null} busy={profitBusy === "SHORT"} onClick={onCloseProfit} />
      <ProfitAction scope="ALL" label="Close All" bucket={profitPreview?.all ?? null} busy={profitBusy === "ALL"} onClick={onCloseProfit} />
    </div>
  </section>;
}

async function loadProfitPreview(): Promise<ProfitPreview> {
  const payload = await authenticatedRequest("/api/exchanges/aster/positions/profitable-close-preview", { cache: "no-store" }) as ProfitPreview;
  const buckets = [payload?.long, payload?.short, payload?.all];
  const valid = payload?.reliable === true
    && payload?.comparison === "greater_than_or_equal"
    && buckets.every((bucket) => bucket && Number.isInteger(bucket.eligibleCount) && bucket.eligibleCount >= 0 && Number.isFinite(bucket.totalProfitUsd));
  if (!valid) throw new Error("De actuele winstselectie is niet betrouwbaar beschikbaar.");
  return payload;
}

export function AsterPortfolioSnapshotEnhancer() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [values, setValues] = useState<SnapshotValues>(EMPTY);
  const [profitPreview, setProfitPreview] = useState<ProfitPreview | null>(null);
  const [profitBusy, setProfitBusy] = useState<ProfitScope | null>(null);
  const valuesRef = useRef<SnapshotValues>(EMPTY);
  const syncing = useRef(false);

  useEffect(() => {
    let observer: MutationObserver | null = null;
    let frame = 0;
    let alive = true;
    const sync = () => {
      if (!alive || syncing.current) return;
      syncing.current = true;
      frame = window.requestAnimationFrame(() => {
        syncing.current = false;
        const asterHero = document.querySelector(".aster-liquidation-hero");
        const impact = document.querySelector<HTMLElement>('section[aria-label^="Portfolio impact."]');
        const active = Boolean(asterHero && impact);
        if (!active) {
          document.documentElement.removeAttribute("data-aster-compact-snapshot");
          setHost((current) => current === null ? current : null);
          return;
        }
        document.documentElement.setAttribute("data-aster-compact-snapshot", "true");
        let mount = document.getElementById("aster-portfolio-snapshot-host");
        if (!mount) {
          mount = document.createElement("div");
          mount.id = "aster-portfolio-snapshot-host";
        }
        const battleRoot = impact.parentElement;
        if (battleRoot?.parentElement && (mount.parentElement !== battleRoot.parentElement || mount.nextElementSibling !== battleRoot)) battleRoot.parentElement.insertBefore(mount, battleRoot);
        setHost((current) => current === mount ? current : mount);
        const next = readSnapshot();
        if (!valuesEqual(valuesRef.current, next)) {
          valuesRef.current = next;
          setValues(next);
        }
      });
    };
    observer = new MutationObserver(sync);
    observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["class", "disabled"] });
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    sync();
    const timer = window.setInterval(sync, 5000);
    return () => {
      alive = false;
      observer?.disconnect();
      window.clearInterval(timer);
      window.cancelAnimationFrame(frame);
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
      document.documentElement.removeAttribute("data-aster-compact-snapshot");
      document.getElementById("aster-portfolio-snapshot-host")?.remove();
    };
  }, []);

  useEffect(() => {
    if (!host) return;
    let alive = true;
    const refresh = async () => {
      try {
        const preview = await loadProfitPreview();
        if (alive) setProfitPreview(preview);
      } catch {
        if (alive) setProfitPreview(null);
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [host]);

  const closeAll = () => {
    const legacy = document.querySelector<HTMLButtonElement>(".portfolio-close-all");
    if (!legacy || legacy.disabled) return;
    legacy.click();
  };

  const closeProfit = async (scope: ProfitScope) => {
    if (profitBusy) return;
    setProfitBusy(scope);
    try {
      const fresh = await loadProfitPreview();
      setProfitPreview(fresh);
      const bucket = scope === "LONG" ? fresh.long : scope === "SHORT" ? fresh.short : fresh.all;
      if (bucket.eligibleCount < 1) return;
      const label = scope === "LONG" ? "Close Long" : scope === "SHORT" ? "Close Short" : "Close All";
      const positions = `${bucket.eligibleCount} ${bucket.eligibleCount === 1 ? "positie" : "posities"}`;
      const confirmed = window.confirm(`${label}\n\n${profitMoney(bucket.totalProfitUsd)} · ${positions}\n\nAlleen posities die bij de servercontrole nog steeds minimaal US$ 0,50 winst hebben worden gesloten. Doorgaan?`);
      if (!confirmed) return;

      await authenticatedRequest(`/api/exchanges/aster/positions/close-profitable?side=${scope}`, {
        method: "POST",
        body: JSON.stringify({
          confirm: true,
          idempotency_key: `snapshot-profit-${scope.toLowerCase()}-${Date.now()}-${crypto.randomUUID()}`,
        }),
      });

      try {
        setProfitPreview(await loadProfitPreview());
      } catch {
        setProfitPreview(null);
      }
      window.setTimeout(() => window.location.reload(), 250);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "De winstposities konden niet veilig worden gesloten.");
    } finally {
      setProfitBusy(null);
    }
  };

  return host ? createPortal(
    <Snapshot
      values={values}
      profitPreview={profitPreview}
      profitBusy={profitBusy}
      onCloseAll={closeAll}
      onCloseProfit={closeProfit}
    />,
    host,
  ) : null;
}
