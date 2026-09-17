"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { HomeTransferPage } from "@/components/home-transfer-page";
import { SniperDashboard } from "@/components/sniper-dashboard";
import { authenticatedRequest } from "@/lib/cloud-client";
import { useAuthSession } from "@/components/auth-provider";
import type { ExchangeSnapshot, ExchangeSnapshots } from "@/lib/use-exchange-data";

const VIEW_PARAM = "tmView";
const SESSION_EXIT = "tradementor.home.explicitExit.v1";
type BridgeView = "home" | "sniper" | null;

const emptySnapshot = (): ExchangeSnapshot => ({ loading: false, data: null, error: "", updatedAt: null, source: "none", serverConfirmed: false });

function currentView(): BridgeView {
  const value = new URL(window.location.href).searchParams.get(VIEW_PARAM);
  return value === "home" || value === "sniper" ? value : null;
}
function urlWithView(view: BridgeView) {
  const url = new URL(window.location.href);
  if (view) url.searchParams.set(VIEW_PARAM, view); else url.searchParams.delete(VIEW_PARAM);
  return `${url.pathname}${url.search}${url.hash}`;
}
function openView(view: Exclude<BridgeView, null>) {
  if (currentView() === view) return;
  if (view === "home") window.sessionStorage.removeItem(SESSION_EXIT);
  window.history.pushState({ ...window.history.state, tmView: view }, "", urlWithView(view));
  window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }));
}
function bridgeButton(destination: "home" | "sniper", glyphText: string, labelText: string) {
  const button = document.createElement("button");
  button.type = "button"; button.className = "nav-button"; button.dataset.destination = destination;
  button.setAttribute("aria-label", labelText); button.setAttribute("aria-pressed", "false");
  const glyph = document.createElement("span"); glyph.textContent = glyphText;
  const label = document.createElement("small"); label.textContent = labelText;
  button.append(glyph, label); button.addEventListener("click", () => openView(destination)); return button;
}
function ensureButton(container: HTMLElement, destination: "home" | "sniper", glyph: string, label: string, after?: string) {
  let button = container.querySelector<HTMLButtonElement>(`:scope > .nav-button[data-destination="${destination}"]`);
  if (button) return button;
  button = bridgeButton(destination, glyph, label);
  if (after) {
    const anchor = container.querySelector<HTMLElement>(`:scope > .nav-button[data-destination="${after}"]`);
    if (anchor?.nextSibling) container.insertBefore(button, anchor.nextSibling); else if (anchor) container.appendChild(button); else container.appendChild(button);
  } else {
    const first = container.querySelector<HTMLElement>(":scope > .nav-button[data-destination]");
    container.insertBefore(button, first || null);
  }
  return button;
}
function syncNav(view: BridgeView) {
  document.querySelectorAll<HTMLElement>(".bottom-nav,.rail-nav").forEach((nav) => {
    ensureButton(nav, "home", "⌂", "HOME");
    ensureButton(nav, "sniper", "S", "SNIPER", "aster");
    if (view) {
      nav.querySelectorAll<HTMLElement>(":scope > .nav-button[data-destination]").forEach((item) => {
        const selected = item.dataset.destination === view;
        item.classList.toggle("active", selected); item.setAttribute("aria-pressed", String(selected));
      });
    } else {
      for (const id of ["home", "sniper"]) {
        const item = nav.querySelector<HTMLElement>(`:scope > .nav-button[data-destination="${id}"]`);
        item?.classList.remove("active"); item?.setAttribute("aria-pressed", "false");
      }
    }
  });
  const label = document.querySelector<HTMLElement>(".mobile-context > span:first-child");
  if (label && view) label.textContent = view === "sniper" ? "SNIPER" : "HOME";
}

export function HomeNavigationBridge() {
  const { cloudReady } = useAuthSession();
  const [view, setView] = useState<BridgeView>(null);
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const [sniperSnapshots, setSniperSnapshots] = useState<ExchangeSnapshots>({ hyperliquid: emptySnapshot(), aster: emptySnapshot() });

  const refreshSniperAccounts = useCallback(async () => {
    if (!cloudReady) return;
    setSniperSnapshots((current) => ({
      hyperliquid: { ...current.hyperliquid, loading: true, error: "" },
      aster: { ...current.aster, loading: true, error: "" },
    }));
    const [hyper, aster] = await Promise.allSettled([
      authenticatedRequest("/api/exchanges/hyperliquid"),
      authenticatedRequest("/api/exchanges/aster"),
    ]);
    const now = Date.now();
    setSniperSnapshots({
      hyperliquid: hyper.status === "fulfilled"
        ? { loading: false, data: hyper.value as Record<string, unknown>, error: "", updatedAt: now, source: "server", serverConfirmed: true }
        : { loading: false, data: null, error: hyper.reason instanceof Error ? hyper.reason.message : "Hyperliquid niet beschikbaar", updatedAt: null, source: "none", serverConfirmed: false },
      aster: aster.status === "fulfilled"
        ? { loading: false, data: aster.value as Record<string, unknown>, error: "", updatedAt: now, source: "server", serverConfirmed: true }
        : { loading: false, data: null, error: aster.reason instanceof Error ? aster.reason.message : "Aster niet beschikbaar", updatedAt: null, source: "none", serverConfirmed: false },
    });
  }, [cloudReady]);

  useEffect(() => {
    const initialUrl = new URL(window.location.href);
    const explicitView = initialUrl.searchParams.has(VIEW_PARAM);
    const explicitHash = /^#\/(hyperliquid|aster|journey|positions|risk|wallet|admin)/.test(initialUrl.hash);
    if (!explicitView && !explicitHash && !window.sessionStorage.getItem(SESSION_EXIT)) {
      window.history.replaceState({ ...window.history.state, tmView: "home" }, "", urlWithView("home"));
    }
    const sync = () => { const next = currentView(); setView(next); setTarget(document.querySelector<HTMLElement>(".content")); syncNav(next); };
    const leave = (event: MouseEvent) => {
      const item = (event.target as HTMLElement | null)?.closest<HTMLElement>(".nav-button[data-destination]");
      const activeView = currentView();
      if (!item || !activeView || item.dataset.destination === activeView) return;
      if (activeView === "home") window.sessionStorage.setItem(SESSION_EXIT, "1");
      window.history.replaceState(window.history.state, "", urlWithView(null));
    };
    sync(); document.addEventListener("click", leave, true); window.addEventListener("hashchange", sync); window.addEventListener("popstate", sync);
    let frame = 0; const observer = new MutationObserver(() => { if (frame) return; frame = requestAnimationFrame(() => { frame=0; sync(); }); }); observer.observe(document.body,{childList:true,subtree:true});
    return () => { observer.disconnect(); if(frame)cancelAnimationFrame(frame); document.removeEventListener("click",leave,true); window.removeEventListener("hashchange",sync); window.removeEventListener("popstate",sync); };
  }, []);

  useEffect(() => {
    if (view !== "sniper") return;
    void refreshSniperAccounts();
  }, [view, refreshSniperAccounts]);

  useEffect(() => {
    if(!view||!target)return;
    target.dataset.bridgeView=view;
    if (view === "home") target.dataset.homeActive="true";
    return()=>{delete target.dataset.bridgeView; delete target.dataset.homeActive;};
  }, [view,target]);

  const portal = useMemo(() => {
    if (!view || !target) return null;
    return view === "home"
      ? <div className="tm-home-portal"><HomeTransferPage /></div>
      : <div className="tm-sniper-portal"><SniperDashboard snapshots={sniperSnapshots} cloudReady={cloudReady} /></div>;
  }, [view, target, sniperSnapshots, cloudReady]);

  if(!portal||!target)return null;
  return createPortal(portal,target);
}
