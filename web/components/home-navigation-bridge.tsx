"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { HomeTransferPage } from "@/components/home-transfer-page";
import { SniperDashboard } from "@/components/sniper-dashboard";
import { useAuthSession } from "@/components/auth-provider";
import { ContinuityStartupGuard } from "@/components/continuity-monitor";

const VIEW_PARAM = "tmView";
const SESSION_EXIT = "tradementor.home.explicitExit.v1";
type BridgeView = "home" | "sniper" | null;

function currentView(): BridgeView {
  const value = new URL(window.location.href).searchParams.get(VIEW_PARAM);
  return value === "home" || value === "sniper" ? value : null;
}

function urlWithView(view: BridgeView) {
  const url = new URL(window.location.href);
  if (view) url.searchParams.set(VIEW_PARAM, view);
  else url.searchParams.delete(VIEW_PARAM);
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
  button.type = "button";
  button.className = "nav-button";
  button.dataset.destination = destination;
  button.setAttribute("aria-label", labelText);
  button.setAttribute("aria-pressed", "false");
  const glyph = document.createElement("span");
  glyph.textContent = glyphText;
  const label = document.createElement("small");
  label.textContent = labelText;
  button.append(glyph, label);
  button.addEventListener("click", () => openView(destination));
  return button;
}

function ensureHome(nav: HTMLElement) {
  let home = nav.querySelector<HTMLButtonElement>(':scope > .nav-button[data-destination="home"]');
  if (home) return home;
  home = bridgeButton("home", "⌂", "HOME");
  const first = nav.querySelector<HTMLElement>(":scope > .nav-button[data-destination]");
  nav.insertBefore(home, first || null);
  return home;
}

function ensureSniper(nav: HTMLElement) {
  let sniper = nav.querySelector<HTMLButtonElement>(':scope > .nav-button[data-destination="sniper"]');
  if (sniper) return sniper;
  sniper = bridgeButton("sniper", "S", "SNIPER");
  const aster = nav.querySelector<HTMLElement>(':scope > .nav-button[data-destination="aster"]');
  const news = nav.querySelector<HTMLElement>(':scope > .nav-button[data-destination="news"]');
  if (news) nav.insertBefore(sniper, news);
  else if (aster?.nextSibling) nav.insertBefore(sniper, aster.nextSibling);
  else if (aster) nav.appendChild(sniper);
  else nav.appendChild(sniper);
  return sniper;
}

function syncNav(view: BridgeView) {
  document.querySelectorAll<HTMLElement>(".bottom-nav,.rail-nav").forEach((nav) => {
    const home = ensureHome(nav);
    const sniper = ensureSniper(nav);
    if (view) {
      nav.querySelectorAll<HTMLElement>(":scope > .nav-button[data-destination]").forEach((item) => {
        const selected = item.dataset.destination === view;
        item.classList.toggle("active", selected);
        item.setAttribute("aria-pressed", String(selected));
      });
    } else {
      for (const item of [home, sniper]) {
        item.classList.remove("active");
        item.setAttribute("aria-pressed", "false");
      }
    }
  });
  const label = document.querySelector<HTMLElement>(".mobile-context > span:first-child");
  if (label && view) label.textContent = view === "sniper" ? "SNIPER" : "HOME";
}

export function HomeNavigationBridge() {
  const { cloudReady, betaOwner, user } = useAuthSession();
  const [view, setView] = useState<BridgeView>(null);
  const [target, setTarget] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const initialUrl = new URL(window.location.href);
    const explicitView = initialUrl.searchParams.has(VIEW_PARAM);
    const explicitHash = /^#\/(hyperliquid|aster|journey|positions|risk|wallet|admin)/.test(initialUrl.hash);
    if (!explicitView && !explicitHash) {
      const launchUrl = new URL(window.location.href);
      launchUrl.searchParams.delete(VIEW_PARAM);
      launchUrl.hash = "/aster";
      window.history.replaceState({ ...window.history.state, destination: "aster" }, "", `${launchUrl.pathname}${launchUrl.search}${launchUrl.hash}`);
    }

    const sync = () => {
      const next = currentView();
      setView(next);
      setTarget(document.querySelector<HTMLElement>(".content"));
      syncNav(next);
    };

    const leave = (event: MouseEvent) => {
      const item = (event.target as HTMLElement | null)?.closest<HTMLElement>(".nav-button[data-destination]");
      const active = currentView();
      if (!item || !active || item.dataset.destination === active) return;
      if (active === "home") window.sessionStorage.setItem(SESSION_EXIT, "1");
      if (item.dataset.destination !== "sniper" && item.dataset.destination !== "home") {
        window.history.replaceState(window.history.state, "", urlWithView(null));
      }
    };

    sync();
    document.addEventListener("click", leave, true);
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    let frame = 0;
    const observer = new MutationObserver(() => {
      if (frame) return;
      frame = requestAnimationFrame(() => { frame = 0; sync(); });
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
      document.removeEventListener("click", leave, true);
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
    };
  }, []);

  useEffect(() => {
    if (!view || !target) return;
    target.dataset.bridgeView = view;
    if (view === "home") target.dataset.homeActive = "true";
    return () => {
      delete target.dataset.bridgeView;
      delete target.dataset.homeActive;
    };
  }, [view, target]);

  const portal = useMemo(() => {
    if (!view || !target) return null;
    if (view === "home") return <div className="tm-home-portal"><HomeTransferPage /></div>;
    return <div className="tm-sniper-portal"><SniperDashboard cloudReady={cloudReady} /></div>;
  }, [view, target, cloudReady]);

  const startupGuard = <ContinuityStartupGuard
    enabled={Boolean(cloudReady && betaOwner && user?.uid && view !== "home")}
    onOpen={() => openView("home")}
  />;
  if (!portal || !target) return startupGuard;
  return <>{startupGuard}{createPortal(portal, target)}</>;
}
