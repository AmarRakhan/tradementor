"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

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
  realizedTone: "positive" | "negative" | "neutral";
  riskTone: "safe" | "caution" | "high" | "critical" | "unknown";
  closeDisabled: boolean;
  closeBusy: boolean;
};

const EMPTY: SnapshotValues = {
  equity: "—", available: "—", activeCapital: "—", activePositions: "—",
  realized: "—", tradesClosed: "—", longs: "—", shorts: "—", dca: "—",
  liquidation: "—", realizedTone: "neutral", riskTone: "unknown",
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
    realizedTone: realizedRow?.classList.contains("positive") ? "positive" : realizedRow?.classList.contains("negative") ? "negative" : "neutral",
    riskTone: riskClass.includes("risk-safe") ? "safe" : riskClass.includes("risk-caution") ? "caution" : riskClass.includes("risk-high") ? "high" : riskClass.includes("risk-critical") ? "critical" : "unknown",
    closeDisabled: !closeButton || closeButton.disabled,
    closeBusy: Boolean(closeButton && /sluiten…|bezig|wachten/i.test(closeButton.textContent || "")),
  };
}

function Icon({ name }: { name: "wallet" | "coins" | "capital" | "positions" | "result" | "trades" | "balance" | "dca" | "shield" }) {
  const common = { width: 27, height: 27, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  if (name === "wallet") return <svg {...common}><path d="M4 7.5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2h12"/><path d="M15 12h6v4h-6a2 2 0 0 1 0-4Z"/></svg>;
  if (name === "coins") return <svg {...common}><ellipse cx="9" cy="6" rx="5" ry="2.5"/><path d="M4 6v4c0 1.4 2.2 2.5 5 2.5s5-1.1 5-2.5V6M4 10v4c0 1.4 2.2 2.5 5 2.5 1.2 0 2.3-.2 3.2-.6"/><ellipse cx="16.5" cy="15.5" rx="4.5" ry="2.3"/><path d="M12 15.5v3.2c0 1.3 2 2.3 4.5 2.3s4.5-1 4.5-2.3v-3.2"/></svg>;
  if (name === "capital") return <svg {...common}><circle cx="12" cy="12" r="8"/><path d="m12 12 4-4M12 12l-2 5"/></svg>;
  if (name === "positions") return <svg {...common}><path d="M5 19V13M10 19V8M15 19V11M20 19V4"/></svg>;
  if (name === "result") return <svg {...common}><path d="M3 5v14h18"/><path d="m5 9 4 4 4-6 6 5"/><path d="m16 12 3 .2-.2 3"/></svg>;
  if (name === "trades") return <svg {...common}><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h5"/></svg>;
  if (name === "balance") return <svg {...common}><path d="m3 16 5-5 4 3 7-8"/><path d="M16 6h3v3"/></svg>;
  if (name === "dca") return <svg {...common}><path d="m12 3 7 4-7 4-7-4 7-4Z"/><path d="m5 11 7 4 7-4M5 15l7 4 7-4"/></svg>;
  return <svg {...common}><path d="M12 3 5 6v5c0 4.7 2.8 8.2 7 10 4.2-1.8 7-5.3 7-10V6l-7-3Z"/><path d="m9 12 2 2 4-5"/></svg>;
}

function MetricCard({ icon, label, value, tone = "normal" }: { icon: Parameters<typeof Icon>[0]["name"]; label: string; value: string; tone?: "normal" | "positive" | "negative" }) {
  return <article className={`aps-metric aps-${tone}`}><span className="aps-icon"><Icon name={icon} /></span><div><small>{label}</small><strong>{value}</strong></div></article>;
}

function Snapshot({ values, onCloseAll }: { values: SnapshotValues; onCloseAll: () => void }) {
  return <section className="aster-portfolio-snapshot" aria-label="Portfolio Snapshot" data-reference={REFERENCE}>
    <header><div className="aps-title-icon"><Icon name="positions" /></div><h2>PORTFOLIO SNAPSHOT</h2><span className="aps-live"><i />Live</span></header>
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
    <button type="button" className="aps-close-all" disabled={values.closeDisabled} onClick={onCloseAll}>{values.closeBusy ? "SLUITEN…" : "ALLES SLUITEN"}</button>
  </section>;
}

export function AsterPortfolioSnapshotEnhancer() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [values, setValues] = useState<SnapshotValues>(EMPTY);
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
          setHost(null);
          return;
        }
        document.documentElement.setAttribute("data-aster-compact-snapshot", "true");
        let mount = document.getElementById("aster-portfolio-snapshot-host");
        if (!mount) {
          mount = document.createElement("div");
          mount.id = "aster-portfolio-snapshot-host";
        }
        const battleRoot = impact.parentElement;
        if (battleRoot?.parentElement && mount.parentElement !== battleRoot.parentElement) battleRoot.parentElement.insertBefore(mount, battleRoot);
        else if (battleRoot?.parentElement && mount.nextElementSibling !== battleRoot) battleRoot.parentElement.insertBefore(mount, battleRoot);
        setHost(mount);
        setValues(readSnapshot());
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

  const closeAll = () => {
    const legacy = document.querySelector<HTMLButtonElement>(".portfolio-close-all");
    if (!legacy || legacy.disabled) return;
    legacy.click();
  };

  return host ? createPortal(<Snapshot values={values} onCloseAll={closeAll} />, host) : null;
}
