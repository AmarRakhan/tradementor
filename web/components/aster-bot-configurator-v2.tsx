"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { strategy2ServerStatus } from "@/lib/aster-strategy2-server-status.mjs";
import { ReleaseCenter } from "@/components/release-center";
import type { AsterConfiguratorProps } from "@/components/aster-bot-configurator-gate";
import styles from "./aster-bot-configurator-v2.module.css";

const VISUAL_REFERENCE = "file_000000003e34820a9d0c8dc22b84ac47";
const TIMEFRAMES = ["1m","5m","15m","1h","4h","1d"] as const;
type Timeframe = typeof TIMEFRAMES[number];
type TpMode = "PER_TRADE" | "PORTFOLIO" | "OFF";
type StopLossMode = "USD" | "PERCENT";

type Draft = {
  name:string; universe:string; longSlots:string; shortSlots:string; minLeverage:string; maxLeverage:string;
  bollingerEnabled:boolean; directionalEnabled:boolean; longTf:Timeframe; shortTf:Timeframe;
  exposureRefill:boolean; refillLongTf:Timeframe; refillShortTf:Timeframe; refillTrigger:string; refillRelease:string;
  fixedPositionSize:boolean; entryMarginLong:string; entryMarginShort:string; entryNotionalLong:string; entryNotionalShort:string;
  longDcaDistance:string; shortDcaDistance:string; longDcaAmount:string; shortDcaAmount:string; maxDcaLong:string; maxDcaShort:string;
  longTp:string; shortTp:string; tpMode:TpMode; shortRequiresLong:boolean;
  stopLossEnabled:boolean; stopLossMode:StopLossMode; stopLossLong:string; stopLossShort:string;
  manualEnabled:boolean;
};

const numberText=(value:unknown,fallback:number)=>String(Number.isFinite(Number(value))?Number(value):fallback);
const percentText=(value:unknown,fallback:number)=>String((Number.isFinite(Number(value))?Number(value):fallback)*100);
const num=(value:string)=>Number(String(value).replace(",","."))||0;
const clamp=(value:number,min:number,max:number)=>Math.max(min,Math.min(max,value));
const asRecord=(value:unknown):Record<string,unknown>=>value&&typeof value==="object"?value as Record<string,unknown>:{};
const tf=(value:unknown,fallback:Timeframe="15m"):Timeframe=>TIMEFRAMES.includes(String(value) as Timeframe)?String(value) as Timeframe:fallback;

function draftFrom(settings:Record<string,unknown>):Draft{
  const legacyEntry=Number(settings.entryMarginUsd??5);
  const legacyDca=Number(settings.dcaDistance??.003);
  const legacyDcaAmount=Number(settings.dcaMarginUsd??2);
  const legacyMax=Number(settings.maxDca??3);
  const legacyTp=Number(settings.takeProfit??.015);
  return {
    name:String(settings.name||"Aster Multi DCA"),
    universe:numberText(settings.universeTopN,30),
    longSlots:numberText(settings.longSlots,20),
    shortSlots:numberText(settings.shortSlots,10),
    minLeverage:numberText(settings.minimumLeverage,50),
    maxLeverage:settings.maximumLeverage===null||settings.maximumLeverage===undefined?"":numberText(settings.maximumLeverage,50),
    bollingerEnabled:settings.bollingerEntryFilter15mEnabled===true,
    directionalEnabled:settings.directionalBollingerEnabled===true,
    longTf:tf(settings.bollingerLongTimeframe??settings.bollingerEntryFilterTimeframe,"15m"),
    shortTf:tf(settings.bollingerShortTimeframe??settings.bollingerEntryFilterTimeframe,"15m"),
    exposureRefill:settings.exposureRefillEnabled===true,
    refillLongTf:tf(settings.exposureRefillLongTimeframe,"1m"),
    refillShortTf:tf(settings.exposureRefillShortTimeframe,"1m"),
    refillTrigger:numberText(settings.exposureRefillTriggerPercent,20),
    refillRelease:numberText(settings.exposureRefillReleasePercent,8),
    fixedPositionSize:String(settings.entrySizingMode||"margin").toLowerCase()==="notional",
    entryMarginLong:numberText(settings.entryMarginLongUsd??settings.entryMarginLong,legacyEntry),
    entryMarginShort:numberText(settings.entryMarginShortUsd??settings.entryMarginShort,legacyEntry),
    entryNotionalLong:settings.entryNotionalLongUsd===undefined?"":numberText(settings.entryNotionalLongUsd,0),
    entryNotionalShort:settings.entryNotionalShortUsd===undefined?"":numberText(settings.entryNotionalShortUsd,0),
    longDcaDistance:percentText(settings.longDcaDistance??legacyDca,legacyDca),
    shortDcaDistance:percentText(settings.shortDcaDistance??legacyDca,legacyDca),
    longDcaAmount:numberText(settings.longDcaMarginUsd??settings.longDcaAmount,legacyDcaAmount),
    shortDcaAmount:numberText(settings.shortDcaMarginUsd??settings.shortDcaAmount,legacyDcaAmount),
    maxDcaLong:numberText(settings.maxDcaLong??settings.longMaxDca,legacyMax),
    maxDcaShort:numberText(settings.maxDcaShort??settings.shortMaxDca,legacyMax),
    longTp:percentText(settings.longTakeProfitValue??settings.takeProfitLong??legacyTp,legacyTp),
    shortTp:percentText(settings.shortTakeProfitValue??settings.takeProfitShort??legacyTp,legacyTp),
    tpMode:String(settings.takeProfitMode||"PER_TRADE").toUpperCase() as TpMode,
    shortRequiresLong:settings.shortRequiresLongEnabled===true,
    stopLossEnabled:settings.stopLossEnabled===true,
    stopLossMode:String(settings.stopLossMode||"PERCENT").toUpperCase()==="USD"?"USD":"PERCENT",
    stopLossLong:numberText(settings.stopLossLong,5),
    stopLossShort:numberText(settings.stopLossShort,5),
    manualEnabled:settings.manualSymbolSelectionEnabled===true,
  };
}

function Field({label,value,onChange,suffix,disabled=false}:{label:string;value:string;onChange:(value:string)=>void;suffix?:string;disabled?:boolean}){
  return <label className={styles.field}><span>{label}</span><div className={styles.inputWrap}><input disabled={disabled} inputMode="decimal" value={value} onChange={(event)=>onChange(event.target.value.replace(",","."))}/>{suffix&&<b>{suffix}</b>}</div></label>;
}

function Switch({label,detail,checked,onChange,disabled=false}:{label:string;detail:string;checked:boolean;onChange:(value:boolean)=>void;disabled?:boolean}){
  return <label className={styles.switchRow}><span><b>{label}</b><small>{detail}</small></span><button type="button" disabled={disabled} aria-pressed={checked} className={checked?styles.switchOn:styles.switchOff} onClick={()=>onChange(!checked)}><i/>{checked?"Aan":"Uit"}</button></label>;
}

function TimeframePicker({value,onChange,disabled=false}:{value:Timeframe;onChange:(value:Timeframe)=>void;disabled?:boolean}){
  return <div className={styles.timeframes}>{TIMEFRAMES.map(item=><button key={item} type="button" disabled={disabled} className={item===value?styles.active:""} onClick={()=>onChange(item)}>{item}</button>)}</div>;
}

function Step({id,index,title,subtitle,children}:{id:string;index:number;title:string;subtitle:string;children:React.ReactNode}){
  return <section id={id} className={styles.step}><header><span className={styles.stepNumber}>{index}</span><div><h3>{title}</h3><p>{subtitle}</p></div></header>{children}</section>;
}

export function AsterBotConfiguratorV2({snapshot,serverConfirmed,onConfirmed,onChanged}:AsterConfiguratorProps){
  const [confirmedState,setConfirmedState]=useState<Record<string,unknown>|null>(null);
  const snapshotState=asRecord(snapshot?.strategy2);
  const status=strategy2ServerStatus(snapshotState,confirmedState,serverConfirmed);
  const state=asRecord(status.state);
  const persisted=asRecord(state.settings);
  const [draft,setDraft]=useState<Draft>(()=>draftFrom(persisted));
  const [dirty,setDirty]=useState(false);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const [activeStep,setActiveStep]=useState(1);
  const hydratedKey=useRef("");

  useEffect(()=>{
    const key=String(persisted.version??state.configVersion??"");
    if(dirty||!key||hydratedKey.current===key)return;
    hydratedKey.current=key;
    setDraft(draftFrom(persisted));
  },[persisted,state.configVersion,dirty]);

  useEffect(()=>{
    const ids=["market","positions","entry","size","dca","profit","protection","review"];
    const observer=new IntersectionObserver((entries)=>{
      const visible=entries.filter(entry=>entry.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];
      if(!visible)return;
      const idx=ids.indexOf(visible.target.id);
      if(idx>=0)setActiveStep(idx+1);
    },{rootMargin:"-18% 0px -64% 0px",threshold:[.1,.4,.7]});
    ids.forEach(id=>{const node=document.getElementById(id);if(node)observer.observe(node)});
    return()=>observer.disconnect();
  },[]);

  const change=(patch:Partial<Draft>)=>{setDraft(current=>({...current,...patch}));setDirty(true);setMessage("")};
  const total=Math.max(0,Math.round(num(draft.longSlots))+Math.round(num(draft.shortSlots)));
  const snapshotAccount=asRecord(snapshot?.account);
  const available=Number(snapshot?.availableBalance??snapshotAccount.availableBalance??snapshotAccount.availableMargin??0)||0;
  const equity=Number(snapshot?.equity??snapshot?.portfolioValue??snapshotAccount.totalMarginBalance??snapshotAccount.totalWalletBalance??0)||0;
  const positions=Array.isArray(snapshot?.positions)?snapshot?.positions as Array<Record<string,unknown>>:[];
  const exposure=useMemo(()=>positions.reduce((acc,row)=>{
    const side=String(row.side??row.positionSide??"").toUpperCase();
    const notional=Math.abs(Number(row.notionalUsd??row.positionValue??0)||0);
    if(side==="LONG")acc.long+=notional;
    if(side==="SHORT")acc.short+=notional;
    return acc;
  },{long:0,short:0}),[positions]);
  const netExposure=exposure.long-exposure.short;
  const grossExposure=exposure.long+exposure.short;
  const imbalance=grossExposure>0?Math.abs(netExposure)/grossExposure*100:0;
  const refillSide=netExposure<0?"LONG":netExposure>0?"SHORT":"—";

  const startMargin=useMemo(()=>{
    const lev=Math.max(1,num(draft.minLeverage));
    const longStart=draft.fixedPositionSize?num(draft.entryNotionalLong)/lev:num(draft.entryMarginLong);
    const shortStart=draft.fixedPositionSize?num(draft.entryNotionalShort)/lev:num(draft.entryMarginShort);
    return Math.max(0,longStart)*Math.max(0,num(draft.longSlots))+Math.max(0,shortStart)*Math.max(0,num(draft.shortSlots));
  },[draft]);
  const dcaCapacity=Math.max(0,num(draft.longSlots))*Math.max(0,num(draft.maxDcaLong))*Math.max(0,num(draft.longDcaAmount))
    +Math.max(0,num(draft.shortSlots))*Math.max(0,num(draft.maxDcaShort))*Math.max(0,num(draft.shortDcaAmount));
  const theoretical=startMargin+dcaCapacity;
  const reserve=available-theoretical;

  function outgoing(){
    const trigger=num(draft.refillTrigger), release=num(draft.refillRelease);
    if(num(draft.universe)<1||num(draft.universe)>800)throw new Error("Top-N moet tussen 1 en 800 liggen.");
    if(total<1)throw new Error("Configureer minimaal één positie.");
    if(num(draft.minLeverage)<1||num(draft.minLeverage)>300)throw new Error("Minimum leverage moet tussen 1x en 300x liggen.");
    if(draft.maxLeverage&&num(draft.maxLeverage)<num(draft.minLeverage))throw new Error("Maximum leverage moet gelijk aan of hoger zijn dan minimum leverage.");
    if(num(draft.longDcaDistance)<=0||num(draft.shortDcaDistance)<=0)throw new Error("DCA-afstand moet groter dan 0% zijn.");
    if(draft.tpMode==="PER_TRADE"&&(num(draft.longTp)<=0||num(draft.shortTp)<=0))throw new Error("Take Profit moet groter dan 0% zijn.");
    if(draft.exposureRefill&&(!(trigger>0&&trigger<=100)||!(release>=0&&release<trigger)))throw new Error("Exposure refill: stopdrempel moet lager zijn dan startdrempel.");
    return {
      ...persisted,
      engine:"multi_bb_v1",strategyKind:"multi_bb_v1",name:draft.name,
      universeTopN:Math.round(num(draft.universe)),
      maximumPositions:total,longSlots:Math.round(num(draft.longSlots)),shortSlots:Math.round(num(draft.shortSlots)),
      minimumLeverage:Math.round(num(draft.minLeverage)),
      maximumLeverage:draft.maxLeverage.trim()?Math.round(num(draft.maxLeverage)):null,
      shortRequiresLongEnabled:draft.shortRequiresLong,
      bollingerEntryFilter15mEnabled:draft.bollingerEnabled,
      directionalBollingerEnabled:draft.directionalEnabled,
      bollingerLongTimeframe:draft.longTf,bollingerShortTimeframe:draft.shortTf,
      exposureRefillEnabled:draft.exposureRefill,
      exposureRefillLongTimeframe:draft.refillLongTf,exposureRefillShortTimeframe:draft.refillShortTf,
      exposureRefillTriggerPercent:trigger,exposureRefillReleasePercent:release,
      entrySizingMode:draft.fixedPositionSize?"notional":"margin",
      entryMarginLongUsd:num(draft.entryMarginLong),entryMarginShortUsd:num(draft.entryMarginShort),
      ...(draft.fixedPositionSize?{entryNotionalLongUsd:num(draft.entryNotionalLong),entryNotionalShortUsd:num(draft.entryNotionalShort)}:{}),
      longDcaDistance:num(draft.longDcaDistance)/100,shortDcaDistance:num(draft.shortDcaDistance)/100,
      longDcaMarginUsd:num(draft.longDcaAmount),shortDcaMarginUsd:num(draft.shortDcaAmount),
      maxDcaLong:Math.round(num(draft.maxDcaLong)),maxDcaShort:Math.round(num(draft.maxDcaShort)),
      longTakeProfitValue:num(draft.longTp)/100,shortTakeProfitValue:num(draft.shortTp)/100,
      takeProfitMode:draft.tpMode,
      stopLossEnabled:draft.stopLossEnabled,stopLossMode:draft.stopLossMode,
      stopLossLong:num(draft.stopLossLong),stopLossShort:num(draft.stopLossShort),
      manualSymbolSelectionEnabled:draft.manualEnabled,
    };
  }

  async function save(startAfter=false){
    if(busy)return;
    setBusy(true);setMessage("");
    try{
      const settings=outgoing();
      const saved=await authenticatedRequest("/api/exchanges/aster/strategy2/settings",{method:"PUT",body:JSON.stringify({settings})});
      const confirmed=asRecord(saved.strategy2);
      if(Object.keys(confirmed).length){setConfirmedState(confirmed);onConfirmed(confirmed)}
      setDirty(false);
      setMessage("BETA-instellingen server-side opgeslagen. Stable gebruikers blijven op de bestaande logica.");
      if(startAfter){
        const started=await authenticatedRequest("/api/exchanges/aster/strategy2/start",{method:"POST",body:JSON.stringify({confirm:true,settings})});
        const next=asRecord(started.strategy2);
        if(Object.keys(next).length){setConfirmedState(next);onConfirmed(next)}
        setMessage("BETA-configuratie opgeslagen en botstart server-side verwerkt.");
      }
      await Promise.resolve(onChanged());
    }catch(error){setMessage(error instanceof Error?error.message:"Opslaan mislukt.");}
    finally{setBusy(false)}
  }

  async function stop(){
    if(busy)return;
    setBusy(true);setMessage("");
    try{
      const result=await authenticatedRequest("/api/exchanges/aster/strategy2/stop",{method:"POST",body:JSON.stringify({confirm:true})});
      const confirmed=asRecord(result.strategy2);
      if(Object.keys(confirmed).length){setConfirmedState(confirmed);onConfirmed(confirmed)}
      setMessage("Bot-stop server-side verwerkt.");
      await Promise.resolve(onChanged());
    }catch(error){setMessage(error instanceof Error?error.message:"Stoppen mislukt.");}
    finally{setBusy(false)}
  }

  const enabled=status.enabled===true;
  const jump=(index:number,id:string)=>{setActiveStep(index);document.getElementById(id)?.scrollIntoView({behavior:"smooth",block:"start"})};

  return <article id="bot-configurator-v2" className={styles.shell} data-reference={VISUAL_REFERENCE}>
    <header className={styles.hero}>
      <div><span>ASTER BOT · BOTCONFIGURATOR V2</span><h2>Bot instellen</h2><p>Van marktselectie tot controle, in één logische flow.</p></div>
      <div className={styles.beta}><b>BETA</b><small>alleen zichtbaar voor jou</small></div>
    </header>

    <nav className={styles.stepNav} aria-label="Configuratiestappen">
      {[
        [1,"Markt","market"],[2,"Posities","positions"],[3,"Instap","entry"],[4,"Grootte","size"],
        [5,"DCA","dca"],[6,"Winst","profit"],[7,"Bescherming","protection"],[8,"Controle","review"],
      ].map(([index,label,id])=><button key={String(id)} type="button" className={activeStep===index?styles.navActive:""} onClick={()=>jump(Number(index),String(id))}><b>{index}</b><span>{label}</span></button>)}
    </nav>

    <Step id="market" index={1} title="Waar mag de bot handelen?" subtitle="Kies de markt en het universum dat gescand mag worden.">
      <div className={styles.grid2}>
        <Field label="Top-N volume" value={draft.universe} onChange={value=>change({universe:value})}/>
        <Field label="Minimum leverage" value={draft.minLeverage} onChange={value=>change({minLeverage:value})} suffix="×"/>
        <Field label="Maximum leverage" value={draft.maxLeverage} onChange={value=>change({maxLeverage:value})} suffix="×"/>
        <div className={styles.readonlyCard}><span>Markt</span><b>ASTER USDT PERPS</b><small>Cross · actuele exchange-universe</small></div>
      </div>
      <Switch label="Zelf munten kiezen" detail={draft.manualEnabled?"Bestaande handmatige selectie blijft behouden.":"Automatisch: Top-N bepaalt de kandidaten."} checked={draft.manualEnabled} onChange={(value)=>change({manualEnabled:value})}/>
      {draft.manualEnabled&&<p className={styles.note}>De bestaande handmatige muntselectie blijft behouden. V2 verandert geen geselecteerde symbolen zolang je ze niet expliciet in de bestaande selectie-editor wijzigt.</p>}
    </Step>

    <Step id="positions" index={2} title="Hoe wil je je portfolio verdelen?" subtitle="LONG en SHORT blijven onafhankelijk; totaal rekent automatisch mee.">
      <div className={styles.slotVisual}>
        <div><span>LONG</span><b>{Math.round(num(draft.longSlots))}</b><i><u style={{width:String(total?clamp(num(draft.longSlots)/total*100,0,100):0)+"%"}}/></i></div>
        <div><span>SHORT</span><b>{Math.round(num(draft.shortSlots))}</b><i><u style={{width:String(total?clamp(num(draft.shortSlots)/total*100,0,100):0)+"%"}}/></i></div>
        <strong>{total}<small>TOTAAL</small></strong>
      </div>
      <div className={styles.grid2}>
        <Field label="LONG slots" value={draft.longSlots} onChange={value=>change({longSlots:value})}/>
        <Field label="SHORT slots" value={draft.shortSlots} onChange={value=>change({shortSlots:value})}/>
      </div>
      <Switch label="SHORT alleen met LONG" detail="LONG mag zelfstandig openen; een nieuwe SHORT vereist een bestaande LONG op dezelfde pair." checked={draft.shortRequiresLong} onChange={value=>change({shortRequiresLong:value})}/>
    </Step>

    <Step id="entry" index={3} title="Wanneer mag een nieuwe positie openen?" subtitle="15m blijft de normale entry; exposure-repair kan tijdelijk sneller scannen.">
      <Switch label="Bollinger instapfilter" detail="Alleen nieuwe primary entries; DCA en TP worden niet aangepast." checked={draft.bollingerEnabled} onChange={value=>change({bollingerEnabled:value})}/>
      <Switch label="LONG en SHORT apart" detail="Gebruik per richting een eigen normale Bollinger-timeframe." checked={draft.directionalEnabled} onChange={value=>change({directionalEnabled:value})} disabled={!draft.bollingerEnabled}/>
      <div className={styles.sidePair}>
        <div className={styles.longCard}><header><span>LONG</span><b>Normale instap</b></header><TimeframePicker value={draft.longTf} onChange={value=>change({longTf:value})} disabled={!draft.bollingerEnabled}/></div>
        <div className={styles.shortCard}><header><span>SHORT</span><b>Normale instap</b></header><TimeframePicker value={draft.shortTf} onChange={value=>change({shortTf:value})} disabled={!draft.bollingerEnabled}/></div>
      </div>
      <Switch label="Automatische exposure-refill" detail="Alleen de onderwogen kant mag tijdelijk naar een sneller timeframe." checked={draft.exposureRefill} onChange={value=>change({exposureRefill:value})} disabled={!draft.bollingerEnabled}/>
      {draft.exposureRefill&&<div className={styles.refillPanel}>
        <div className={styles.sidePair}>
          <div className={styles.longCard}><header><span>LONG</span><b>Snelle refill</b></header><TimeframePicker value={draft.refillLongTf} onChange={value=>change({refillLongTf:value})}/></div>
          <div className={styles.shortCard}><header><span>SHORT</span><b>Snelle refill</b></header><TimeframePicker value={draft.refillShortTf} onChange={value=>change({refillShortTf:value})}/></div>
        </div>
        <div className={styles.grid2}>
          <Field label="Start snelle refill" value={draft.refillTrigger} onChange={value=>change({refillTrigger:value})} suffix="%"/>
          <Field label="Terug naar normaal" value={draft.refillRelease} onChange={value=>change({refillRelease:value})} suffix="%"/>
        </div>
        <p className={styles.note}>Exposure-refill opent alleen toegestane lege seats. Het veroorzaakt geen DCA, verandert geen 10%/25%-DCA-regel en opent nooit boven de slotlimieten.</p>
      </div>}
    </Step>

    <Step id="size" index={4} title="Hoe groot start iedere positie?" subtitle="LONG en SHORT kunnen een eigen startgrootte houden.">
      <Switch label="Vaste positieomvang" detail="Aan = positie-notional; uit = instapmargin." checked={draft.fixedPositionSize} onChange={value=>change({fixedPositionSize:value})}/>
      <div className={styles.sidePair}>
        <div className={styles.longCard}><header><span>LONG</span><b>Start</b></header><Field label="Instapmargin" value={draft.entryMarginLong} onChange={value=>change({entryMarginLong:value})} suffix="USDT"/>{draft.fixedPositionSize&&<Field label="Vaste positie" value={draft.entryNotionalLong} onChange={value=>change({entryNotionalLong:value})} suffix="USDT"/>}</div>
        <div className={styles.shortCard}><header><span>SHORT</span><b>Start</b></header><Field label="Instapmargin" value={draft.entryMarginShort} onChange={value=>change({entryMarginShort:value})} suffix="USDT"/>{draft.fixedPositionSize&&<Field label="Vaste positie" value={draft.entryNotionalShort} onChange={value=>change({entryNotionalShort:value})} suffix="USDT"/>}</div>
      </div>
    </Step>

    <Step id="dca" index={5} title="Wat gebeurt er als een positie tegen je ingaat?" subtitle="DCA blijft uitsluitend bestaande posities beheren.">
      <div className={styles.sidePair}>
        <div className={styles.longCard}><header><span>LONG</span><b>DCA</b></header><Field label="DCA-afstand" value={draft.longDcaDistance} onChange={value=>change({longDcaDistance:value})} suffix="%"/><Field label="DCA-bedrag" value={draft.longDcaAmount} onChange={value=>change({longDcaAmount:value})} suffix="USDT"/><Field label="Max DCA" value={draft.maxDcaLong} onChange={value=>change({maxDcaLong:value})}/><small className={styles.explainer}>Bij {num(draft.longDcaDistance).toFixed(2)}% daling komt pas de volgende LONG-DCA in aanmerking.</small></div>
        <div className={styles.shortCard}><header><span>SHORT</span><b>DCA</b></header><Field label="DCA-afstand" value={draft.shortDcaDistance} onChange={value=>change({shortDcaDistance:value})} suffix="%"/><Field label="DCA-bedrag" value={draft.shortDcaAmount} onChange={value=>change({shortDcaAmount:value})} suffix="USDT"/><Field label="Max DCA" value={draft.maxDcaShort} onChange={value=>change({maxDcaShort:value})}/><small className={styles.explainer}>Bij {num(draft.shortDcaDistance).toFixed(2)}% stijging komt pas de volgende SHORT-DCA in aanmerking.</small></div>
      </div>
    </Step>

    <Step id="profit" index={6} title="Wanneer wordt winst genomen?" subtitle="LONG en SHORT sluiten onafhankelijk op hun eigen take-profit.">
      <div className={styles.segmented}>{(["PER_TRADE","PORTFOLIO","OFF"] as TpMode[]).map(mode=><button key={mode} type="button" className={draft.tpMode===mode?styles.active:""} onClick={()=>change({tpMode:mode})}>{mode==="PER_TRADE"?"Per trade":mode==="PORTFOLIO"?"Portfolio":"Uit"}</button>)}</div>
      <div className={styles.grid2}>
        <Field label="Take Profit LONG" value={draft.longTp} onChange={value=>change({longTp:value})} suffix="%"/>
        <Field label="Take Profit SHORT" value={draft.shortTp} onChange={value=>change({shortTp:value})} suffix="%"/>
      </div>
      {draft.tpMode==="PORTFOLIO"&&<p className={styles.note}>Bestaande Portfolio TP-waarden en cycle-basis blijven uit je opgeslagen configuratie behouden. Deze V2-layout verandert de bestaande cycle-state niet.</p>}
    </Step>

    <Step id="protection" index={7} title="Hoe bewaakt de bot je portfolio?" subtitle="Bekijk exposure en beschermingsregels zonder de bestaande state te resetten.">
      <div className={styles.exposureGrid}>
        <div><span>LONG exposure</span><b>{"$"}{exposure.long.toLocaleString("nl-NL",{maximumFractionDigits:0})}</b></div>
        <div><span>SHORT exposure</span><b>{"$"}{exposure.short.toLocaleString("nl-NL",{maximumFractionDigits:0})}</b></div>
        <div><span>Netto exposure</span><b className={netExposure<0?styles.negative:styles.positive}>{netExposure>=0?"+":""}{"$"}{netExposure.toLocaleString("nl-NL",{maximumFractionDigits:0})}</b></div>
        <div><span>Afwijking</span><b>{imbalance.toFixed(1)}%</b></div>
      </div>
      {draft.exposureRefill&&<div className={styles.liveRefill}><span>Exposure-repair</span><b>{imbalance>=num(draft.refillTrigger)?refillSide+" snelle refill":imbalance>num(draft.refillRelease)?"Binnen hysterese":"Normale timeframes"}</b><small>Start {draft.refillTrigger}% · terug normaal {draft.refillRelease}%</small></div>}
      <details className={styles.advanced}>
        <summary>Geavanceerde instellingen</summary>
        <Switch label="Stoploss" detail="Bestaande server-side reduce-only stoploss blijft per richting instelbaar." checked={draft.stopLossEnabled} onChange={value=>change({stopLossEnabled:value})}/>
        {draft.stopLossEnabled&&<><div className={styles.segmented}><button type="button" className={draft.stopLossMode==="PERCENT"?styles.active:""} onClick={()=>change({stopLossMode:"PERCENT"})}>%</button><button type="button" className={draft.stopLossMode==="USD"?styles.active:""} onClick={()=>change({stopLossMode:"USD"})}>$</button></div><div className={styles.grid2}><Field label="Stoploss LONG" value={draft.stopLossLong} onChange={value=>change({stopLossLong:value})} suffix={draft.stopLossMode==="USD"?"USDT":"%"}/><Field label="Stoploss SHORT" value={draft.stopLossShort} onChange={value=>change({stopLossShort:value})} suffix={draft.stopLossMode==="USD"?"USDT":"%"}/></div></>}
      </details>
    </Step>

    <Step id="review" index={8} title="Controle & samenvatting" subtitle="Controleer wat de bot werkelijk gaat gebruiken voordat je opslaat.">
      <div className={styles.summary}>
        <div><span>Markt</span><b>Top {Math.round(num(draft.universe))} Aster USDT</b></div>
        <div><span>Posities</span><b>{Math.round(num(draft.longSlots))} LONG · {Math.round(num(draft.shortSlots))} SHORT · {total} totaal</b></div>
        <div><span>Instap</span><b>LONG {draft.longTf} · SHORT {draft.shortTf}</b></div>
        <div><span>Exposure refill</span><b>{draft.exposureRefill?"LONG "+draft.refillLongTf+" · SHORT "+draft.refillShortTf:"Uit"}</b></div>
        <div><span>DCA</span><b>LONG {draft.longDcaDistance}% · SHORT {draft.shortDcaDistance}%</b></div>
        <div><span>Take Profit</span><b>LONG {draft.longTp}% · SHORT {draft.shortTp}%</b></div>
      </div>
      <div className={styles.capacity}>
        <div><span>Geschatte startmargin</span><b>{"$"}{startMargin.toFixed(2)}</b></div>
        <div><span>Max ingestelde DCA-capaciteit</span><b>{"$"}{dcaCapacity.toFixed(2)}</b></div>
        <div><span>Theoretische ingestelde belasting</span><b>{"$"}{theoretical.toFixed(2)}</b></div>
        <div><span>Available nu</span><b>{"$"}{available.toFixed(2)}</b></div>
        <div><span>Portfolio equity</span><b>{"$"}{equity.toFixed(2)}</b></div>
        <div className={reserve<0?styles.warning:""}><span>Reserve na theoretische belasting</span><b>{"$"}{reserve.toFixed(2)}</b></div>
      </div>
      <small className={styles.disclaimer}>Capaciteitsbedragen zijn een configuratie-inschatting; daadwerkelijke margin hangt af van leverage, fills, exchange-regels en bestaande posities.</small>
      <ReleaseCenter compact/>
    </Step>

    {message&&<p className={styles.message}>{message}</p>}
    <footer className={styles.footer}>
      <div><span className={enabled?styles.liveDot:styles.offDot}/><b>{enabled?"Bot actief":"Bot uit"}</b><small>{dirty?" · wijzigingen nog niet opgeslagen":""}</small></div>
      <div className={styles.footerActions}>
        {enabled&&<button type="button" className={styles.stop} disabled={busy} onClick={()=>void stop()}>Bot uitschakelen</button>}
        <button type="button" className={styles.save} disabled={busy} onClick={()=>void save(!enabled)}>{busy?"Bezig…":enabled?"Instellingen opslaan":"Opslaan & bot activeren"}</button>
      </div>
    </footer>
  </article>;
}
