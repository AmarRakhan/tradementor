"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { FriendsView } from "@/components/friends-view";

const VIEW_PARAM = "tmView";
const NAV_DESTINATIONS = ["home","markets","aster","sniper","news","friends","journey","wallet"] as const;

function isFriendsRoute() {
  return new URL(window.location.href).searchParams.get(VIEW_PARAM) === "friends";
}

function openFriends() {
  if (isFriendsRoute()) return;
  const url = new URL(window.location.href);
  url.searchParams.set(VIEW_PARAM, "friends");
  window.history.pushState({ ...window.history.state, friends: true }, "", `${url.pathname}${url.search}${url.hash}`);
  window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }));
}

function friendsGlyph() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox","0 0 24 24"); svg.setAttribute("fill","none"); svg.setAttribute("stroke","currentColor"); svg.setAttribute("stroke-width","1.8");
  svg.innerHTML='<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>';
  svg.style.width="21px"; svg.style.height="21px";
  return svg;
}

function friendsButton() {
  const button=document.createElement("button");
  button.type="button"; button.className="nav-button"; button.dataset.destination="friends";
  button.setAttribute("aria-label","Friends"); button.setAttribute("aria-pressed","false");
  const glyph=document.createElement("span"); glyph.appendChild(friendsGlyph());
  const label=document.createElement("small"); label.textContent="FRIENDS";
  button.append(glyph,label); button.addEventListener("click",openFriends);
  return button;
}

function ensureFriends(nav:HTMLElement) {
  let button=nav.querySelector<HTMLButtonElement>('[data-destination="friends"]');
  if(button) return button;
  button=friendsButton();
  const journey=nav.querySelector<HTMLElement>('[data-destination="journey"]');
  const wallet=nav.querySelector<HTMLElement>('[data-destination="wallet"]');
  if(journey) nav.insertBefore(button,journey); else if(wallet) nav.insertBefore(button,wallet); else nav.appendChild(button);
  return button;
}

function syncContext(active:boolean) {
  const label=document.querySelector<HTMLElement>(".mobile-context > span:first-child");
  if(!label) return;
  if(active){ if(!label.dataset.friendsPreviousLabel) label.dataset.friendsPreviousLabel=label.textContent||"ASTER"; label.textContent="FRIENDS"; }
  else if(label.dataset.friendsPreviousLabel){ label.textContent=label.dataset.friendsPreviousLabel; delete label.dataset.friendsPreviousLabel; }
}

function syncNavigation(active:boolean) {
  syncContext(active);
  document.querySelectorAll<HTMLElement>(".bottom-nav,.rail-nav").forEach(nav=>{
    const button=ensureFriends(nav);
    for(const item of nav.querySelectorAll<HTMLElement>(":scope > .nav-button[data-destination]")){
      const destination=item.dataset.destination||"";
      const visible=NAV_DESTINATIONS.includes(destination as (typeof NAV_DESTINATIONS)[number]);
      if(nav.classList.contains("bottom-nav")){
        item.hidden=!visible; item.setAttribute("aria-hidden",String(!visible)); item.tabIndex=visible?0:-1;
      }
      if(active){ const selected=destination==="friends"; item.classList.toggle("active",selected); item.setAttribute("aria-pressed",String(selected)); }
    }
    if(!active){button.classList.remove("active");button.setAttribute("aria-pressed","false");}
    if(nav.classList.contains("bottom-nav")){
      const visible=NAV_DESTINATIONS.flatMap(destination=>{const node=nav.querySelector<HTMLElement>(`:scope > .nav-button[data-destination="${destination}"]`);return node?[node]:[];});
      const current=Array.from(nav.children).filter((node):node is HTMLElement=>node instanceof HTMLElement&&!node.hidden&&node.classList.contains("nav-button"));
      if(visible.some((node,index)=>current[index]!==node)) for(const node of visible) nav.appendChild(node);
      nav.style.setProperty("--mobile-nav-count",String(visible.length));
    }
  });
}

export function FriendsNavigationBridge() {
  const [active,setActive]=useState(false);
  const [target,setTarget]=useState<HTMLElement|null>(null);
  useEffect(()=>{
    const sync=()=>{const next=isFriendsRoute();setActive(next);setTarget(document.querySelector<HTMLElement>(".content"));syncNavigation(next);};
    const leave=(event:MouseEvent)=>{const item=(event.target as HTMLElement|null)?.closest<HTMLElement>(".nav-button[data-destination]");if(!item||item.dataset.destination==="friends"||!isFriendsRoute())return;const url=new URL(window.location.href);url.searchParams.delete(VIEW_PARAM);window.history.replaceState(window.history.state,"",`${url.pathname}${url.search}${url.hash}`);};
    sync();document.addEventListener("click",leave,true);window.addEventListener("hashchange",sync);window.addEventListener("popstate",sync);
    let frame=0;const observer=new MutationObserver(()=>{if(frame)return;frame=requestAnimationFrame(()=>{frame=0;sync();});});observer.observe(document.body,{childList:true,subtree:true});
    return()=>{observer.disconnect();if(frame)cancelAnimationFrame(frame);document.removeEventListener("click",leave,true);window.removeEventListener("hashchange",sync);window.removeEventListener("popstate",sync);};
  },[]);
  useEffect(()=>{if(!active||!target)return;target.dataset.friendsActive="true";return()=>{delete target.dataset.friendsActive;};},[active,target]);
  if(!active||!target)return null;
  return createPortal(<div className="friends-portal" data-friends-portal="true"><FriendsView/></div>,target);
}
