"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { NewsView } from "@/components/news-view";
import styles from "./news-view.module.css";

const VIEW_PARAM = "tmView";
const MOBILE_DESTINATIONS = ["markets", "aster", "news", "journey", "wallet"] as const;

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
  let news = nav.querySelector<HTMLButtonElement>('[data-destination="news"]');
  if (news) return news;
  const journey = nav.querySelector<HTMLElement>('[data-destination="journey"]');
  const aster = nav.querySelector<HTMLElement>('[data-destination="aster"]');
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

function normaliseBottomNavigation(nav: HTMLElement, active: boolean) {
  const news = ensureNewsButton(nav);
  for (const item of Array.from(nav.querySelectorAll<HTMLElement>(":scope > .nav-button[data-destination]"))) {
    const destination = item.dataset.destination || "";
    const hidden = !MOBILE_DESTINATIONS.includes(destination as (typeof MOBILE_DESTINATIONS)[number]);
    item.hidden = hidden;
    item.setAttribute("aria-hidden", String(hidden));
    item.tabIndex = hidden ? -1 : 0;
  }
  const visible = MOBILE_DESTINATIONS.flatMap((destination) => {
    const item = nav.querySelector<HTMLElement>(`:scope > .nav-button[data-destination="${destination}"]`);
    return item ? [item] : [];
  });
  const visibleChildren = Array.from(nav.children).filter((child): child is HTMLElement => child instanceof HTMLElement && !child.hidden && child.classList.contains("nav-button"));
  if (visible.some((item, index) => visibleChildren[index] !== item)) for (const item of visible) nav.appendChild(item);
  nav.style.setProperty("--mobile-nav-count", String(visible.length));
  if (active) {
    for (const item of visible) {
      const selected = item.dataset.destination === "news";
      item.classList.toggle("active", selected);
      item.setAttribute("aria-pressed", String(selected));
    }
  } else {
    news.classList.remove("active");
    news.setAttribute("aria-pressed", "false");
  }
}

function syncNavigation(active: boolean) {
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
  document.querySelectorAll<HTMLElement>(".bottom-nav").forEach((nav) => normaliseBottomNavigation(nav, active));
}

export function NewsNavigationBridge() {
  const [active, setActive] = useState(false);
  const [target, setTarget] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const sync = () => {
      const next = isNewsRoute();
      setActive(next);
      setTarget(document.querySelector<HTMLElement>(".content"));
      syncNavigation(next);
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
    };
  }, []);

  useEffect(() => {
    if (!active || !target) return;
    target.dataset.newsActive = "true";
    return () => { delete target.dataset.newsActive; };
  }, [active, target]);

  if (!active || !target) return null;
  return createPortal(<div className={styles.portal} data-news-portal="true"><NewsView /></div>, target);
}
