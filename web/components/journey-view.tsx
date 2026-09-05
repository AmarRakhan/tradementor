"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import type { ExchangeSnapshots } from "@/lib/use-exchange-data";
import "./journey-view.css";

type Day={date:string;usdChange:number;percentage:number;levels:number;startValue?:number;endValue?:number;closedTrades?:number;realizedPnl?:number;fees?:number;largestWin?:number;largestLoss?:number;highestLevel?:number};
type Daily={reliable?:boolean;todayPercentage?:number;todayUsd?:number;todayLevels?:number;averageDailyPercentage?:number;measuredDays?:number;measurementStartDate?:string;currentEquity?:number;history?:Day[]};
type Growth={baseline?:number;setupRequired?:boolean;targetPortfolio?:number;target?:number;goal?:number;lastBigWinDate?:string;lastBigWinUsd?:number};
const FALLBACK_GOAL=1_000_000;
const usd=(n:number)=>new Intl.NumberFormat("nl-NL",{style:"currency",currency:"USD",minimumFractionDigits:2,maximumFractionDigits:2}).format(n).replace("US$ ","$");
const pct=(n:number)=>`${n>=0?"+":""}${n.toLocaleString("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2})}%`;
const nlDate=(d:string)=>new Date(`${d}T12:00:00`).toLocaleDateString("nl-NL",{day:"numeric",month:"long",year:"numeric"});
const parts=(d:string)=>{const x=new Date(`${d}T12:00:00`);return{day:x.toLocaleDateString("nl-NL",{day:"2-digit"}),month:x.toLocaleDateString("nl-NL",{month:"short"}).replace(".","")}};
const Icon=({name}:{name:"goal"|"earned"|"remaining"|"forecast"})=>{const common={fill:"none",stroke:"currentColor",strokeWidth:1.8,strokeLinecap:"round" as const,strokeLinejoin:"round" as const};return <svg viewBox="0 0 24 24" aria-hidden="true">{name==="goal"?<><circle cx="12" cy="12" r="8" {...common}/><circle cx="12" cy="12" r="3" {...common}/><path d="M14.3 9.7 20 4m0 0v4m0-4h-4" {...common}/></>:name==="earned"?<><path d="M4 17V9m6 8V5m6 12v-7m4 7H2" {...common}/><path d="m14 7 3-3 3 3" {...common}/></>:name==="remaining"?<><circle cx="12" cy="12" r="9" {...common}/><path d="M12 7v5l3 2" {...common}/></>:<><rect x="3" y="5" width="18" height="16" rx="2" {...common}/><path d="M7 3v4m10-4v4M3 10h18m-9 3v5m-2-2h4" {...common}/></>}</svg>};

export function JourneyView({snapshots}:{snapshots:ExchangeSnapshots}){
 const [daily,setDaily]=useState<Daily|null>(null),[growth,setGrowth]=useState<Growth|null>(null),[selected,setSelected]=useState<string|null>(null);
 const stripRef=useRef<HTMLDivElement>(null);
 useEffect(()=>{let alive=true;Promise.all([authenticatedRequest('/api/exchanges/aster/portfolio-growth/daily'),authenticatedRequest('/api/exchanges/aster/portfolio-growth')]).then(([d,g])=>{if(alive){setDaily(d as Daily);setGrowth(g as Growth)}}).catch(()=>{});return()=>{alive=false}},[]);
 const todayIso=new Date().toLocaleDateString("sv-SE",{timeZone:"Europe/Amsterdam"});
 const today:Day={date:todayIso,usdChange:Number(daily?.todayUsd??0),percentage:Number(daily?.todayPercentage??0),levels:Number(daily?.todayLevels??0)};
 const history=useMemo(()=>{const m=new Map<string,Day>();for(const d of daily?.history??[])if(d.date<=todayIso)m.set(d.date,d);m.set(todayIso,{...(m.get(todayIso)||{}),...today});return [...m.values()].sort((a,b)=>a.date.localeCompare(b.date))},[daily?.history,todayIso,today.usdChange,today.percentage,today.levels]);
 useEffect(()=>{if(!selected&&history.length)setSelected(history.at(-1)!.date)},[history,selected]);
 useEffect(()=>{if(!stripRef.current||!history.length)return;requestAnimationFrame(()=>stripRef.current?.scrollTo({left:stripRef.current.scrollWidth,behavior:"auto"}))},[history.length]);
 const equity=Number(daily?.currentEquity??snapshots.aster.data?.equity??0),baseline=Number(growth?.baseline??0),avg=Number(daily?.averageDailyPercentage??0),rate=avg/100;
 const goalCandidate=Number(growth?.targetPortfolio??growth?.target??growth?.goal??FALLBACK_GOAL),goal=Number.isFinite(goalCandidate)&&goalCandidate>0?goalCandidate:FALLBACK_GOAL;
 const totalEarned=baseline>0?equity-baseline:0,remaining=Math.max(0,goal-equity),goalProgress=Math.max(0,Math.min(100,equity/goal*100));
 const forecastDays=useMemo(()=>rate>0&&equity>0&&equity<goal?Math.ceil(Math.log(goal/equity)/Math.log(1+rate)):equity>=goal?0:null,[rate,equity,goal]);
 const forecastDate=forecastDays===null?null:new Date(Date.now()+forecastDays*86400000),forecast=forecastDate?forecastDate.toLocaleDateString("nl-NL",{day:"numeric",month:"long",year:"numeric"}):"—";
 const currentLevel=rate>0&&baseline>0&&equity>=baseline?Math.max(0,Math.floor(Math.log(equity/baseline)/Math.log(1+rate))):0;
 const levelFloor=rate>0&&baseline>0?baseline*Math.pow(1+rate,currentLevel):baseline||equity;
 const nextLevel=rate>0&&levelFloor>0?levelFloor*(1+rate):equity;
 const levelSpan=Math.max(0,nextLevel-levelFloor),levelProgress=levelSpan>0?Math.max(0,Math.min(100,(equity-levelFloor)/levelSpan*100)):0;
 const toNext=Math.max(0,nextLevel-equity),toNextPct=equity>0?toNext/equity*100:0;
 const selectedDay=history.find(d=>d.date===selected)??history.at(-1)??today;
 const bestDay=history.reduce<Day|null>((best,d)=>!best||d.levels>best.levels?d:best,null);
 const latestBigWin=growth?.lastBigWinDate?{date:growth.lastBigWinDate,usdChange:Number(growth.lastBigWinUsd??0)}:([...history].reverse().find(d=>d.usdChange>0)||null);
 const shift=(dir:-1|1)=>stripRef.current?.scrollBy({left:dir*stripRef.current.clientWidth,behavior:"smooth"});
 const ringStyle={"--journey-level":`${levelProgress*3.6}deg`} as React.CSSProperties;
 return <section className="journey2026">
  <section className="j26Hero">
   <div className="j26Sky" aria-hidden="true"/>
   <div className="j26Top"><div className="j26Brand"><b>AMAR</b><span>CRYPTO BOT</span></div><div className="j26Selector"><span className="j26Diamond"/> JOURNEY <span>⌄</span></div></div>
   <div className="j26HeroGrid">
    <div className="j26GoalCopy"><span>Jouw reis naar</span><strong>{usd(goal)}</strong><small>1 level = gemiddelde daggroei</small><b>{goalProgress.toLocaleString("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2})}%</b><i><em style={{width:`${goalProgress}%`}}/></i><small>{usd(equity)} / {usd(goal)}</small></div>
    <div className="j26Orb" style={ringStyle}><div><span>LVL {currentLevel}</span><strong>{usd(equity)}</strong><small>Volgend level</small><b>{usd(nextLevel)}</b><em>Nog {usd(toNext)} nodig</em><em>+{toNextPct.toLocaleString("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2})}% nodig</em><i>{levelProgress.toLocaleString("nl-NL",{minimumFractionDigits:1,maximumFractionDigits:1})}% voltooid</i></div></div>
   </div>
   <div className="j26Stats"><article><Icon name="goal"/><span>DOEL</span><strong>{usd(goal)}</strong></article><article><Icon name="earned"/><span>TOTAAL VERDIEND</span><strong className={totalEarned>=0?"pos":"neg"}>{baseline?usd(totalEarned):"—"}</strong><small>vandaag</small></article><article><Icon name="remaining"/><span>RESTEREND TOT DOEL</span><strong>{usd(remaining)}</strong></article><article><Icon name="forecast"/><span>PROGNOSE</span><strong>{forecast}</strong><small>{forecastDays===null?"—":`Over ${forecastDays} dagen`}</small></article></div>
  </section>
  <section className="j26Calendar"><header><div><b>JOURNEY KALENDER</b><span>JOUW DAGELIJKSE VOORTGANG</span></div><small>Swipe om meer te zien</small></header>
   <div className="j26Carousel"><button type="button" className="j26Arrow" aria-label="Vorige vier dagen" onClick={()=>shift(-1)}>‹</button><div className="j26Strip" ref={stripRef}>{history.map(d=>{const p=parts(d.date),tone=d.percentage>0?"positive":d.percentage<0?"negative":"neutral";return <button type="button" key={d.date} className={`j26Day ${tone} ${selected===d.date?"selected":""}`} onClick={()=>setSelected(d.date)} aria-pressed={selected===d.date}><b>{p.day}</b><span>{p.month}</span><i>{d.percentage>0?"↑":d.percentage<0?"↓":"–"}</i><strong>{d.levels} {d.levels===1?"level":"levels"}</strong><em>{usd(d.usdChange)}</em><small>{pct(d.percentage)}</small><u>{d.percentage>0?"Groei":d.percentage<0?"Daling":"Gelijk"}</u></button>})}</div><button type="button" className="j26Arrow" aria-label="Volgende vier dagen" onClick={()=>shift(1)}>›</button></div>
   <article className={`j26Detail ${selectedDay.percentage<0?"negative":"positive"}`}><header>DETAILS — {nlDate(selectedDay.date).toUpperCase()}</header><div className="j26DetailMain"><div><span>Verdiend</span><strong>{usd(selectedDay.usdChange)}</strong></div><div><span>Groei</span><strong>{pct(selectedDay.percentage)}</strong></div><div><span>Levels</span><strong>{selectedDay.levels}</strong></div></div>{(selectedDay.startValue!==undefined||selectedDay.endValue!==undefined||selectedDay.closedTrades!==undefined||selectedDay.fees!==undefined)&&<div className="j26DetailExtra">{selectedDay.startValue!==undefined&&<span>Begin {usd(selectedDay.startValue)}</span>}{selectedDay.endValue!==undefined&&<span>Einde {usd(selectedDay.endValue)}</span>}{selectedDay.closedTrades!==undefined&&<span>{selectedDay.closedTrades} gesloten trades</span>}{selectedDay.fees!==undefined&&<span>Fees {usd(selectedDay.fees)}</span>}</div>}<p>{selectedDay.percentage>0?`Sterke dag! Je hebt ${selectedDay.levels} ${selectedDay.levels===1?"level":"levels"} behaald en je portfolio is met ${pct(selectedDay.percentage)} gegroeid.`:selectedDay.percentage<0?`Deze dag daalde je portfolio met ${Math.abs(selectedDay.percentage).toLocaleString("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2})}%.`:"Deze dag bleef je portfolio nagenoeg gelijk."}</p></article>
   <div className="j26Achievements"><article><span className="j26Trophy"/> <small>Beste dag</small><strong>{bestDay?`${bestDay.levels} levels`:"—"}</strong></article><article><span className="j26Gem"/> <small>Laatste grote winst</small><strong>{latestBigWin?usd(latestBigWin.usdChange):"—"}</strong>{latestBigWin&&<em>{nlDate(latestBigWin.date)}</em>}</article><article><span className="j26Coins"/> <small>Vandaag verdiend</small><strong className={today.usdChange>=0?"pos":"neg"}>{usd(today.usdChange)}</strong></article></div>
  </section>
 </section>
}
