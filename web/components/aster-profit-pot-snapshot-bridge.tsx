"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";
import { derivePortfolioCycleCard, type PortfolioCycleCardState } from "@/lib/portfolio-cycle-card";

const PROFIT_POT_REFERENCE = "file_00000000f5ec8210bf3f2c300b972c25";
const HOST_ID = "aster-profit-pot-snapshot-host";
const CYCLE_REFERENCE_INACTIVE = "file_00000000192481f495e9311d4ed77933";
const CYCLE_REFERENCE_ACTIVE = "file_00000000b78081f4a8a332da9a783f3b";

function existingProfitPotValue(): string {
  const rows = Array.from(document.querySelectorAll<HTMLElement>(".metric-strip .metric"));
  const row = rows.find((item) => item.querySelector("span")?.textContent?.trim().toUpperCase() === "PROFIT POT / SPOT");
  const value = row?.querySelector<HTMLElement>("strong")?.textContent?.trim() || "";
  if (!value || value === "—") return "US$ —";
  return value;
}

function profitPotIcon() {
  return <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
    <path d="M9 5.5h14M11 5.5v4h10v-4M8 11.5h16v14.5H8z" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M11.5 16h9M11.5 20.5h9" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" />
  </svg>;
}


function formatCycleMoney(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "US$ —";
  return `US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}`;
}

function formatCyclePercent(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}%`;
}

function cycleIcon() {
  return <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
    <path d="M25.4 10.4A11 11 0 0 0 7.2 7.7L4.5 10.4M4.5 10.4V5.5M4.5 10.4h4.9M6.6 21.5A11 11 0 0 0 24.8 24l2.7-2.7M27.5 21.3v4.9M27.5 21.3h-4.9" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>;
}

function openPortfolioTakeProfitSettings() {
  const maker = document.getElementById("strategy-2-maker");
  if (!maker) return;
  const portfolioButton = Array.from(maker.querySelectorAll<HTMLButtonElement>(".tp-tabs button"))
    .find((button) => button.textContent?.trim().toLowerCase() === "portfolio");
  portfolioButton?.click();
  window.requestAnimationFrame(() => {
    const panel = maker.querySelector<HTMLElement>(".portfolio-tp-panel") || maker;
    panel.scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

function PortfolioCycleCard({ state }: { state: PortfolioCycleCardState }) {
  if (!state.active) {
    return <button
      type="button"
      className="aps-portfolio-cycle-card is-inactive"
      data-reference={CYCLE_REFERENCE_INACTIVE}
      onClick={openPortfolioTakeProfitSettings}
      aria-label="Portfolio cyclus niet ingesteld. Portfolio Take Profit instellen."
    >
      <span className="aps-cycle-icon">{cycleIcon()}</span>
      <span className="aps-cycle-inactive-copy">
        <small>PORTFOLIO CYCLUS</small>
        <strong>Niet ingesteld</strong>
        <em>Portfolio TP niet actief</em>
      </span>
      <span className="aps-cycle-setup">Instellen</span>
    </button>;
  }

  const progress = Math.max(0, Math.min(100, state.progressPercent ?? 0));
  return <button
    type="button"
    className="aps-portfolio-cycle-card is-active"
    data-reference={CYCLE_REFERENCE_ACTIVE}
    onClick={openPortfolioTakeProfitSettings}
    aria-label={`Portfolio cyclus ${Math.round(progress)} procent. Nog ${formatCycleMoney(state.remainingUsd)} tot sluiten.`}
  >
    <span className="aps-cycle-active-head">
      <small>PORTFOLIO CYCLUS</small>
      <strong>{Math.round(progress)}%</strong>
    </span>
    <span className="aps-cycle-progress" aria-hidden="true"><i style={{ width: `${progress}%` }} /></span>
    <span className="aps-cycle-active-foot">
      <span><b>Nog {formatCycleMoney(state.remainingUsd)}</b><em>+{formatCyclePercent(state.remainingPercent)} tot sluiten</em></span>
      <u>{state.statusLabel}</u>
    </span>
  </button>;
}

export function AsterProfitPotSnapshotBridge() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [value, setValue] = useState("US$ —");
  const [cycleState, setCycleState] = useState<PortfolioCycleCardState>({ active: false, statusLabel: "Niet ingesteld", progressPercent: null, remainingUsd: null, remainingPercent: null });

  useEffect(() => {
    if (!host) return;
    let alive = true;
    const refreshCycle = async () => {
      try {
        const payload = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" });
        const next = derivePortfolioCycleCard(payload);
        if (alive) setCycleState(next);
      } catch {
        if (alive) setCycleState({ active: false, statusLabel: "Niet ingesteld", progressPercent: null, remainingUsd: null, remainingPercent: null });
      }
    };
    void refreshCycle();
    const timer = window.setInterval(refreshCycle, 10000);
    const onVisible = () => { if (document.visibilityState === "visible") void refreshCycle(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [host]);

  useEffect(() => {
    let alive = true;
    let frame = 0;
    const sync = () => {
      if (!alive) return;
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        if (!alive) return;
        const snapshot = document.querySelector<HTMLElement>(".aster-portfolio-snapshot");
        const grid = snapshot?.querySelector<HTMLElement>(":scope > .aps-grid");
        if (!snapshot || !grid) {
          document.getElementById(HOST_ID)?.remove();
          setHost((current) => current === null ? current : null);
          setValue("US$ —");
          return;
        }
        let mount = document.getElementById(HOST_ID) as HTMLElement | null;
        if (!mount) {
          mount = document.createElement("div");
          mount.id = HOST_ID;
        }
        if (mount.parentElement !== snapshot || grid.nextElementSibling !== mount) grid.insertAdjacentElement("afterend", mount);
        setHost((current) => current === mount ? current : mount);
        const next = existingProfitPotValue();
        setValue((current) => current === next ? current : next);
      });
    };

    const observer = new MutationObserver(sync);
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    sync();
    const timer = window.setInterval(sync, 5000);
    return () => {
      alive = false;
      observer.disconnect();
      window.clearInterval(timer);
      window.cancelAnimationFrame(frame);
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
      document.getElementById(HOST_ID)?.remove();
    };
  }, []);

  if (!host) return null;
  return createPortal(
    <div className="aps-profit-pot-row" aria-label="Profit Pot / Spot">
      <article className="aps-profit-pot-card" data-reference={PROFIT_POT_REFERENCE}>
        <span className="aps-profit-pot-icon">{profitPotIcon()}</span>
        <div className="aps-profit-pot-copy">
          <small>PROFIT POT / SPOT</small>
          <strong>{value}</strong>
        </div>
      </article>
      <div id="aster-profit-sweep-settings-host" />
      <PortfolioCycleCard state={cycleState} />
    </div>,
    host,
  );
}
