"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { MarketsPage } from "@/components/markets-page";
import { useAuthSession } from "@/components/auth-provider";
import {
  MOBILE_NAVIGATION_ORDER,
  NAVIGATION_PREFERENCES_EVENT,
  mobileNavigationDestinationVisible,
} from "@/lib/navigation-preferences";

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

function ensureMarketsButton(nav: HTMLElement) {
  let market = nav.querySelector<HTMLButtonElement>(':scope > .nav-button[data-destination="markets"]');
  if (market) return market;
  market = marketsButton();
  const aster = nav.querySelector<HTMLElement>(':scope > .nav-button[data-destination="aster"]');
  if (aster) nav.insertBefore(market, aster);
  else nav.appendChild(market);
  return market;
}

function syncContext(active: boolean) {
  const label = document.querySelector<HTMLElement>(".mobile-context > span:first-child");
  if (!label) return;
  if (active) {
    if (!label.dataset.marketsPreviousLabel) label.dataset.marketsPreviousLabel = label.textContent || "ASTER";
    if (label.textContent !== "MARKETS") label.textContent = "MARKETS";
  } else if (label.dataset.marketsPreviousLabel) {
    label.textContent = label.dataset.marketsPreviousLabel;
    delete label.dataset.marketsPreviousLabel;
  }
}

function normaliseBottomNavigation(nav: HTMLElement, active: boolean, uid?: string) {
  const market = ensureMarketsButton(nav);
  const order = MOBILE_NAVIGATION_ORDER as readonly string[];

  for (const item of Array.from(nav.querySelectorAll<HTMLElement>(":scope > .nav-button[data-destination]"))) {
    const destination = item.dataset.destination || "";
    const hidden = !order.includes(destination) || !mobileNavigationDestinationVisible(destination, uid);
    if (item.hidden !== hidden) item.hidden = hidden;
    if (item.getAttribute("aria-hidden") !== String(hidden)) item.setAttribute("aria-hidden", String(hidden));
    if (item.tabIndex !== (hidden ? -1 : 0)) item.tabIndex = hidden ? -1 : 0;
  }

  const visible = MOBILE_NAVIGATION_ORDER.flatMap((destination) => {
    if (!mobileNavigationDestinationVisible(destination, uid)) return [];
    const item = nav.querySelector<HTMLElement>(`:scope > .nav-button[data-destination="${destination}"]`);
    return item ? [item] : [];
  });
  const visibleChildren = Array.from(nav.children).filter(
    (child): child is HTMLElement => child instanceof HTMLElement && !child.hidden && child.classList.contains("nav-button"),
  );
  if (visible.some((item, index) => visibleChildren[index] !== item)) for (const item of visible) nav.appendChild(item);
  if (nav.style.getPropertyValue("--mobile-nav-count") !== String(visible.length)) {
    nav.style.setProperty("--mobile-nav-count", String(visible.length));
  }

  if (active) {
    for (const item of visible) {
      const selected = item.dataset.destination === "markets";
      item.classList.toggle("active", selected);
      if (item.getAttribute("aria-pressed") !== String(selected)) item.setAttribute("aria-pressed", String(selected));
    }
  } else {
    market.classList.remove("active");
    market.setAttribute("aria-pressed", "false");
  }
}

function syncNavigation(active: boolean, uid?: string) {
  syncContext(active);

  for (const rail of document.querySelectorAll<HTMLElement>(".rail-nav")) {
    const button = ensureMarketsButton(rail);
    if (active) {
      for (const item of rail.querySelectorAll<HTMLElement>(".nav-button")) {
        const selected = item.dataset.destination === "markets";
        item.classList.toggle("active", selected);
        item.setAttribute("aria-pressed", String(selected));
      }
    } else {
      button.classList.remove("active");
      button.setAttribute("aria-pressed", "false");
    }
  }

  document.querySelectorAll<HTMLElement>(".bottom-nav").forEach((nav) => normaliseBottomNavigation(nav, active, uid));
}

export function MarketsNavigationBridge() {
  const { user } = useAuthSession();
  const [active, setActive] = useState(false);
  const [target, setTarget] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const sync = () => {
      const next = isMarketsRoute();
      setActive(next);
      setTarget(document.querySelector<HTMLElement>(".content"));
      syncNavigation(next, user?.uid);
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
    window.addEventListener(NAVIGATION_PREFERENCES_EVENT, sync);
    let frame = 0;
    const observer = new MutationObserver(() => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => { frame = 0; sync(); });
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
      document.removeEventListener("click", leaveMarketsBeforeExistingNav, true);
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
      window.removeEventListener(NAVIGATION_PREFERENCES_EVENT, sync);
    };
  }, [user?.uid]);

  useEffect(() => {
    if (!active || !target) return;
    target.dataset.marketsActive = "true";
    return () => { delete target.dataset.marketsActive; };
  }, [active, target]);

  if (!active || !target) return null;
  return createPortal(<div className="markets-portal"><MarketsPage /></div>, target);
}
