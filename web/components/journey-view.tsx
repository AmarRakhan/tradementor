"use client";
import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import type { ExchangeSnapshots } from "@/lib/use-exchange-data";

type Day={date:string;usdChange:number;percentage:number;levels:number};
type Daily={reliable?:boolean;todayPercentage?:number;todayUsd?:number;todayLevels?:number;averageDailyPercentage?:number;measuredDays?:number;measurementStartDate?:string;currentEquity?:number;history?:Day[]};
type Growth={baseline?:number;setupRequired?:boolean};
type DisplayDay=Day&{future?:boolean};
const GOAL=1_000_000;
const usd=(n:number)=>new Intl.NumberFormat("nl-NL",{style:"currency",currency:"USD",minimumFractionDigits:2,maximumFractionDigits:2}).format(n).replace("US$ ","$");
const pct=(n:number)=>`${n>=0?"+":""}${n.toLocaleString("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2})}%`;
const dateParts=(d:string)=>{const x=new Date(`${d}T12:00:00`);return {day:x.toLocaleDateString("nl-NL",{day:"2-digit"}),month:x.toLocaleDateString("nl-NL",{month:"short"}).replace('.','')}};
const monthLabel=(days:DisplayDay[])=>{const a=new Date(`${days[0].date}T12:00:00`),b=new Date(`${days[days.length-1].date}T12:00:00`);const am=a.toLocaleDateString("nl-NL",{month:"long"}).toUpperCase(),bm=b.toLocaleDateString("nl-NL",{month:"short"}).replace('.','').toUpperCase();return a.getMonth()===b.getMonth()?`${am} ${a.getFullYear()}`:`${a.toLocaleDateString("nl-NL",{month:"short"}).replace('.','').toUpperCase()} / ${bm} ${b.getFullYear()}`};

export function JourneyView({snapshots}:{snapshots:ExchangeSnapshots}){
 const [daily,setDaily]=useState<Daily|null>(null),[growth,setGrowth]=useState<Growth|null>(null);
 useEffect(()=>{let a=true;Promise.all([authenticatedRequest('/api/exchanges/aster/portfolio-growth/daily'),authenticatedRequest('/api/exchanges/aster/portfolio-growth')]).then(([d,g])=>{if(a){setDaily(d as Daily);setGrowth(g as Growth)}}).catch(()=>{});return()=>{a=false}},[]);
 const equity=Number(daily?.currentEquity ?? snapshots.aster.data?.equity ?? 0),avg=Number(daily?.averageDailyPercentage??0),baseline=Number(growth?.baseline??0);
 const totalEarned=baseline>0?equity-baseline:0,remaining=Math.max(0,GOAL-equity),rate=avg/100;
 const days=useMemo(()=>rate>0&&equity>0&&equity<GOAL?Math.ceil(Math.log(GOAL/equity)/Math.log(1+rate)):equity>=GOAL?0:null,[rate,equity]);
 const targetDate=days===null?null:new Date(Date.now()+days*86400000),progress=Math.max(0,Math.min(100,equity/GOAL*100)),remainingLevels=days;
 const todayIso=new Date().toLocaleDateString("sv-SE",{timeZone:"Europe/Amsterdam"}),today:Day={date:todayIso,usdChange:Number(daily?.todayUsd??0),percentage:Number(daily?.todayPercentage??0),levels:Number(daily?.todayLevels??0)};
 const rows=useMemo(()=>{const map=new Map<string,Day>();for(const d of daily?.history??[])map.set(d.date,d);map.set(today.date,today);const start=daily?.measurementStartDate||today.date;const out:DisplayDay[]=[];const cursor=new Date(`${start}T12:00:00`);for(let i=0;i<18;i++){const iso=cursor.toLocaleDateString("sv-SE");const found=map.get(iso);out.push(found?{...found}:{date:iso,usdChange:0,percentage:0,levels:0,future:iso>today.date});cursor.setDate(cursor.getDate()+1)}return [out.slice(0,6),out.slice(6,12),out.slice(12,18)];},[daily?.history,daily?.measurementStartDate,today.date,today.levels,today.percentage,today.usdChange]);
 const forecast=targetDate?targetDate.toLocaleDateString('nl-NL',{day:'numeric',month:'long',year:'numeric'}):'—';
 return <section className="journey-shell">
  <header className="journey-reference-header"><button type="button" aria-label="Menu">☰</button><div><strong>AMAR</strong><small>CRYPTO BOT</small></div><span>▥　Dashboard　⌄</span></header>
  <section className="journey-top-card">
   <div className="journey-hero"><div className="journey-title"><span>MIJN PAD NAAR</span><h1>$1.000.000</h1><p>1 level = gemiddelde daggroei</p></div><div className="journey-curve" aria-hidden="true"/><aside><strong>{daily?.reliable?`${avg.toLocaleString('nl-NL',{minimumFractionDigits:2,maximumFractionDigits:2})}%`:'—'}</strong><small>Gemiddelde groei per dag</small></aside></div>
   <div className="journey-stats">
    <div data-icon="◎"><span>DOEL</span><strong>$1.000.000</strong></div><div data-icon="▣"><span>HUIDIGE WAARDE</span><strong>{equity?usd(equity):'—'}</strong></div><div data-icon="↗"><span>TOTAAL VERDIEND</span><strong className={totalEarned>=0?'positive':'negative'}>{baseline?usd(totalEarned):'—'}</strong><small>vandaag</small></div>
    <div data-icon="⠿"><span>VANDAAG VERDIEND</span><strong>{daily?.reliable?`${today.levels} levels`:'—'}</strong><small className={today.usdChange>=0?'positive':'negative'}>{daily?.reliable?usd(today.usdChange):'—'}</small></div><div data-icon="◌"><span>RESTEREND TOT DOEL</span><strong>{remainingLevels===null?'—':`${remainingLevels} levels`}</strong><small>{equity?usd(remaining):'—'}</small></div><div data-icon="□"><span>PROGNOSE BIJ HUIDIG TEMPO</span><strong className="positive">{forecast}</strong><small>{days===null?'—':`Over ${days} dagen`}</small></div>
   </div>
  </section>
  <section className="journey-levels"><header><div><h2>JOURNEY LEVELS</h2><p>Elke level staat voor gemiddelde daggroei</p></div><small><i/> Groei behaald　○ Geen groei</small></header>{rows.map((row,i)=><div className="journey-row" key={i}><b className="journey-month">{monthLabel(row)}</b><div className="journey-grid">{row.map((d)=>{const p=dateParts(d.date);return <article key={d.date} className={d.future?'future':d.percentage>0?'won':d.percentage<0?'lost':''}><b>{p.day}</b><em>{p.month}</em><strong>{d.future?'':d.levels}</strong><em>{d.future?'':d.levels===1?'level':'levels'}</em><span>{d.future?'—':usd(d.usdChange)}</span><small>{d.future?'':pct(d.percentage)}</small></article>})}</div></div>)}<div className="journey-pager"><button aria-label="Vorige">‹</button><span><i/>•••••••••</span><button aria-label="Volgende">›</button></div></section>
  <section className="journey-progress"><div><span>VOORTGANG NAAR DOEL</span><strong className="positive">{progress.toLocaleString('nl-NL',{minimumFractionDigits:2,maximumFractionDigits:2})}%</strong><i><b style={{width:`${progress}%`}}/></i><small>{Math.round(equity).toLocaleString('nl-NL')} / 1.000.000</small></div><div><span>NOG TE GAAN</span><strong>{equity?usd(remaining):'—'}</strong><small>{remainingLevels===null?'—':`${remainingLevels} levels`}</small></div><div><span>GESCHATTE DATUM DOEL</span><strong className="positive">{forecast}</strong><small>{days===null?'—':`Over ${days} dagen`}</small></div></section>
 </section>
}
