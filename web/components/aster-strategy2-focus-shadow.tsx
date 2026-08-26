"use client";
import {useEffect,useMemo,useState} from "react";
import {authenticatedRequest} from "@/lib/cloud-client";

type Row={symbol?:string;price?:number;change_24h_pct?:number;quote_volume_24h?:number;score?:number;reason?:string;rejection_reason?:string;eligible?:boolean;overextended?:boolean;momentum_pct?:number;bollinger_middle?:number;bollinger_upper?:number;bollinger_lower?:number};
type Report={ordersSent?:number;readOnly?:boolean;capturedAtMs?:number;ranking?:Row[];decision?:Record<string,unknown>;state?:Record<string,unknown>;performance?:Record<string,unknown>;selectionReason?:string};
const n=(x:unknown)=>{const v=Number(x);return Number.isFinite(v)?v:0};
const money=(x:unknown)=>`US$ ${n(x).toFixed(2)}`;
const pct=(x:unknown)=>`${(n(x)*100).toFixed(2)}%`;

export function AsterStrategy2FocusShadow({enabled,manualPair,onSelect}:{enabled:boolean;manualPair?:string;onSelect?:(symbol:string)=>void}){
 const [report,setReport]=useState<Report|null>(null),[error,setError]=useState("");
 useEffect(()=>{if(!enabled)return;let active=true;const load=async()=>{try{const value=await authenticatedRequest("/api/exchanges/aster/strategy2/focus/shadow") as Report;if(active){setReport(value);setError("")}}catch(e){if(active)setError(e instanceof Error?e.message:"Focus Shadow kon niet worden geladen")}};void load();const timer=setInterval(()=>void load(),15000);return()=>{active=false;clearInterval(timer)}},[enabled]);
 const state=report?.state||{};const performance=report?.performance||{};const rows=useMemo(()=>Array.isArray(report?.ranking)?report!.ranking!.slice(0,10):[],[report]);
 if(!enabled)return <small>Schakel Focus Shadow in om de actuele Aster-ranking te zien.</small>;
 if(error)return <p className="strategy-message">{error}</p>;
 if(!report)return <small>Focus Shadow-data laden…</small>;
 const activePair=String(state.active_pair||state.activePair||manualPair||"");
 const current=rows.find(x=>String(x.symbol||"")==activePair);
 const weighted=n(state.weighted_entry??state.weightedEntry),price=n(current?.price),qty=n(state.total_quantity??state.totalQuantity),notional=n(state.total_notional??state.totalNotional),usedMargin=n(state.used_margin??state.usedMargin),budgetUsed=n(state.focus_budget_used??state.focusBudgetUsed);
 const pnl=weighted>0&&price>0?(price-weighted)*qty:0;const pnlPct=weighted>0&&price>0?price/weighted-1:0;
 return <div className="focus-shadow-panel">
   <div className="strategy-message"><b>FOCUS SHADOW · ordersSent = {String(report.ordersSent??0)}</b><br/>Status: {String(state.cycle_status||state.cycleStatus||"Pair selecteren")} · geselecteerd: {activePair||"—"}<br/>Huidige prijs: {price?String(price):"—"} · gemiddelde entry: {weighted?String(weighted):"—"}<br/>Totale positie/notional: {qty?String(qty):"—"} / {money(notional)} · margin: {money(usedMargin)}<br/>DCA: {String(state.dca_count??state.dcaCount??0)} · volgende trigger: {String(state.next_dca_trigger??state.nextDcaTrigger??"—")}<br/>Huidige PNL: {money(pnl)} · {pct(pnlPct)} · hoogste winst: {pct(state.highest_profit_pct??state.highestProfitPct)}<br/>Trailing high: {String(state.highest_price??state.highestPrice??"—")} · floor: {String(state.trailing_floor??state.trailingFloor??"—")}<br/>Focus-budget gebruikt: {money(budgetUsed)} · theoretische equity: {money(performance.portfolioEquity)}<br/>Beslissing: {String(report.decision?.kind||"HOLD")} · {String(report.decision?.reason||report.selectionReason||"")}</div>
   <div className="maker-summary"><b>Coin van het moment · actuele ranking</b><span>Pair | 24h % | huidige prijs</span>{rows.map((row,index)=><button type="button" className="expand-settings" key={row.symbol||index} disabled={row.eligible===false} onClick={()=>row.symbol&&onSelect?.(row.symbol)}><b>{index+1}. {row.symbol}</b> · {(n(row.change_24h_pct)*100).toFixed(2)}% · {n(row.price).toFixed(8)}<br/><small>{row.reason||row.rejection_reason||""}{row.overextended?" · overstrekt":""}</small></button>)}</div>
 </div>;
}
