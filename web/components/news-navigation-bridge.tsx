"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { NewsView } from "@/components/news-view";
import { useAuthSession } from "@/components/auth-provider";
import {
  MOBILE_NAVIGATION_ORDER,
  NAVIGATION_PREFERENCES_EVENT,
  mobileNavigationDestinationVisible,
} from "@/lib/navigation-preferences";
import styles from "./news-view.module.css";

const VIEW_PARAM = "tmView";

function isNewsRoute() {
  return new URL(window.location.href).searchParams.get(VIEW_PARAM) === "news";
}

function openNews() {
  if (isNewsRoute()) return;
  const url = new URL(window.location.href);
  url.searchParams.set(VIEW_PARAM, "news");
  window.history.pushState({ ...window.history.state, news: true }, "", `${url.pathname}${url.search}${url.hash}`);
  window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }));
}

function newsButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "nav-button";
  button.dataset.destination = "news";
  button.setAttribute("aria-pressed", "false");
  button.setAttribute("aria-label", "Nieuws");
  const glyph = document.createElement("span");
  glyph.textContent = "▤";
  const label = document.createElement("small");
  label.textContent = "NIEUWS";
  button.append(glyph, label);
  button.addEventListener("click", openNews);
  return button;
}

function ensureNewsButton(nav: HTMLElement) {
  let news = nav.querySelector<HTMLButtonElement>(':scope > .nav-button[data-destination="news"]');
  if (news) return news;
  const journey = nav.querySelector<HTMLElement>(':scope > .nav-button[data-destination="journey"]');
  const aster = nav.querySelector<HTMLElement>(':scope > .nav-button[data-destination="aster"]');
  news = newsButton();
  if (journey) nav.insertBefore(news, journey);
  else if (aster?.nextSibling) nav.insertBefore(news, aster.nextSibling);
  else nav.appendChild(news);
  return news;
}

function syncContext(active: boolean) {
  const label = document.querySelector<HTMLElement>(".mobile-context > span:first-child");
  if (!label) return;
  if (active) {
    if (!label.dataset.newsPreviousLabel) label.dataset.newsPreviousLabel = label.textContent || "ASTER";
    label.textContent = "NIEUWS";
  } else if (label.dataset.newsPreviousLabel) {
    label.textContent = label.dataset.newsPreviousLabel;
    delete label.dataset.newsPreviousLabel;
  }
}

function normaliseBottomNavigation(nav: HTMLElement, active: boolean, uid?: string) {
  const news = ensureNewsButton(nav);
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
  const current = Array.from(nav.children).filter(
    (child): child is HTMLElement => child instanceof HTMLElement && !child.hidden && child.classList.contains("nav-button"),
  );
  if (visible.some((item, index) => current[index] !== item)) for (const item of visible) nav.appendChild(item);
  if (nav.style.getPropertyValue("--mobile-nav-count") !== String(visible.length)) {
    nav.style.setProperty("--mobile-nav-count", String(visible.length));
  }

  if (active) {
    for (const item of visible) {
      const selected = item.dataset.destination === "news";
      item.classList.toggle("active", selected);
      if (item.getAttribute("aria-pressed") !== String(selected)) item.setAttribute("aria-pressed", String(selected));
    }
  } else {
    news.classList.remove("active");
    news.setAttribute("aria-pressed", "false");
  }
}

function syncNavigation(active: boolean, uid?: string) {
  syncContext(active);
  for (const rail of document.querySelectorAll<HTMLElement>(".rail-nav")) {
    const news = ensureNewsButton(rail);
    if (active) {
      for (const item of rail.querySelectorAll<HTMLElement>(".nav-button")) {
        const selected = item.dataset.destination === "news";
        item.classList.toggle("active", selected);
        item.setAttribute("aria-pressed", String(selected));
      }
    } else {
      news.classList.remove("active");
      news.setAttribute("aria-pressed", "false");
    }
  }
  document.querySelectorAll<HTMLElement>(".bottom-nav").forEach((nav) => normaliseBottomNavigation(nav, active, uid));
}

export function NewsNavigationBridge() {
  const { user } = useAuthSession();
  const [active, setActive] = useState(false);
  const [target, setTarget] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const sync = () => {
      const next = isNewsRoute();
      setActive(next);
      setTarget(document.querySelector<HTMLElement>(".content"));
      syncNavigation(next, user?.uid);
    };
    const leaveNewsBeforeExistingNav = (event: MouseEvent) => {
      const item = (event.target as HTMLElement | null)?.closest<HTMLElement>(".nav-button[data-destination]");
      if (!item || item.dataset.destination === "news" || !isNewsRoute()) return;
      const url = new URL(window.location.href);
      url.searchParams.delete(VIEW_PARAM);
      window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
    };
    sync();
    document.addEventListener("click", leaveNewsBeforeExistingNav, true);
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
      document.removeEventListener("click", leaveNewsBeforeExistingNav, true);
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
      window.removeEventListener(NAVIGATION_PREFERENCES_EVENT, sync);
    };
  }, [user?.uid]);

  useEffect(() => {
    if (!active || !target) return;
    target.dataset.newsActive = "true";
    return () => { delete target.dataset.newsActive; };
  }, [active, target]);

  if (!active || !target) return null;
  return createPortal(<div className={styles.portal} data-news-portal="true"><NewsView /></div>, target);
}
