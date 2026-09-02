"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { MarketsPage } from "@/components/markets-page";

const VIEW_PARAM = "tmView";

function isMarketsRoute() {
  return new URL(window.location.href).searchParams.get(VIEW_PARAM) === "markets";
}

function openMarkets() {
  if (isMarketsRoute()) return;
  const url = new URL(window.location.href);
  url.searchParams.set(VIEW_PARAM, "markets");
  window.history.pushState({ ...window.history.state, markets: true }, "", `${url.pathname}${url.search}${url.hash}`);
  window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }));
}

function marketsButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "nav-button";
  button.dataset.destination = "markets";
  button.setAttribute("aria-pressed", "false");
  button.setAttribute("aria-label", "Markets");
  const glyph = document.createElement("span");
  glyph.textContent = "M";
  const label = document.createElement("small");
  label.textContent = "MARKETS";
  button.append(glyph, label);
  button.addEventListener("click", openMarkets);
  return button;
}

function syncContext(active: boolean) {
  const label = document.querySelector<HTMLElement>(".mobile-context > span:first-child");
  if (!label) return;
  if (active) {
    if (!label.dataset.marketsPreviousLabel) label.dataset.marketsPreviousLabel = label.textContent || "ASTER";
    if (label.textContent !== "MARKETS") label.textContent = "MARKETS";
  } else if (label.dataset.marketsPreviousLabel) {
    const previous = label.dataset.marketsPreviousLabel;
    if (label.textContent !== previous) label.textContent = previous;
    delete label.dataset.marketsPreviousLabel;
  }
}

const USER_MAIN_DESTINATIONS = ["markets", "aster", "journey", "wallet"] as const;
const HIDDEN_MAIN_DESTINATIONS = new Set(["positions", "risk", "hyperliquid", "admin"]);

function syncNavigation(active: boolean) {
  syncContext(active);
  for (const nav of document.querySelectorAll<HTMLElement>(".rail-nav, .bottom-nav")) {
    for (const item of nav.querySelectorAll<HTMLElement>(".nav-button[data-destination]")) {
      const destination = item.dataset.destination || "";
      if (HIDDEN_MAIN_DESTINATIONS.has(destination)) item.remove();
    }
    let button = nav.querySelector<HTMLButtonElement>('[data-destination="markets"]');
    const aster = nav.querySelector<HTMLElement>('[data-destination="aster"]');
    if (!button && aster) {
      button = marketsButton();
      nav.insertBefore(button, aster);
    }
    const byDestination = new Map(
      Array.from(nav.querySelectorAll<HTMLElement>(".nav-button[data-destination]")).map((item) => [item.dataset.destination || "", item]),
    );
    for (const destination of USER_MAIN_DESTINATIONS) {
      const item = byDestination.get(destination);
      if (item) nav.appendChild(item);
    }
    if (nav.classList.contains("bottom-nav")) nav.style.setProperty("--mobile-nav-count", "4");
    if (active) {
      for (const item of nav.querySelectorAll<HTMLElement>(".nav-button")) {
        const selected = item.dataset.destination === "markets";
        item.classList.toggle("active", selected);
        item.setAttribute("aria-pressed", String(selected));
      }
    } else if (button) {
      button.classList.remove("active");
      button.setAttribute("aria-pressed", "false");
    }
  }
}

export function MarketsNavigationBridge() {
  const [active, setActive] = useState(false);
  const [target, setTarget] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const sync = () => {
      const next = isMarketsRoute();
      setActive(next);
      setTarget(document.querySelector<HTMLElement>(".content"));
      syncNavigation(next);
    };
    const leaveMarketsBeforeExistingNav = (event: MouseEvent) => {
      const item = (event.target as HTMLElement | null)?.closest<HTMLElement>(".nav-button[data-destination]");
      if (!item || item.dataset.destination === "markets" || !isMarketsRoute()) return;
      const url = new URL(window.location.href);
      url.searchParams.delete(VIEW_PARAM);
      window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
    };
    sync();
    document.addEventListener("click", leaveMarketsBeforeExistingNav, true);
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    const observer = new MutationObserver(sync);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      document.removeEventListener("click", leaveMarketsBeforeExistingNav, true);
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
    };
  }, []);

  useEffect(() => {
    if (!active || !target) return;
    target.dataset.marketsActive = "true";
    return () => { delete target.dataset.marketsActive; };
  }, [active, target]);

  if (!active || !target) return null;
  return createPortal(<div className="markets-portal"><MarketsPage /></div>, target);
}
