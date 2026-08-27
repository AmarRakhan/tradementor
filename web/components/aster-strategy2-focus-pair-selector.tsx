"use client";
import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

const CACHE_KEY="tradementor:focus-manual-market-universe:v1";
const cleanRows=(value:unknown):Record<string,unknown>[]=>Array.isArray(value)?value.filter((x):x is Record<string,unknown>=>Boolean(x&&typeof x==="object"&&String((x as Record<string,unknown>).symbol||"").trim())):[];
const mergeRows=(...groups:Record<string,unknown>[][])=>{
 const map=new Map<string,Record<string,unknown>>();
 for(const group of groups)for(const row of group){const symbol=String(row.symbol||"").toUpperCase().trim();if(symbol)map.set(symbol,{...(map.get(symbol)||{}),...row,symbol})}
 return [...map.values()].sort((a,b)=>String(a.symbol||"").localeCompare(String(b.symbol||"")));
};

export function AsterStrategy2FocusPairSelector({rows,value,onChange}:{rows:Record<string,unknown>[];value:string;onChange:(symbol:string)=>void}){
 const [remoteRows,setRemoteRows]=useState<Record<string,unknown>[]>([]),[cachedRows,setCachedRows]=useState<Record<string,unknown>[]>([]),[query,setQuery]=useState(""),[loading,setLoading]=useState(true);
 useEffect(()=>{
  let active=true;
  try{const raw=window.localStorage.getItem(CACHE_KEY);if(raw)setCachedRows(cleanRows(JSON.parse(raw)))}catch{}
  const load=async(attempt=0):Promise<void>=>{
   try{
    const result=await authenticatedRequest("/api/exchanges/aster/strategy2/focus/markets") as Record<string,unknown>;
    const next=cleanRows(result.ranking);
    if(!active)return;
    if(next.length){setRemoteRows(next);setCachedRows(next);try{window.localStorage.setItem(CACHE_KEY,JSON.stringify(next))}catch{}}
    setLoading(false);
   }catch{
    if(!active)return;
    if(attempt<2){window.setTimeout(()=>{void load(attempt+1)},500*(attempt+1));return}
    setLoading(false);
   }
  };
  void load();
  return()=>{active=false};
 },[]);
 const selected=value.toUpperCase().trim();
 const source=useMemo(()=>mergeRows(cachedRows,remoteRows,rows),[cachedRows,remoteRows,rows]);
 const filtered=useMemo(()=>{const q=query.toUpperCase().trim();return source.filter(row=>!q||String(row.symbol||"").toUpperCase().includes(q))},[source,query]);
 return <div>
  <label>Zoek pair<input value={query} onChange={e=>setQuery(e.target.value.toUpperCase())} placeholder="Bijv. BTC" autoComplete="off"/></label>
  <div style={{maxHeight:280,overflowY:"auto",display:"grid",gap:6,paddingRight:4}} aria-label="Focus pair selecteren">
   {loading&&source.length===0&&<small>Volledige Aster-pairlijst laden…</small>}
   {!loading&&filtered.length===0&&<small>Geen Aster USDT-perpetual gevonden voor dit filter.</small>}
   {filtered.map((row,index)=>{const symbol=String(row.symbol||"").toUpperCase();const active=symbol===selected;const change=Number(row.change_24h_pct??row.change24hPct??0)*100;const price=Number(row.price||0);return <button key={symbol} type="button" onClick={()=>onChange(symbol)} aria-pressed={active} className="strategy-message" style={{textAlign:"left",cursor:"pointer",outline:active?"2px solid currentColor":"none"}}>
    <b>{index+1}. {symbol}</b><br/><small>{Number.isFinite(change)?`${change>=0?"+":""}${change.toFixed(2)}% 24u`:"—"} · {price>0?`$${price.toLocaleString(undefined,{maximumFractionDigits:8})}`:"prijs —"}{active?" · GESELECTEERD":""}</small>
   </button>})}
  </div>
 </div>
}
