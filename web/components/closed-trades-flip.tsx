"use client";
import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type Trade = Record<string, unknown>;
type Mode = "all" | "today";
const asNumber = (v:unknown) => v == null || v === "" || !Number.isFinite(Number(v)) ? null : Number(v);
const asDate = (v:unknown) => { const t= typeof v === "number" ? (v < 1e10 ? v*1000 : v) : Date.parse(String(v||"")); return Number.isFinite(t)&&t>0?t:null; };
const dateKey = (t:number) => new Intl.DateTimeFormat("en-CA",{timeZone:"Europe/Amsterdam",year:"numeric",month:"2-digit",day:"2-digit"}).format(t);
const formatted = (n:number|null) => n===null?"—":new Intl.NumberFormat("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Math.abs(n));
const duration = (row:Trade) => {const opened=asDate(row.openedAt),closed=asDate(row.closedAt);if(opened===null||closed===null||closed<opened)return "—";const mins=Math.floor((closed-opened)/60000);return mins>=1440?`${Math.floor(mins/1440)}d ${Math.floor(mins%1440/60)}u`:mins>=60?`${Math.floor(mins/60)}u ${mins%60}m`:`${mins}m`;};
export function ClosedTradesFlip({mode,onClose,todayCount}:{mode:Mode;onClose:()=>void;todayCount:string}) {
 const [rows,setRows]=useState<Trade[]>([]),[busy,setBusy]=useState(true),[error,setError]=useState("");
 const [visible,setVisible]=useState(20),[flipped,setFlipped]=useState(false);
 useEffect(()=>{const controller=new AbortController();setFlipped(true);
 authenticatedRequest("/api/exchanges/aster/closed-trades",{signal:controller.signal,cache:"no-store"}).then(data=>{
   if(controller.signal.aborted)return;
   const source=Array.isArray(data?.closedTrades)?data.closedTrades:[];
   const unique=new Map<string,Trade>();
   for(const trade of source){if(!trade || typeof trade!=="object")continue;const key=String(trade.exchangeTradeId||trade.id||[trade.symbol,trade.side,trade.closedAt,trade.realizedPnlUsd].join("|"));if(!unique.has(key))unique.set(key,trade);}
   setRows([...unique.values()].sort((a,b)=>(asDate(b.closedAt)??0)-(asDate(a.closedAt)??0)));
 }).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Historie tijdelijk niet beschikbaar");}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});
 return ()=>controller.abort();},[]);
 useEffect(()=>{const old=document.body.style.overflow;document.body.style.overflow="hidden";const key=(e:KeyboardEvent)=>{if(e.key==="Escape")onClose()};window.addEventListener("keydown",key);return()=>{document.body.style.overflow=old;window.removeEventListener("keydown",key)}},[onClose]);
 const filtered=useMemo(()=>mode==="all"?rows:rows.filter(row=>{const t=asDate(row.closedAt);return t!==null&&dateKey(t)===dateKey(Date.now())}),[mode,rows]);
 const displayed=filtered.slice(0,visible);
 return <div className="aps-closed-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}>
  <div className="aps-closed-perspective"><section className={`aps-closed-flip ${flipped?"is-flipped":""}`} role="dialog" aria-modal="true" aria-label={mode==="all"?"Gesloten resultaat":"Trades gesloten vandaag"}>
  <div className="aps-closed-face aps-closed-front" aria-hidden="true"><strong>✦ AMAR CRYPTO BOT</strong></div>
  <div className="aps-closed-face aps-closed-back">
   <header><div><small>✦ TRADE HISTORIE</small><h2>{mode==="all"?"Gesloten resultaat":"Trades gesloten vandaag"}</h2><p>Nieuwste eerst · bestaande Aster-gegevens</p></div><button type="button" onClick={onClose} aria-label="Terug">×</button></header>
   {mode==="today"&&todayCount!=="—"?<p className="aps-closed-message">Gesloten volgens dagoverzicht: {todayCount}. Getoonde records zijn uitsluitend de beschikbare historische sluitingen.</p>:null}
   <div className="aps-closed-scroll">
    {busy?<p role="status" className="aps-closed-message">Trades laden…</p>:null}
    {error?<p role="alert" className="aps-closed-message">{error}</p>:null}
    {!busy&&!error&&filtered.length===0?<p className="aps-closed-message">Geen beschikbare gesloten trades.</p>:null}
    {displayed.map((row,index)=>{const profit=asNumber(row.realizedPnlUsd);const margin=asNumber(row.executedMarginUsd)??asNumber(row.marginUsd)??asNumber(row.initialMarginUsd);const t=asDate(row.closedAt);return <article className="aps-closed-row" key={String(row.exchangeTradeId||row.id||index)}>
     <div className="aps-closed-row-head"><strong>{String(row.symbol||"—")}</strong><b className={row.side==="SHORT"?"short":"long"}>{String(row.side||"—")}</b><time>{t===null?"—":new Intl.DateTimeFormat("nl-NL",{timeZone:"Europe/Amsterdam",day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"}).format(t)}</time></div>
     <div className="aps-closed-row-grid"><span><small>Resultaat</small><strong className={profit===null?"":profit>=0?"positive":"negative"}>{profit===null?"—":`${profit>=0?"+":"−"}US$ ${formatted(profit)}`}</strong></span><span><small>Marge</small><strong>{margin===null?"—":`US$ ${formatted(margin)}`}</strong></span><span><small>Duur</small><strong>{duration(row)}</strong></span></div>
    </article>})}
    {visible<filtered.length?<button type="button" className="aps-closed-more" onClick={()=>setVisible(n=>n+20)}>Meer laden</button>:null}
   </div>
   <footer>Alleen beschikbare gegevens · ontbrekende velden worden niet geschat</footer>
  </div></section></div>
 </div>;
}
