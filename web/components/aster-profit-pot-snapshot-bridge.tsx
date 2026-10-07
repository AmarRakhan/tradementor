"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest, subscribeSharedAsterSnapshot } from "@/lib/cloud-client";
import { derivePortfolioCycleCard, type PortfolioCycleCardState } from "@/lib/portfolio-cycle-card";

const PROFIT_POT_REFERENCE = "file_00000000a6388210976eaf5f7d7386e0";
const HOST_ID = "aster-profit-pot-snapshot-host";
const CYCLE_REFERENCE_INACTIVE = "file_00000000ba448210b16f35eaf915a01f";
const CYCLE_REFERENCE_ACTIVE = "file_00000000ba448210b16f35eaf915a01f";

function profitPotIcon() {
  return <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
    <path d="M9 5.5h14M11 5.5v4h10v-4M8 11.5h16v14.5H8z" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M11.5 16h9M11.5 20.5h9" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" />
  </svg>;
}


function formatProfitPotMoney(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "US$ —";
  return `US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}`;
}

function formatCycleMoney(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "US$ —";
  return `US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}`;
}

function cycleIcon() {
  return <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
    <path d="M25.4 10.4A11 11 0 0 0 7.2 7.7L4.5 10.4M4.5 10.4V5.5M4.5 10.4h4.9M6.6 21.5A11 11 0 0 0 24.8 24l2.7-2.7M27.5 21.3v4.9M27.5 21.3h-4.9" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>;
}

function openPortfolioTakeProfitSettings() {
  const openPanel = (attempt = 0) => {
    const maker = document.getElementById("strategy-2-maker");
    if (!maker) {
      if (attempt < 8) window.requestAnimationFrame(() => openPanel(attempt + 1));
      return;
    }
    const portfolioButton = Array.from(maker.querySelectorAll<HTMLButtonElement>(".tp-tabs button"))
      .find((button) => button.textContent?.trim().toLowerCase() === "portfolio");
    portfolioButton?.click();
    window.requestAnimationFrame(() => {
      const panel = maker.querySelector<HTMLElement>(".portfolio-tp-panel") || maker;
      panel.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  };

  const settingsButton = Array.from(document.querySelectorAll<HTMLButtonElement>(".aster-subtabs button"))
    .find((button) => button.textContent?.trim().toLowerCase().includes("instellingen"));
  if (settingsButton && settingsButton.getAttribute("aria-pressed") !== "true") {
    settingsButton.click();
    window.requestAnimationFrame(() => openPanel());
    return;
  }
  openPanel();
}

function PortfolioCycleCard({ state }: { state: PortfolioCycleCardState }) {
  if (!state.active) {
    return <button
      type="button"
      className="aps-portfolio-cycle-card is-inactive"
      data-reference={CYCLE_REFERENCE_INACTIVE}
      onClick={openPortfolioTakeProfitSettings}
      aria-label="Portfolio cyclus uit. Geen actieve cyclus. Tik voor instellingen."
    >
      <span className="aps-cycle-icon">{cycleIcon()}</span>
      <span className="aps-cycle-inactive-copy">
        <small>PORTFOLIO CYCLUS</small>
        <strong>UIT</strong>
        <em>Geen actieve cyclus</em>
      </span>
    </button>;
  }

  const progress = Math.max(0, Math.min(100, state.progressPercent ?? 0));
  return <button
    type="button"
    className="aps-portfolio-cycle-card is-active"
    data-reference={CYCLE_REFERENCE_ACTIVE}
    onClick={openPortfolioTakeProfitSettings}
    aria-label={`Portfolio cyclus ${Math.round(progress)} procent behaald. Nog ${formatCycleMoney(state.remainingUsd)} tot doel.`}
  >
    <span className="aps-cycle-icon">{cycleIcon()}</span>
    <span className="aps-cycle-active-copy">
      <span className="aps-cycle-active-head">
        <small>PORTFOLIO CYCLUS</small>
        <strong>{Math.round(progress)}%</strong>
      </span>
      <span className="aps-cycle-progress" aria-hidden="true"><i style={{ width: `${progress}%` }} /></span>
      <b className="aps-cycle-remaining">Nog {formatCycleMoney(state.remainingUsd)}</b>
    </span>
  </button>;
}

export function AsterProfitPotSnapshotBridge() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [todayTransferred, setTodayTransferred] = useState<number | null>(null);
  const [pendingSavings, setPendingSavings] = useState<number | null>(null);
  const [cycleState, setCycleState] = useState<PortfolioCycleCardState>({ active: false, statusLabel: "Niet ingesteld", progressPercent: null, remainingUsd: null, remainingPercent: null });

  useEffect(() => {
    if (!host) return;
    return subscribeSharedAsterSnapshot((payload) => {
      try {
        setCycleState(derivePortfolioCycleCard(payload));
      } catch {
        setCycleState({ active: false, statusLabel: "Niet ingesteld", progressPercent: null, remainingUsd: null, remainingPercent: null });
      }
    });
  }, [host]);

  useEffect(() => {
    if (!host) return;
    let alive = true;
    const refreshProfitPot = async () => {
      try {
        const payload = await authenticatedRequest("/api/exchanges/aster/profit-sweep-settings", { cache: "no-store" });
        const transferred = Number(payload.todayTransferred ?? 0);
        const pending = Number(payload.pendingSavings ?? 0);
        if (alive) {
          setTodayTransferred(Number.isFinite(transferred) ? transferred : 0);
          setPendingSavings(Number.isFinite(pending) ? pending : 0);
        }
      } catch {
        if (alive) {
          setTodayTransferred(null);
          setPendingSavings(null);
        }
      }
    };
    void refreshProfitPot();
    const timer = window.setInterval(refreshProfitPot, 10000);
    const onVisible = () => { if (document.visibilityState === "visible") void refreshProfitPot(); };
    const onUpdated = () => { void refreshProfitPot(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("aster-profit-sweep-settings-updated", onUpdated);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("aster-profit-sweep-settings-updated", onUpdated);
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
          return;
        }
        let mount = document.getElementById(HOST_ID) as HTMLElement | null;
        if (!mount) {
          mount = document.createElement("div");
          mount.id = HOST_ID;
        }
        if (mount.parentElement !== snapshot || grid.nextElementSibling !== mount) grid.insertAdjacentElement("afterend", mount);
        setHost((current) => current === mount ? current : mount);
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
  const profitPotTodayDisplay = todayTransferred === null || pendingSavings === null
    ? null
    : todayTransferred + pendingSavings;
  return createPortal(
    <div className="aps-profit-pot-row" aria-label="Profit Pot / Spot">
      <button
        type="button"
        className="aps-profit-pot-card"
        data-reference={PROFIT_POT_REFERENCE}
        onClick={() => window.dispatchEvent(new CustomEvent("aster-profit-pot-open"))}
        aria-label={`Profit Pot / Spot. Vandaag richting Spot: ${formatProfitPotMoney(profitPotTodayDisplay)}. Dit is vandaag succesvol overgezet plus de huidige spaarbuffer. Tik voor instellingen.`}
      >
        <span className="aps-profit-pot-icon">{profitPotIcon()}</span>
        <span className="aps-profit-pot-copy">
          <small>PROFIT POT / SPOT</small>
          <strong>{formatProfitPotMoney(profitPotTodayDisplay)}</strong>
          <em>Vandaag</em>
        </span>
      </button>
      <div id="aster-profit-sweep-settings-host" />
      <div id="aster-position-loss-auto-hedge-host" />
      <PortfolioCycleCard state={cycleState} />
    </div>,
    host,
  );
}
