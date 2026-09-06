"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { HomeTransferPage } from "@/components/home-transfer-page";

const VIEW_PARAM = "tmView";
const SESSION_EXIT = "tradementor.home.explicitExit.v1";

function isHome() { return new URL(window.location.href).searchParams.get(VIEW_PARAM) === "home"; }
function urlWithHome(active: boolean) {
  const url = new URL(window.location.href);
  if (active) url.searchParams.set(VIEW_PARAM, "home"); else url.searchParams.delete(VIEW_PARAM);
  return `${url.pathname}${url.search}${url.hash}`;
}
function openHome() {
  if (isHome()) return;
  window.sessionStorage.removeItem(SESSION_EXIT);
  window.history.pushState({ ...window.history.state, home: true }, "", urlWithHome(true));
  window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }));
}
function homeButton() {
  const button = document.createElement("button");
  button.type = "button"; button.className = "nav-button"; button.dataset.destination = "home";
  button.setAttribute("aria-label", "Home"); button.setAttribute("aria-pressed", "false");
  const glyph = document.createElement("span"); glyph.textContent = "⌂";
  const label = document.createElement("small"); label.textContent = "HOME";
  button.append(glyph, label); button.addEventListener("click", openHome); return button;
}
function ensureButton(container: HTMLElement) {
  let button = container.querySelector<HTMLButtonElement>(':scope > .nav-button[data-destination="home"]');
  if (button) return button;
  button = homeButton();
  const first = container.querySelector<HTMLElement>(":scope > .nav-button[data-destination]");
  container.insertBefore(button, first || null);
  return button;
}
function syncNav(active: boolean) {
  document.querySelectorAll<HTMLElement>(".bottom-nav,.rail-nav").forEach((nav) => {
    const home = ensureButton(nav);
    if (active) {
      nav.querySelectorAll<HTMLElement>(":scope > .nav-button[data-destination]").forEach((item) => {
        const selected = item.dataset.destination === "home";
        item.classList.toggle("active", selected); item.setAttribute("aria-pressed", String(selected));
      });
    } else { home.classList.remove("active"); home.setAttribute("aria-pressed", "false"); }
  });
  const label = document.querySelector<HTMLElement>(".mobile-context > span:first-child");
  if (label && active) label.textContent = "HOME";
}

export function HomeNavigationBridge() {
  const [active, setActive] = useState(false);
  const [target, setTarget] = useState<HTMLElement | null>(null);
  useEffect(() => {
    const initialUrl = new URL(window.location.href);
    const explicitView = initialUrl.searchParams.has(VIEW_PARAM);
    const explicitHash = /^#\/(aster|journey|positions|risk|wallet|admin)/.test(initialUrl.hash);
    if (!explicitView && !explicitHash && !window.sessionStorage.getItem(SESSION_EXIT)) {
      window.history.replaceState({ ...window.history.state, home: true }, "", urlWithHome(true));
    }
    const sync = () => { const next = isHome(); setActive(next); setTarget(document.querySelector<HTMLElement>(".content")); syncNav(next); };
    const leave = (event: MouseEvent) => {
      const item = (event.target as HTMLElement | null)?.closest<HTMLElement>(".nav-button[data-destination]");
      if (!item || item.dataset.destination === "home" || !isHome()) return;
      window.sessionStorage.setItem(SESSION_EXIT, "1");
      window.history.replaceState(window.history.state, "", urlWithHome(false));
    };
    sync(); document.addEventListener("click", leave, true); window.addEventListener("hashchange", sync); window.addEventListener("popstate", sync);
    let frame = 0; const observer = new MutationObserver(() => { if (frame) return; frame = requestAnimationFrame(() => { frame=0; sync(); }); }); observer.observe(document.body,{childList:true,subtree:true});
    return () => { observer.disconnect(); if(frame)cancelAnimationFrame(frame); document.removeEventListener("click",leave,true); window.removeEventListener("hashchange",sync); window.removeEventListener("popstate",sync); };
  }, []);
  useEffect(() => { if(!active||!target)return; target.dataset.homeActive="true"; return()=>{delete target.dataset.homeActive;}; }, [active,target]);
  if(!active||!target)return null;
  return createPortal(<div className="tm-home-portal"><HomeTransferPage /></div>,target);
}
