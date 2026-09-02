"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { MarketsPage } from "@/components/markets-page";

function isMarketsRoute() {
  return window.location.hash.replace(/^#\/?/, "").split(/[/?]/, 1)[0] === "markets";
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
  button.addEventListener("click", () => {
    if (isMarketsRoute()) return;
    window.localStorage.setItem("tradementor.activeDestination", "markets");
    window.location.hash = "/markets";
  });
  return button;
}

function syncNavigation(active: boolean) {
  for (const nav of document.querySelectorAll<HTMLElement>(".rail-nav, .bottom-nav")) {
    let button = nav.querySelector<HTMLButtonElement>('[data-destination="markets"]');
    const aster = nav.querySelector<HTMLElement>('[data-destination="aster"]');
    if (!button && aster) {
      button = marketsButton();
      nav.insertBefore(button, aster);
    }
    if (nav.classList.contains("bottom-nav")) {
      const count = nav.querySelectorAll(":scope > .nav-button").length;
      nav.style.setProperty("--mobile-nav-count", String(count));
    }
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
    sync();
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    const observer = new MutationObserver(sync);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
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
