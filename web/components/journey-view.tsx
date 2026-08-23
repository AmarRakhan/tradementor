"use client";
import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import type { ExchangeSnapshots } from "@/lib/use-exchange-data";

type Day={date:string;usdChange:number;percentage:number;levels:number};
type Daily={reliable?:boolean;todayPercentage?:number;todayUsd?:number;todayLevels?:number;averageDailyPercentage?:number;measuredDays?:number;measurementStartDate?:string;currentEquity?:number;history?:Day[]};
type Growth={baseline?:number;setupRequired?:boolean};
const GOAL=1_000_000;
const usd=(n:number)=>new Intl.NumberFormat("nl-NL",{style:"currency",currency:"USD",minimumFractionDigits:2,maximumFractionDigits:2}).format(n);
const pct=(n:number)=>`${n>=0?"+":""}${n.toLocaleString("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2})}%`;
const shortDate=(d:string)=>new Date(`${d}T12:00:00`).toLocaleDateString("nl-NL",{day:"2-digit",month:"short"}).replace('.','');
export function JourneyView({snapshots}:{snapshots:ExchangeSnapshots}){
 const [daily,setDaily]=useState<Daily|null>(null),[growth,setGrowth]=useState<Growth|null>(null);
 useEffect(()=>{let a=true;Promise.all([authenticatedRequest('/api/exchanges/aster/portfolio-growth/daily'),authenticatedRequest('/api/exchanges/aster/portfolio-growth')]).then(([d,g])=>{if(a){setDaily(d as Daily);setGrowth(g as Growth)}}).catch(()=>{});return()=>{a=false}},[]);
 const equity=Number(daily?.currentEquity ?? snapshots.aster.data?.equity ?? 0); const avg=Number(daily?.averageDailyPercentage??0); const baseline=Number(growth?.baseline??0);
 const totalEarned=baseline>0?equity-baseline:0; const remaining=Math.max(0,GOAL-equity); const rate=avg/100;
 const days=useMemo(()=>rate>0&&equity>0&&equity<GOAL?Math.ceil(Math.log(GOAL/equity)/Math.log(1+rate)):equity>=GOAL?0:null,[rate,equity]);
 const targetDate=days===null?null:new Date(Date.now()+days*86400000); const progress=Math.max(0,Math.min(100,equity/GOAL*100));
 const remainingLevels=days; const today:Day={date:new Date().toISOString().slice(0,10),usdChange:Number(daily?.todayUsd??0),percentage:Number(daily?.todayPercentage??0),levels:Number(daily?.todayLevels??0)};
 const history=[...(daily?.history??[]),today].slice(-15);
 return <section className="journey-shell">
  <header className="journey-reference-header"><button type="button" aria-label="Menu">☰</button><div><strong>AMAR</strong><small>CRYPTO BOT</small></div><span>▥　Dashboard　⌄</span></header>
  <section className="journey-hero"><div><span>MIJN PAD NAAR</span><h1>$1.000.000</h1><p>1 level = gemiddelde daggroei</p></div><div className="journey-curve" aria-hidden="true"><i/><i/><i/><i/><i/><b/></div><aside><strong>{daily?.reliable?`${avg.toLocaleString('nl-NL',{minimumFractionDigits:2,maximumFractionDigits:2})}%`:'—'}</strong><small>Gemiddelde groei per dag</small></aside></section>
  <section className="journey-stats"><div><span>DOEL</span><strong>$1.000.000</strong></div><div><span>HUIDIGE WAARDE</span><strong>{equity?usd(equity):'—'}</strong></div><div><span>TOTAAL VERDIEND</span><strong className={totalEarned>=0?'positive':'negative'}>{baseline?usd(totalEarned):'—'}</strong></div><div><span>VANDAAG VERDIEND</span><strong>{daily?.reliable?`${today.levels} levels`:'—'}</strong><small className={today.usdChange>=0?'positive':'negative'}>{daily?.reliable?usd(today.usdChange):'—'}</small></div><div><span>RESTEREND TOT DOEL</span><strong>{remainingLevels===null?'—':`${remainingLevels} levels`}</strong><small>{equity?usd(remaining):'—'}</small></div><div><span>PROGNOSE BIJ HUIDIG TEMPO</span><strong className="positive">{targetDate?targetDate.toLocaleDateString('nl-NL',{day:'numeric',month:'long',year:'numeric'}):'—'}</strong><small>{days===null?'—':`Over ${days} dagen`}</small></div></section>
  <section className="journey-levels"><header><div><h2>JOURNEY LEVELS</h2><p>Elke level staat voor gemiddelde daggroei</p></div><small><i/> Groei behaald　○ Geen groei</small></header><div className="journey-grid">{history.map((d)=><article key={d.date} className={d.percentage>0?'won':d.percentage<0?'lost':''}><b>{shortDate(d.date)}</b><strong>{d.levels} levels</strong><span>{usd(d.usdChange)}</span><small>{pct(d.percentage)}</small></article>)}</div><div className="journey-pager">‹　<span>● · · · · · · ·</span>　›</div></section>
  <section className="journey-progress"><div><span>VOORTGANG NAAR DOEL</span><strong className="positive">{progress.toLocaleString('nl-NL',{minimumFractionDigits:2,maximumFractionDigits:2})}%</strong><i><b style={{width:`${progress}%`}}/></i><small>{Math.round(equity).toLocaleString('nl-NL')} / 1.000.000</small></div><div><span>NOG TE GAAN</span><strong>{equity?usd(remaining):'—'}</strong><small>{remainingLevels===null?'—':`${remainingLevels} levels`}</small></div><div><span>GESCHATTE DATUM DOEL</span><strong className="positive">{targetDate?targetDate.toLocaleDateString('nl-NL',{day:'numeric',month:'long',year:'numeric'}):'—'}</strong><small>{days===null?'—':`Over ${days} dagen`}</small></div></section>
 </section>
}
