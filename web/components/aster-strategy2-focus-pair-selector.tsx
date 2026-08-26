"use client";
import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

export function AsterStrategy2FocusPairSelector({rows,value,onChange}:{rows:Record<string,unknown>[];value:string;onChange:(symbol:string)=>void}){
 const [remoteRows,setRemoteRows]=useState<Record<string,unknown>[]>([]),[query,setQuery]=useState("");
 useEffect(()=>{let active=true;authenticatedRequest("/api/exchanges/aster/strategy2/focus/markets").then(result=>{const value=result as Record<string,unknown>;if(active)setRemoteRows(Array.isArray(value.ranking)?value.ranking.filter((x):x is Record<string,unknown>=>Boolean(x&&typeof x==="object")):[])}).catch(()=>{if(active)setRemoteRows([])});return()=>{active=false}},[]);
 const selected=value.toUpperCase().trim();
 const source=rows.length?rows:remoteRows;
 const eligible=useMemo(()=>source.filter(row=>row.eligible!==false&&String(row.symbol||"").trim()).filter(row=>String(row.symbol||"").toUpperCase().includes(query.toUpperCase().trim())),[source,query]);
 return <div>
  <label>Zoek pair<input value={query} onChange={e=>setQuery(e.target.value.toUpperCase())} placeholder="Bijv. BTC" autoComplete="off"/></label>
  <div style={{maxHeight:280,overflowY:"auto",display:"grid",gap:6,paddingRight:4}} aria-label="Focus pair selecteren">
   {eligible.length===0&&<small>Geen beschikbare Focus-pairs gevonden voor dit filter.</small>}
   {eligible.map((row,index)=>{const symbol=String(row.symbol||"").toUpperCase();const active=symbol===selected;const change=Number(row.change_24h_pct??row.change24hPct??0)*100;const price=Number(row.price||0);return <button key={symbol} type="button" onClick={()=>onChange(symbol)} aria-pressed={active} className="strategy-message" style={{textAlign:"left",cursor:"pointer",outline:active?"2px solid currentColor":"none"}}>
    <b>{index+1}. {symbol}</b><br/><small>{Number.isFinite(change)?`${change>=0?"+":""}${change.toFixed(2)}% 24u`:"—"} · {price>0?`$${price.toLocaleString(undefined,{maximumFractionDigits:8})}`:"prijs —"}{active?" · GESELECTEERD":""}</small>
   </button>})}
  </div>
 </div>
}
