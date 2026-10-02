"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CandlestickSeries, ColorType, CrosshairMode, LineSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { authenticatedRequest } from "@/lib/cloud-client";
import { useAuthSession } from "@/components/auth-provider";
import { WEBAPP_BUILD_NUMBER } from "@/lib/app-version";
import { sanitizePortfolioEquityRows } from "@/lib/portfolio-equity-history";
import { PORTFOLIO_KOERS_DEFAULT_TIMEFRAME, PORTFOLIO_KOERS_TIMEFRAMES, aggregatePortfolioEquityHistory, bollinger20x2, cashflowAdjustedPortfolioSeries, markerVisual, mergePortfolioKoersCandles, mergePortfolioKoersMarkers, mergeRealtimeEquitySample, normalizePortfolioKoersPayload, parsePortfolioEquityText, portfolioCashflowShift, portfolioKoersTimelineHealth, portfolioZoneDistancePercent, portfolioZoneForPrice, portfolioZoneProgress, tpTradesForBucketFromActivity } from "@/lib/portfolio-koers-chart.mjs";
import { eventPriority, layoutPortfolioKoersMarkers, layoutPortfolioKoersZoneRegions, selectPortfolioKoersReferenceCandidates } from "@/lib/portfolio-koers-marker-layout.mjs";
import { derivePortfolioZoneLadder, extendPortfolioZoneLadderToPrice, portfolioZoneContextFromLadder } from "@/lib/portfolio-zone-advisor.mjs";
import { buildStrategyStatusCommandCenter, mergeSoldierActivityHistory, soldierOpenEventsFromManagedPositions } from "@/lib/strategy-status-command-center.mjs";

type Candle={time:number;atMs:number;open:number;high:number;low:number;close:number;samples:number;sourceAtMs:number};
type Zone={index:number;label:string;center:number;lower:number;upper:number;touches:number;atr:number;source:string};
type TpTrade={symbol:string;realizedPnlUsd:number;durationMinutes:number|null};
type Marker={time:number;atMs:number;kind?:string;side?:string;label?:string;count?:number;notionalUsd?:number;realizedPnlUsd?:number;amountUsd?:number;cashflowType?:string;originZones?:number[];soldierRoles?:string[];activityTypes?:string[];trades?:TpTrade[];source?:string};
type Payload={timeframe:string;candles:Candle[];markers:Marker[];zones:Zone[];currentZone:number|null;cycleStartEquity:number|null;currentEquity:number|null;snapshotAtMs:number|null;live:boolean;persistent:boolean;externalCashflowsSeparated:boolean;readOnly:boolean;ordersSent:number;source:string};
type ZoneLayout={index:number;label:string;top:number;height:number;tone:"red"|"amber"|"green"|"blue"};
type ZoneBoundaryLayout={price:number;top:number;kind:"regular"|"next-up"|"next-down";targetIndex:number|null};
type StructureLevelLayout={label:"R2"|"R1"|"S1"|"S2";price:number;top:number;side:"resistance"|"support"};
type StructureOverlayLayout={
  levels:StructureLevelLayout[];
  activeZone:{top:number;height:number;label:string}|null;
  roleFlip:{left:number;top:number}|null;
  newHigh:{left:number;top:number}|null;
  breakout:{left:number;top:number}|null;
};
type EventLabel={id:string;left:number;top:number;position:"above"|"below";tone:"long"|"short"|"tp"|"cashflow"|"cluster";title:string;value:string;glyph?:string;multiplier?:string;compact?:boolean;eventCount?:number;anchorLeft?:number;anchorTop?:number;realizedPnlUsd?:number;trades?:TpTrade[];markerTime?:number};
type SoldierActivityEvent={id:string;atMs:number;side:"LONG"|"SHORT";count:number;originZone:number|null;role?:string;source?:string};
type PortfolioViewMode="performance"|"account"|"active";
type ActiveTradesPayload={
  timeframe:string;candles:Candle[];markers:Marker[];
  currentIndexValue:number|null;currentOpenPnl:number|null;currentPnlPercent:number|null;
  longPnl:number|null;shortPnl:number|null;longSharePercent:number|null;shortSharePercent:number|null;
  activeTrades:number;longTrades:number;shortTrades:number;totalNotional:number|null;
  dayHigh:number|null;dayLow:number|null;recoveryPercent:number|null;
  snapshotAtMs:number|null;live:boolean;persistent:boolean;entryExitAdjusted:boolean;readOnly:boolean;ordersSent:number;source:string;
};
type AdvisorSeats={longSlots:number|null;shortSlots:number|null;activeLong:number|null;activeShort:number|null;settings:Record<string,unknown>;zoneSoldiers:Record<string,unknown>;runtimeTruth:Record<string,unknown>;soldierOpenEvents:SoldierActivityEvent[]};

const EMPTY=normalizePortfolioKoersPayload({}) as Payload;
const EMPTY_ACTIVE:ActiveTradesPayload={
  timeframe:"15m",candles:[],markers:[],currentIndexValue:null,currentOpenPnl:null,currentPnlPercent:null,
  longPnl:null,shortPnl:null,longSharePercent:null,shortSharePercent:null,activeTrades:0,longTrades:0,shortTrades:0,totalNotional:null,
  dayHigh:null,dayLow:null,recoveryPercent:null,snapshotAtMs:null,live:false,persistent:true,entryExitAdjusted:true,readOnly:true,ordersSent:0,source:"",
};
const EMPTY_ADVISOR:AdvisorSeats={longSlots:null,shortSlots:null,activeLong:null,activeShort:null,settings:{},zoneSoldiers:{},runtimeTruth:{},soldierOpenEvents:[]};
const ZONE_ADVISOR_REFERENCE="file_00000000d9b081f59f77ecf35043ec32";
const ZONE_SOLDIERS_SCREEN_REFERENCE="file_00000000c2d0821082a1b3c28f6462c1";
const ZONE_SOLDIERS_OPEN_EVENT="tradementor:open-zone-soldiers-command-center";
const PORTFOLIO_STRUCTURE_REFERENCE="file_00000000035481f4bb41632c35857982";
const PORTFOLIO_STRUCTURE_BASELINE_REFERENCE="file_000000002c048243bcc70e9957bb001e";
const PORTFOLIO_KOERS_UI41_REFERENCE="file_00000000e2fc820a9057c8f60c1ec845";
const PORTFOLIO_KOERS_UI41_DETAIL_REFERENCE="file_00000000267082109428370054535e59";
const EMPTY_STRUCTURE_OVERLAY:StructureOverlayLayout={levels:[],activeZone:null,roleFlip:null,newHigh:null,breakout:null};
const PRICE_AXIS_WIDTH=48;
const TIMEFRAME_VIEW:Record<string,{visibleBars:number;barSpacing:number;rightOffset:number}>={
  "1m":{visibleBars:40,barSpacing:6.0,rightOffset:1.4},
  "5m":{visibleBars:38,barSpacing:6.2,rightOffset:1.4},
  "15m":{visibleBars:36,barSpacing:6.6,rightOffset:1.6},
  "1u":{visibleBars:34,barSpacing:6.8,rightOffset:1.6},
  "4u":{visibleBars:30,barSpacing:7.2,rightOffset:1.8},
  "24u":{visibleBars:26,barSpacing:7.8,rightOffset:2.0},
};
const localTime=(seconds:number)=>new Date(seconds*1000).toLocaleString("nl-NL",{timeZone:"Europe/Amsterdam",day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit",hourCycle:"h23"});
const clockTime=(seconds:number)=>new Date(seconds*1000).toLocaleTimeString("nl-NL",{timeZone:"Europe/Amsterdam",hour:"2-digit",minute:"2-digit",hourCycle:"h23"});
const advisorErrorText=(reason:unknown,fallback:string)=>{
  const message=reason instanceof Error?reason.message.trim():"";
  if(!message)return fallback;
  if(/failed to fetch|networkerror|load failed/i.test(message))return "Serververbinding onderbroken · er is niets gewijzigd. Probeer opnieuw.";
  return message;
};
const compactUsd=(value:number|null|undefined)=>{
  if(!Number.isFinite(Number(value))||Number(value)===0)return "";
  const number=Number(value),sign=number<0?"-":"";
  return `${sign}$ ${new Intl.NumberFormat("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Math.abs(number))}`;
};
const signedUsd=(value:number|null|undefined)=>{
  if(!Number.isFinite(Number(value)))return "—";
  const number=Number(value),sign=number<0?"−":"+";
  return sign+"$"+new Intl.NumberFormat("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Math.abs(number));
};
const accountUsd=(value:number|null|undefined)=>Number.isFinite(Number(value))
  ? "$"+new Intl.NumberFormat("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(value))
  : "—";
const durationLabel=(minutes:number|null|undefined)=>Number.isFinite(Number(minutes))
  ? (Number(minutes)>=60?`${Math.floor(Number(minutes)/60)}u ${Math.round(Number(minutes)%60)}m`:`${Math.round(Number(minutes))}m`)
  : "—";
const record=(value:unknown):Record<string,unknown>=>value&&typeof value==="object"?value as Record<string,unknown>:{};
const integerOrNull=(value:unknown)=>{
  if(value===null||value===undefined||value==="")return null;
  const number=Number(value);
  return Number.isFinite(number)?Math.max(0,Math.round(number)):null;
};
const signedIntegerOrNull=(value:unknown)=>{
  if(value===null||value===undefined||value==="")return null;
  const number=Number(value);
  return Number.isFinite(number)?Math.round(number):null;
};
function advisorSeatsFromPayload(payload:unknown):AdvisorSeats {
  const root=record(payload);
  const sources=[root,record(root.data),record(root.snapshot),record(root.account)];
  let strategy2:Record<string,unknown>={};
  for(const source of sources){
    const candidate=record(source.strategy2);
    if(Object.keys(candidate).length){strategy2=candidate;break}
  }
  const settings=record(strategy2.settings);
  const runtimeTruth=record(strategy2.runtimeTruth);
  const managedPositions=record(strategy2.multiBbPositions);
  const primaryReport=record(strategy2.multiBb);
  const report=Object.keys(primaryReport).length?primaryReport:record(strategy2.multiBbReport);
  const zoneSoldiers=Object.keys(record(strategy2.priceZoneSeats)).length
    ? record(strategy2.priceZoneSeats)
    : record(strategy2.zoneSoldiers);
  const reportZoneSoldiers=Object.keys(record(report.priceZoneSeats)).length
    ? record(report.priceZoneSeats)
    : record(report.zoneSoldiers);
  return {
    longSlots:integerOrNull(settings.longSlots),
    shortSlots:integerOrNull(settings.shortSlots),
    activeLong:integerOrNull(report.activeLong),
    activeShort:integerOrNull(report.activeShort),
    settings,
    zoneSoldiers:Object.keys(zoneSoldiers).length?zoneSoldiers:reportZoneSoldiers,
    runtimeTruth,
    soldierOpenEvents:soldierOpenEventsFromManagedPositions(managedPositions) as SoldierActivityEvent[],
  };
}
const signedZone=(value:number|null)=>value===null?"—":value===0?"0":value>0?`+${value}`:`${value}`;
const zoneLevelClass=(value:number)=>value<0?`level-n${Math.abs(value)}`:value>0?`level-p${value}`:"level-0";
const levelUsd=(value:number|null|undefined)=>Number.isFinite(Number(value))
  ? `${new Intl.NumberFormat("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(value))}`
  : "—";
const percent2=(value:number|null|undefined,signed=true)=>{
  if(!Number.isFinite(Number(value)))return "—";
  const number=Number(value);
  const prefix=signed?(number>0?"+":number<0?"−":""):"";
  return `${prefix}${new Intl.NumberFormat("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Math.abs(number))}%`;
};

const numberOrNull=(value:unknown)=>Number.isFinite(Number(value))?Number(value):null;
function normalizeActiveTradesPayload(value:unknown):ActiveTradesPayload{
  const root=record(value);
  const candles=(Array.isArray(root.candles)?root.candles:[]).flatMap((raw)=>{
    const row=record(raw);
    const time=Number(row.time),atMs=Number(row.atMs)||time*1000;
    const open=Number(row.open),high=Number(row.high),low=Number(row.low),close=Number(row.close);
    if(!Number.isFinite(time)||time<=0||![open,high,low,close].every(Number.isFinite)||high<low)return [];
    return [{time,atMs,open,high,low,close,samples:Math.max(1,Number(row.samples)||1),sourceAtMs:Number(row.sourceAtMs)||atMs} as Candle];
  }).sort((a,b)=>a.time-b.time);
  const markerPayload=normalizePortfolioKoersPayload({timeframe:String(root.timeframe||"15m"),markers:Array.isArray(root.markers)?root.markers:[]}) as Payload;
  return {
    timeframe:String(root.timeframe||"15m"),candles,markers:markerPayload.markers,
    currentIndexValue:numberOrNull(root.currentIndexValue),currentOpenPnl:numberOrNull(root.currentOpenPnl),currentPnlPercent:numberOrNull(root.currentPnlPercent),
    longPnl:numberOrNull(root.longPnl),shortPnl:numberOrNull(root.shortPnl),longSharePercent:numberOrNull(root.longSharePercent),shortSharePercent:numberOrNull(root.shortSharePercent),
    activeTrades:Math.max(0,Math.round(Number(root.activeTrades)||0)),longTrades:Math.max(0,Math.round(Number(root.longTrades)||0)),shortTrades:Math.max(0,Math.round(Number(root.shortTrades)||0)),
    totalNotional:numberOrNull(root.totalNotional),dayHigh:numberOrNull(root.dayHigh),dayLow:numberOrNull(root.dayLow),recoveryPercent:numberOrNull(root.recoveryPercent),
    snapshotAtMs:numberOrNull(root.snapshotAtMs),live:root.live===true,persistent:root.persistent!==false,entryExitAdjusted:root.entryExitAdjusted===true,readOnly:root.readOnly!==false,
    ordersSent:Math.max(0,Math.round(Number(root.ordersSent)||0)),source:String(root.source||""),
  };
}

function markerPresentation(row:Marker) {
  const kind=String(row.kind||"").toLowerCase(),side=String(row.side||"").toUpperCase(),count=Math.max(1,Number(row.count)||1);
  if(kind==="cashflow"){
    const amount=Number(row.amountUsd)||0;
    const cashflowType=String(row.cashflowType||"").toUpperCase();
    const title=cashflowType==="DEPOSIT"?"Storting":cashflowType==="WITHDRAWAL"?"Opname":"Cashflow";
    const signed=amount>=0?`+${levelUsd(Math.abs(amount))}`:`−${levelUsd(Math.abs(amount))}`;
    return {tone:"cashflow" as const,glyph:"",multiplier:`${title} ${signed}`,title,value:""};
  }
  if(kind==="entry"){
    const label=side==="SHORT"?"S":"L";
    return {tone:(side==="SHORT"?"short":"long") as "short"|"long",glyph:side==="SHORT"?"down":"up",multiplier:`${label} ×${count}`,title:side==="SHORT"?"SHORT":"LONG",value:""};
  }
  return {tone:"tp" as const,glyph:"money",multiplier:signedUsd(row.realizedPnlUsd),title:"Take Profit",value:""};
}

function DirectionArrow({direction}:{direction:"up"|"down"}) {
  const down=direction==="down";
  return <svg className="portfolio-koers-direction-arrow" viewBox="0 0 18 22" aria-hidden="true">
    <path d={down?"M9 2v16M3.5 12.5 9 18l5.5-5.5":"M9 20V4M3.5 9.5 9 4l5.5 5.5"} fill="none" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>;
}

function MoneyBagIcon() {
  return <svg className="portfolio-koers-moneybag" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M8.2 3.5h7.6l-1.7 3H9.9l-1.7-3Z" fill="currentColor"/>
    <path d="M9.8 6.5h4.4c3.6 2.4 5.5 5.3 5.5 8.4 0 4-2.8 6.1-7.7 6.1s-7.7-2.1-7.7-6.1c0-3.1 1.9-6 5.5-8.4Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/>
    <path d="M14.8 11.2c-.6-.7-1.5-1-2.7-1-1.4 0-2.4.6-2.4 1.5 0 2.4 5.1.9 5.1 3.5 0 1.1-1 1.8-2.6 1.8-1.2 0-2.2-.4-2.9-1.1M12.1 9v9.1" fill="none" stroke="currentColor" strokeWidth="1.45" strokeLinecap="round"/>
  </svg>;
}

function CoinBadge({symbol}:{symbol:string}) {
  const coin=String(symbol||"").toUpperCase().replace(/(?:USDT|USDC|BUSD|USD)$/,"");
  const glyph=coin==="BTC"?"₿":coin==="ETH"?"◆":coin==="XRP"?"✕":coin.slice(0,1)||"•";
  return <span className={`portfolio-koers-coin coin-${coin.toLowerCase()}`} aria-hidden="true">{glyph}</span>;
}

function tpDetailConnectorStyle(label:EventLabel) {
  const startX=264,startY=74;
  const endX=Number(label.left)+43,endY=Number(label.top)+17;
  if(!Number.isFinite(endX)||!Number.isFinite(endY))return undefined;
  const dx=endX-startX,dy=endY-startY,length=Math.hypot(dx,dy);
  if(length<8)return undefined;
  return {left:`${startX}px`,top:`${startY}px`,width:`${length}px`,transform:`rotate(${Math.atan2(dy,dx)}rad)`};
}

function connectorStyle(label:EventLabel) {
  if(!Number.isFinite(label.anchorLeft)||!Number.isFinite(label.anchorTop))return undefined;
  const startX=Number(label.anchorLeft),startY=Number(label.anchorTop);
  const dx=label.left-startX,dy=label.top-startY;
  const length=Math.hypot(dx,dy);
  if(length<5)return undefined;
  return {
    left:`${startX}px`,
    top:`${startY}px`,
    width:`${length}px`,
    transform:`rotate(${Math.atan2(dy,dx)}rad)`,
  };
}

function markerDetail(row:Marker) {
  const kind=String(row.kind||"").toLowerCase(),side=String(row.side||"").toUpperCase(),count=Math.max(1,Number(row.count)||1);
  if(kind==="cashflow")return `${String(row.cashflowType||"Transfer").replaceAll("_"," ")} ${compactUsd(row.amountUsd)}`.trim();
  if(kind==="entry"){
    const zones=Array.isArray(row.originZones)?row.originZones.filter((value)=>Number.isInteger(Number(value))).map((value)=>`Z${signedZone(Number(value))}`):[];
    const roles=Array.isArray(row.soldierRoles)?row.soldierRoles.map((value)=>String(value).toUpperCase()):[];
    const origin=zones.length===1?` · ${zones[0]}`:zones.length>1?` · ${zones.length} zones`:"";
    const role=roles.length===1?` · ${roles[0]==="EXPOSURE_BALANCER"?"exposure-balancer":roles[0]==="ZONE_BASE"?"zone-stoel":roles[0].toLowerCase().replaceAll("_","-")}`:"";
    const types=Array.isArray(row.activityTypes)?row.activityTypes.map((value)=>String(value).toUpperCase()):[];
    const activity=types.length===1&&types[0]==="DCA"?" DCA":types.includes("DCA")&&types.includes("ENTRY")?" ENTRY+DCA":"";
    return `${side==="SHORT"?"SHORT":"LONG"}${activity}${count>1?` ×${count}`:""} ${compactUsd(row.notionalUsd)}${origin}${role}`.trim();
  }
  return `💰${count>1?` ×${count}`:""} ${compactUsd(row.realizedPnlUsd)}`.trim();
}

type StructureNoteKind="roleFlip"|"newHigh"|"breakout";
type StructureRect={left:number;right:number;top:number;bottom:number};

function structureRectsOverlap(a:StructureRect,b:StructureRect,padding=5){
  return !(a.right+padding<=b.left||b.right+padding<=a.left||a.bottom+padding<=b.top||b.bottom+padding<=a.top);
}

function structureNoteRect(kind:StructureNoteKind,left:number,top:number):StructureRect{
  const size=kind==="roleFlip"?{width:148,height:28}:kind==="breakout"?{width:112,height:30}:{width:70,height:22};
  return {left:left-size.width/2,right:left+size.width/2,top:top-size.height/2,bottom:top+size.height/2};
}

function placeStructureNote(
  point:{left:number;top:number}|null,
  kind:StructureNoteKind,
  markerLabels:any[],
  reserved:StructureRect[],
  width:number,
  height:number,
){
  if(!point)return null;
  const offsets=kind==="newHigh"
    ? [[0,0],[-72,-10],[72,-10],[-88,28],[88,28],[0,-44],[0,44]]
    : kind==="breakout"
      ? [[0,0],[0,-34],[-82,0],[82,0],[-64,-30],[64,-30]]
      : [[0,0],[74,-10],[-74,-10],[0,34],[82,26],[-82,26]];
  const markerRects=(Array.isArray(markerLabels)?markerLabels:[])
    .map((row:any)=>row?.rect)
    .filter((rect:any)=>rect&&Number.isFinite(Number(rect.left))&&Number.isFinite(Number(rect.top))) as StructureRect[];
  for(const [dx,dy] of offsets){
    const left=Math.max(46,Math.min(width-70,point.left+dx));
    const top=Math.max(18,Math.min(height-20,point.top+dy));
    const rect=structureNoteRect(kind,left,top);
    if(markerRects.some((other)=>structureRectsOverlap(rect,other,4)))continue;
    if(reserved.some((other)=>structureRectsOverlap(rect,other,4)))continue;
    reserved.push(rect);
    return {left,top};
  }
  const left=Math.max(46,Math.min(width-70,point.left));
  const top=Math.max(18,Math.min(height-20,point.top+(kind==="newHigh"?48:-38)));
  reserved.push(structureNoteRect(kind,left,top));
  return {left,top};
}


function StrategyCommandCenter({vm,advisorMessage}:{vm:any;advisorMessage:string}) {
  const exposureClass=String(vm.netExposureSide||"NEUTRAAL").toLowerCase();
  const priorityClass=String(vm.entryPriority||"GEEN").toLowerCase();
  const exposureAmount=Number.isFinite(Number(vm.netExposureUsd))&&Math.abs(Number(vm.netExposureUsd))>=.005
    ? `${levelUsd(Math.abs(Number(vm.netExposureUsd)))} ${vm.netExposureSide}`
    : String(vm.netExposureSide||"NEUTRAAL");
  return <section
    className={`portfolio-command-center pcc-homecoming cc-${vm.actionMode}`}
    data-reference="file_00000000cf9481f4b495250734661e31"
    data-release-feature="zone_command_center"
    aria-label="Prijszone-stoelen Strategiestatus"
    aria-live="polite"
  >
    <header className="pcc-head">
      <span className="pcc-head-icon" aria-hidden="true">⌖</span>
      <div><small>PRIJSZONE-STOELEN</small><strong>Strategiestatus</strong></div>
      <span className="pcc-command-badge">COMMAND CENTER<em>{vm.strategyEnabled?"BOT ACTIEF · 24/7":"STRATEGY UIT"}</em></span>
    </header>

    <section className="pcc-formation-hero pcc-zone-summary">
      <div className="pcc-active-zone">
        <small>ACTIEVE ZONE</small>
        <strong>{vm.activeZone}</strong>
        <em>Doel {vm.desiredLong}L · {vm.desiredShort}S</em>
      </div>
      <div className={`pcc-exposure ${exposureClass}`}>
        <span aria-hidden="true">⚖</span>
        <div><small>NETTO EXPOSURE</small><strong>{exposureAmount}</strong><em>PRIORITEIT: <b className={priorityClass}>{vm.entryPriority}</b></em></div>
      </div>
    </section>

    <div className="pcc-status-grid pcc-status-grid-v2">
      <article>
        <span className="pcc-status-icon field" aria-hidden="true">♟</span>
        <div><small>PRIJSZONE-POSITIES ACTIEF</small><strong><b className="long">{vm.strategyOwnedLong}L</b> · <b className="short">{vm.strategyOwnedShort}S</b></strong><em>{vm.strategyOwnedTotal} totaal · strategy-owned</em></div>
      </article>
      <article>
        <span className="pcc-status-icon map" aria-hidden="true">◇</span>
        <div><small>OUDE-ZONE POSITIES</small><strong>{vm.oldZonesOpenTotal}</strong><em><b className="long">{vm.oldZonesOpenLong}L</b> · <b className="short">{vm.oldZonesOpenShort}S</b></em></div>
      </article>
      <article className="pcc-next-zones">
        <span className="pcc-status-icon clock" aria-hidden="true">◷</span>
        <div><small>VOLGENDE ZONES</small><strong>↑ {vm.nextZoneUp} · {percent2(vm.nextZoneUpDistancePercent,false)}</strong><em>↓ {vm.nextZoneDown} · {percent2(vm.nextZoneDownDistancePercent,false)}</em></div>
      </article>
      <article>
        <span className="pcc-status-icon trophy" aria-hidden="true">♛</span>
        <div><small>WINST UIT OUDE ZONES</small><strong>{vm.winningHomeToday}</strong><em>vandaag · buiten oorsprongszone gesloten</em></div>
      </article>
    </div>

    <footer className="pcc-homecoming-footer">
      <span className="pcc-info-icon" aria-hidden="true">i</span>
      <div><strong>Oude-zone posities blijven onderdeel van de prijszone-strategie</strong><em>Legacy, manual en Sniper tellen hier niet mee.</em></div>
    </footer>

    <span className="portfolio-koers-cockpit-sr">
      Actieve zone {vm.activeZone}. Strategy-owned {vm.strategyOwnedLong} long en {vm.strategyOwnedShort} short. Oude-zone posities {vm.oldZonesOpenLong} long en {vm.oldZonesOpenShort} short. Netto exposure {exposureAmount}. Prioriteit {vm.entryPriority}. Volgende zones omhoog {vm.nextZoneUp} op {percent2(vm.nextZoneUpDistancePercent,false)} en omlaag {vm.nextZoneDown} op {percent2(vm.nextZoneDownDistancePercent,false)}. {advisorMessage}
    </span>
  </section>;
}

function ZoneSoldiersCommandCenterScreen({vm,advisorMessage,onClose}:{vm:any;advisorMessage:string;onClose:()=>void}) {
  const goToUnderlying=(needle:string)=>{
    onClose();
    window.setTimeout(()=>{
      const nodes=Array.from(document.querySelectorAll<HTMLElement>("button,a,[role=button]"));
      const target=nodes.find((node)=>(node.textContent||"").toUpperCase().includes(needle));
      target?.click();
      target?.scrollIntoView({behavior:"smooth",block:"center"});
    },80);
  };
  return createPortal(
    <section className="zsc-screen" data-reference={ZONE_SOLDIERS_SCREEN_REFERENCE} aria-label="Prijszone-stoelen overzicht">
      <div className="zsc-scroll">
        <header className="zsc-topbar">
          <button type="button" className="zsc-back" onClick={onClose} aria-label="Terug naar Portfolio Snapshot">‹</button>
          <div className="zsc-brand"><strong>Prijszone-stoelen</strong><span>OVERZICHT</span></div>
          <span className="zsc-live"><i/>Live</span>
          <span className="zsc-build">Webapp versie 46 · build {WEBAPP_BUILD_NUMBER}</span>
          <span className="zsc-bell" aria-hidden="true">♢</span>
        </header>
        <section className="zsc-intro">
          <div><strong>Strategie-overzicht · losse pagina</strong><span>Alle prijszone-informatie, posities en stoelstatus in één overzicht.</span></div>
          <div className="zsc-discipline"><b>◒</b><span>DISCIPLINE<br/>DATA<br/><em>LONG TERM WEALTH</em></span></div>
        </section>
        <StrategyCommandCenter vm={vm} advisorMessage={advisorMessage}/>
        <section className="zsc-actions">
          <header><strong>SNELLE ACTIES</strong><span>Direct naar de belangrijkste functies.</span></header>
          <div className="zsc-actions-grid">
            <button type="button" onClick={()=>goToUnderlying("ACTIEVE POSITIES")}><b>☷</b><span><strong>Open posities</strong><small>Bekijk alle actieve prijszone-posities</small></span><em>›</em></button>
            <button type="button" className="gold" onClick={onClose}><b>◇</b><span><strong>Zone mapping</strong><small>Overzicht van alle zones</small></span><em>›</em></button>
            <button type="button" onClick={()=>goToUnderlying("BOTINSTELLINGEN")}><b>⚙</b><span><strong>Instellingen</strong><small>Strategie en risico parameters</small></span><em>›</em></button>
            <button type="button" className="gold" onClick={onClose}><b>↩</b><span><strong>Terug naar snapshot</strong><small>Naar portfolio overzicht</small></span><em>›</em></button>
          </div>
        </section>
        <footer className="zsc-footer"><span>“Systeem. Discipline. Resultaat.”</span><b>AMAR CRYPTO BOT 2026</b></footer>
      </div>
      <nav className="zsc-bottom-nav" aria-label="Hoofdnavigatie">
        {["HOME","MARKETS","ASTER","SNIPER","NIEUWS","FRIENDS","JOURNEY","WALLET"].map((label)=>
          <button type="button" key={label} className={label==="ASTER"?"active":""} onClick={()=>label==="ASTER"?onClose():goToUnderlying(label)}><span>{label==="HOME"?"⌂":label==="ASTER"?"✦":label==="SNIPER"?"⌾":label==="FRIENDS"?"♟":label==="JOURNEY"?"△":label==="WALLET"?"▣":"▥"}</span><b>{label}</b></button>
        )}
      </nav>
    </section>,
    document.body,
  );
}

export function PortfolioKoersChart({
  liveEquityText,
  liveAvailableText,
  liveLongText,
  liveShortText,
  onActiveZoneChange,
}:{
  liveEquityText:string;
  liveAvailableText:string;
  liveLongText:string;
  liveShortText:string;
  onActiveZoneChange?:(zone:number|null)=>void;
}) {
  const { user }=useAuthSession();
  const shellRef=useRef<HTMLElement>(null);
  const canvasRef=useRef<HTMLDivElement>(null);
  const chartRef=useRef<IChartApi|null>(null);
  const candleSeriesRef=useRef<ISeriesApi<any>|null>(null);
  const bbRefs=useRef<{upper:ISeriesApi<any>|null;middle:ISeriesApi<any>|null;lower:ISeriesApi<any>|null}>({upper:null,middle:null,lower:null});
  const candleDataRef=useRef<Candle[]>([]);
  const markerRowsRef=useRef<Marker[]>([]);
  const syncOverlaysRef=useRef<()=>void>(()=>{});
  const advisorZoneLadderRef=useRef<any>(null);
  const activeZoneRef=useRef<number|null>(null);
  const liveEquityTextRef=useRef(liveEquityText);
  const [timeframe,setTimeframe]=useState(PORTFOLIO_KOERS_DEFAULT_TIMEFRAME);
  const [viewMode,setViewMode]=useState<PortfolioViewMode>("account");
  const [payload,setPayload]=useState<Payload>(EMPTY);
  const [activePayload,setActivePayload]=useState<ActiveTradesPayload>(EMPTY_ACTIVE);
  const [activeLoading,setActiveLoading]=useState(false);
  const [activeError,setActiveError]=useState("");
  const [recentMarkers,setRecentMarkers]=useState<Marker[]>([]);
  const [browserCandles,setBrowserCandles]=useState<Candle[]>([]);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(true);
  const [initialChartReady,setInitialChartReady]=useState(false);
  const [zoneLayout,setZoneLayout]=useState<ZoneLayout[]>([]);
  const [zoneBoundaries,setZoneBoundaries]=useState<ZoneBoundaryLayout[]>([]);
  const [structureOverlay,setStructureOverlay]=useState<StructureOverlayLayout>(EMPTY_STRUCTURE_OVERLAY);
  const [eventLabels,setEventLabels]=useState<EventLabel[]>([]);
  const [selectedTpCluster,setSelectedTpCluster]=useState<EventLabel|null>(null);
  const [tpDetailLoading,setTpDetailLoading]=useState(false);
  const [tpDetailError,setTpDetailError]=useState("");
  const [hover,setHover]=useState<{candle:Candle;markers:Marker[]}|null>(null);
  const [liveEquity,setLiveEquity]=useState<number|null>(null);
  const [advisorEnabled,setAdvisorEnabled]=useState(false);
  const [commandCenterAvailable,setCommandCenterAvailable]=useState(false);
  const [activeTradesAvailable,setActiveTradesAvailable]=useState(false);
  const [advisorSeats,setAdvisorSeats]=useState<AdvisorSeats>(EMPTY_ADVISOR);
  const [advisorZones,setAdvisorZones]=useState<Zone[]>([]);
  const [advisorTimeline,setAdvisorTimeline]=useState<any>(null);
  const [advisorMessage,setAdvisorMessage]=useState("");
  const [soldierActivity,setSoldierActivity]=useState<SoldierActivityEvent[]>([]);
  const [zoneSoldiersScreenOpen,setZoneSoldiersScreenOpen]=useState(false);
  const durableMarkers=viewMode==="active"?activePayload.markers:payload.markers;
  const combinedMarkers=useMemo(
    ()=>mergePortfolioKoersMarkers(durableMarkers,recentMarkers) as Marker[],
    [durableMarkers,recentMarkers],
  );
  const cashflowSignature=useMemo(
    ()=>combinedMarkers
      .filter((row)=>String(row.kind||"").toLowerCase()==="cashflow")
      .map((row)=>String(row.time)+":"+String(row.cashflowType||"")+":"+String(Number(row.amountUsd)||0))
      .join("|"),
    [combinedMarkers],
  );
  liveEquityTextRef.current=liveEquityText;
  markerRowsRef.current=combinedMarkers;

  const loadBrowserHistory=useCallback(()=>{
    if(!user?.uid){setBrowserCandles([]);return}
    try{
      const key=`tradementor.portfolioEquity.v2.${encodeURIComponent(user.uid)}`;
      const raw=JSON.parse(window.localStorage.getItem(key)||"[]");
      const rows=sanitizePortfolioEquityRows(Array.isArray(raw)?raw:[]);
      setBrowserCandles(aggregatePortfolioEquityHistory(rows,timeframe,320) as Candle[]);
    }catch{setBrowserCandles([])}
  },[timeframe,user?.uid]);

  useEffect(()=>{loadBrowserHistory()},[loadBrowserHistory,payload.snapshotAtMs]);

  useEffect(()=>{
    if(!commandCenterAvailable||!user?.uid){setSoldierActivity([]);return}
    try{
      const key=`tradementor.zoneSoldierActivity.v1.${encodeURIComponent(user.uid)}`;
      const stored=JSON.parse(window.localStorage.getItem(key)||"[]");
      setSoldierActivity(mergeSoldierActivityHistory(Array.isArray(stored)?stored:[],[],Date.now()) as SoldierActivityEvent[]);
    }catch{setSoldierActivity([])}
  },[commandCenterAvailable,user?.uid]);

  const loadAdvisor=useCallback(async()=>{
    try{
      const release=record(await authenticatedRequest("/api/releases/me",{cache:"no-store"}));
      const features=record(release.features);
      const zoneFeature=record(features.zone_soldiers);
      const commandCenterFeature=record(features.zone_command_center);
      const activeTradesFeature=record(features.active_trades_chart);
      const strategyAccess=zoneFeature.enabled===true;
      const commandCenterAccess=commandCenterFeature.enabled===true;
      setAdvisorEnabled(strategyAccess);
      setCommandCenterAvailable(commandCenterAccess);
      setActiveTradesAvailable(activeTradesFeature.enabled===true);
      if(strategyAccess){
        const account=await authenticatedRequest("/api/exchanges/aster",{cache:"no-store"});
        const nextAdvisor=advisorSeatsFromPayload(account);
        setAdvisorSeats(nextAdvisor);
        if(commandCenterAccess&&user?.uid){
          setSoldierActivity((current)=>{
            const merged=mergeSoldierActivityHistory(current,nextAdvisor.soldierOpenEvents,Date.now()) as SoldierActivityEvent[];
            try{
              const key=`tradementor.zoneSoldierActivity.v1.${encodeURIComponent(user.uid)}`;
              window.localStorage.setItem(key,JSON.stringify(merged));
            }catch{/* activity remains in memory when storage is unavailable */}
            return merged;
          });
        }
      }else{
        setAdvisorSeats(EMPTY_ADVISOR);
      }
    }catch{
      setAdvisorEnabled(false);
      setCommandCenterAvailable(false);
      setActiveTradesAvailable(false);
      setViewMode((current)=>current==="active"?"account":current);
      setZoneSoldiersScreenOpen(false);
      setAdvisorSeats(EMPTY_ADVISOR);
    }
    try{
      const canonical=normalizePortfolioKoersPayload(await authenticatedRequest("/api/exchanges/aster/portfolio-chart?timeframe=15m&limit=320",{cache:"no-store"})) as Payload;
      setAdvisorZones(canonical.zones);
      setAdvisorTimeline(portfolioKoersTimelineHealth(canonical.candles,"15m",Date.now(),14));
      setAdvisorMessage("");
    }catch(reason){
      setAdvisorZones([]);
      setAdvisorTimeline(null);
      setAdvisorMessage(advisorErrorText(reason,"15m-zonebasis tijdelijk niet beschikbaar; Portfolio Koers blijft informatief."));
    }
  },[user?.uid]);

  useEffect(()=>{
    void loadAdvisor();
    const timer=window.setInterval(()=>{if(document.visibilityState==="visible")void loadAdvisor()},45_000);
    return()=>window.clearInterval(timer);
  },[loadAdvisor]);

  const loadRecentEvents=useCallback(async()=>{
    try{
      const response=record(await authenticatedRequest(
        `/api/exchanges/aster/portfolio-chart/events?timeframe=${encodeURIComponent(timeframe)}`,
        {cache:"no-store"},
      ));
      const normalized=normalizePortfolioKoersPayload({timeframe,markers:Array.isArray(response.markers)?response.markers:[]}) as Payload;
      setRecentMarkers(normalized.markers);
    }catch{
      // Keep the last confirmed live markers. The normal 45s chart refresh is
      // still the durable fallback and no trading path depends on this feed.
    }
  },[timeframe]);

  useEffect(()=>{
    setRecentMarkers([]);
    void loadRecentEvents();
    const timer=window.setInterval(()=>{
      if(document.visibilityState==="visible")void loadRecentEvents();
    },5_000);
    const visible=()=>{if(document.visibilityState==="visible")void loadRecentEvents()};
    document.addEventListener("visibilitychange",visible);
    return()=>{window.clearInterval(timer);document.removeEventListener("visibilitychange",visible)};
  },[loadRecentEvents]);

  useEffect(()=>{
    markerRowsRef.current=combinedMarkers;
    syncOverlaysRef.current();
  },[combinedMarkers]);

  useEffect(()=>{
    const open=()=>{if(commandCenterAvailable)setZoneSoldiersScreenOpen(true)};
    window.addEventListener(ZONE_SOLDIERS_OPEN_EVENT,open);
    return()=>window.removeEventListener(ZONE_SOLDIERS_OPEN_EVENT,open);
  },[commandCenterAvailable]);

  useEffect(()=>{
    if(!commandCenterAvailable)setZoneSoldiersScreenOpen(false);
  },[commandCenterAvailable]);

  useEffect(()=>{
    if(!zoneSoldiersScreenOpen)return;
    const previous=document.body.style.overflow;
    document.body.style.overflow="hidden";
    document.documentElement.setAttribute("data-zone-soldiers-screen-open","true");
    const onKey=(event:KeyboardEvent)=>{if(event.key==="Escape")setZoneSoldiersScreenOpen(false)};
    window.addEventListener("keydown",onKey);
    return()=>{document.body.style.overflow=previous;document.documentElement.removeAttribute("data-zone-soldiers-screen-open");window.removeEventListener("keydown",onKey)};
  },[zoneSoldiersScreenOpen]);

  const load=useCallback(async()=>{
    try{
      const response=await authenticatedRequest(`/api/exchanges/aster/portfolio-chart?timeframe=${encodeURIComponent(timeframe)}&limit=320`,{cache:"no-store"});
      const normalized=normalizePortfolioKoersPayload(response) as Payload;
      setPayload(normalized);
      setError("");
    }catch(reason){
      setError(reason instanceof Error?reason.message:"Portfolio Koers kon niet worden geladen.");
    }finally{setLoading(false);setInitialChartReady(true)}
  },[timeframe]);

  useEffect(()=>{
    setLoading(true);
    void load();
    const timer=window.setInterval(()=>{if(document.visibilityState==="visible")void load()},45_000);
    const visible=()=>{if(document.visibilityState==="visible"){loadBrowserHistory();void load()}};
    document.addEventListener("visibilitychange",visible);
    return()=>{window.clearInterval(timer);document.removeEventListener("visibilitychange",visible)};
  },[load,loadBrowserHistory]);


  const loadActiveTrades=useCallback(async()=>{
    if(viewMode!=="active"||!activeTradesAvailable)return;
    setActiveLoading(true);
    try{
      const response=await authenticatedRequest(`/api/exchanges/aster/portfolio-chart/active-trades?timeframe=${encodeURIComponent(timeframe)}&limit=320`,{cache:"no-store"});
      setActivePayload(normalizeActiveTradesPayload(response));
      setActiveError("");
    }catch(reason){
      setActiveError(reason instanceof Error?reason.message:"Actieve Trades kon niet worden geladen.");
    }finally{setActiveLoading(false)}
  },[timeframe,viewMode,activeTradesAvailable]);

  useEffect(()=>{
    if(viewMode!=="active"||!activeTradesAvailable)return;
    void loadActiveTrades();
    const timer=window.setInterval(()=>{if(document.visibilityState==="visible")void loadActiveTrades()},5_000);
    const visible=()=>{if(document.visibilityState==="visible")void loadActiveTrades()};
    document.addEventListener("visibilitychange",visible);
    return()=>{window.clearInterval(timer);document.removeEventListener("visibilitychange",visible)};
  },[loadActiveTrades,viewMode,activeTradesAvailable]);

  useEffect(()=>{
    if(viewMode==="active")return;
    const equity=parsePortfolioEquityText(liveEquityText);
    if(!equity)return;
    setLiveEquity(equity);
    if(!candleSeriesRef.current||!candleDataRef.current.length)return;
    const previousTime=candleDataRef.current.at(-1)?.time??null;
    const next=mergeRealtimeEquitySample(candleDataRef.current,equity,Date.now(),timeframe) as Candle[];
    candleDataRef.current=next;
    const candle=next.at(-1);
    if(!candle)return;
    try{
      if(viewMode==="performance"){
        const anchorTime=next[0]?.time??candle.time;
        const shift=portfolioCashflowShift(markerRowsRef.current,anchorTime,candle.time);
        const adjusted=Math.max(Number.EPSILON,candle.close-shift);
        candleSeriesRef.current.update({time:candle.time as UTCTimestamp,value:adjusted});
      }else{
        candleSeriesRef.current.update({time:candle.time as UTCTimestamp,open:candle.open,high:candle.high,low:candle.low,close:candle.close});
        const bb=bollinger20x2(next);
        bbRefs.current.upper?.setData(bb.upper.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
        bbRefs.current.middle?.setData(bb.middle.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
        bbRefs.current.lower?.setData(bb.lower.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
      }
      syncOverlaysRef.current();
      if(previousTime===null||candle.time>previousTime){
        setHover(null);
        requestAnimationFrame(()=>{try{chartRef.current?.timeScale().scrollToRealTime()}catch{/* disposed */}});
      }
    }catch{/* the next confirmed payload rebuilds a stale chart safely */}
  },[liveEquityText,timeframe,viewMode]);

  const baseCandles=useMemo(()=>mergePortfolioKoersCandles(browserCandles,payload.candles,320) as Candle[],[browserCandles,payload.candles]);
  const activeCandles=activePayload.candles;
  const timelineCandles=useMemo(()=>liveEquity?mergeRealtimeEquitySample(baseCandles,liveEquity,Date.now(),timeframe) as Candle[]:baseCandles,[baseCandles,liveEquity,timeframe]);
  const chartTimeline=useMemo(()=>portfolioKoersTimelineHealth(timelineCandles,timeframe,Date.now(),1),[timelineCandles,timeframe]);
  const visibleTimelineStart=timelineCandles[Math.max(0,timelineCandles.length-((TIMEFRAME_VIEW[timeframe]||TIMEFRAME_VIEW["15m"]).visibleBars+3))]?.time??0;
  const recentChartGap=chartTimeline.gaps?.filter((gap:any)=>gap.beforeTime>=visibleTimelineStart).at(-1)??null;
  const currentZonePrice=liveEquity??payload.currentEquity??baseCandles.at(-1)?.close??null;
  const confirmedActiveZone=useMemo(()=>portfolioZoneForPrice(payload.zones,currentZonePrice),[payload.zones,currentZonePrice]);
  const advisorZoneSource=useMemo(()=>advisorTimeline?.safeForAdvisor===true&&advisorZones.length?advisorZones:payload.zones,[advisorTimeline?.safeForAdvisor,advisorZones,payload.zones]);
  const advisorZoneLadder=useMemo(()=>{
    if(!advisorZoneSource.length)return null;
    const base=derivePortfolioZoneLadder(advisorZoneSource);
    return extendPortfolioZoneLadderToPrice(base,currentZonePrice,2);
  },[advisorZoneSource,currentZonePrice]);
  const zoneContext=useMemo(()=>portfolioZoneContextFromLadder(advisorZoneLadder,currentZonePrice),[advisorZoneLadder,currentZonePrice]);
  const zoneSoldierReport=advisorSeats.zoneSoldiers;
  const runtimeTruth=advisorSeats.runtimeTruth;
  const runtimeTruthCanonical=runtimeTruth.source==="SERVER_RUNTIME";
  const runtimeZoneActive=runtimeTruthCanonical&&runtimeTruth.strategyMode==="ZONE_WARRIORS";
  const zoneSoldierEnabled=advisorEnabled&&(runtimeZoneActive?runtimeTruth.enabled===true:zoneSoldierReport.enabled===true);
  const zoneSoldierLifecycle=String(zoneSoldierReport.lifecycle||"OFF").toUpperCase();
  const liveDisplayActiveZone=zoneContext?.activeIndex??confirmedActiveZone;
  // Operational Zone Warriors status follows the server runtime contract.
  // The price-derived zone remains an informational fallback while releases overlap.
  const activeZone=runtimeZoneActive?signedIntegerOrNull(runtimeTruth.activeZone):liveDisplayActiveZone;
  advisorZoneLadderRef.current=advisorZoneLadder;
  activeZoneRef.current=activeZone;

  // The chart and sibling snapshot consume the same operational active zone.
  useEffect(()=>{onActiveZoneChange?.(activeZone)},[activeZone,onActiveZoneChange]);
  useEffect(()=>()=>{onActiveZoneChange?.(null)},[onActiveZoneChange]);
  useEffect(()=>{syncOverlaysRef.current()},[advisorZoneLadder,activeZone]);
  useEffect(()=>{setSelectedTpCluster(null);setTpDetailLoading(false);setTpDetailError("")},[timeframe,viewMode]);

  useEffect(()=>{
    const container=canvasRef.current;
    const observedEquity=parsePortfolioEquityText(liveEquityTextRef.current);
    const candles=(viewMode==="active"
      ? activeCandles
      : observedEquity?mergeRealtimeEquitySample(baseCandles,observedEquity,Date.now(),timeframe):baseCandles) as Candle[];
    if(!container||!candles.length){candleDataRef.current=[];setZoneLayout([]);setZoneBoundaries([]);setStructureOverlay(EMPTY_STRUCTURE_OVERLAY);setEventLabels([]);return}
    candleDataRef.current=candles.map((row)=>({...row}));
    const performancePoints=cashflowAdjustedPortfolioSeries(candles,markerRowsRef.current);
    const performanceByTime=new Map(performancePoints.map((row:any)=>[Number(row.time),Number(row.value)]));
    const view=TIMEFRAME_VIEW[timeframe]||TIMEFRAME_VIEW["15m"];
    // Keep the same logical viewport density for every tab. Sparse Active Trades history\n    // must not be auto-zoomed into giant candles; missing history stays empty rather than invented.\n    const focusVisibleBars=view.visibleBars;
    const chart=createChart(container,{
      width:Math.max(1,container.clientWidth),height:Math.max(220,container.clientHeight),
      layout:{background:{type:ColorType.Solid,color:"#03131b"},textColor:"#9fb0ba",fontSize:10,attributionLogo:false} as any,
      grid:{vertLines:{color:"rgba(75,133,160,.035)"},horzLines:{color:"rgba(75,133,160,.045)"}},
      crosshair:{mode:CrosshairMode.MagnetOHLC,vertLine:{color:"rgba(106,198,255,.48)",labelBackgroundColor:"#17394a"},horzLine:{color:"rgba(106,198,255,.48)",labelBackgroundColor:"#17394a"}},
      rightPriceScale:{borderColor:"rgba(85,160,190,.22)",minimumWidth:PRICE_AXIS_WIDTH,scaleMargins:{top:.06,bottom:.06}},
      timeScale:{borderColor:"rgba(85,160,190,.28)",timeVisible:true,secondsVisible:false,rightOffset:view.rightOffset,barSpacing:view.barSpacing,minBarSpacing:3,tickMarkFormatter:(time:unknown)=>{
        const sec=typeof time==="number"?time:0;
        if(!sec)return"";
        const date=new Date(sec*1000);
        if(timeframe==="24u")return date.toLocaleDateString("nl-NL",{timeZone:"Europe/Amsterdam",day:"2-digit",month:"short"});
        if(timeframe==="4u"||timeframe==="1u")return date.toLocaleString("nl-NL",{timeZone:"Europe/Amsterdam",day:"2-digit",month:"short",hour:"2-digit",hourCycle:"h23"});
        return date.toLocaleTimeString("nl-NL",{timeZone:"Europe/Amsterdam",hour:"2-digit",minute:"2-digit",hourCycle:"h23"});
      }},
      localization:{locale:"nl-NL",timeFormatter:(time:unknown)=>localTime(Number(time)||0)},
      handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:true},
      handleScale:{mouseWheel:true,pinch:true,axisPressedMouseMove:true},
    });
    chartRef.current=chart;
    const series=viewMode==="performance"
      ? chart.addSeries(LineSeries,{color:"#39eaa0",lineWidth:3,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:true})
      : chart.addSeries(CandlestickSeries,{upColor:"#17e6a0",downColor:"#ff5a66",wickUpColor:"#17e6a0",wickDownColor:"#ff6a74",borderVisible:false,priceLineVisible:false,lastValueVisible:true});
    candleSeriesRef.current=series;
    if(viewMode==="performance"){
      series.setData(performancePoints.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
    }else{
      series.setData(candles.map((row)=>({time:row.time as UTCTimestamp,open:row.open,high:row.high,low:row.low,close:row.close})));
    }

    const bb=viewMode==="account"?bollinger20x2(candles):{upper:[],middle:[],lower:[]};
    if(viewMode==="account"){
      const upper=chart.addSeries(LineSeries,{color:"rgba(18,152,255,.26)",lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
      const middle=chart.addSeries(LineSeries,{color:"rgba(226,235,239,.16)",lineWidth:1,lineStyle:2 as any,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
      const lower=chart.addSeries(LineSeries,{color:"rgba(240,46,73,.26)",lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
      bbRefs.current={upper,middle,lower};
      upper.setData(bb.upper.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
      middle.setData(bb.middle.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
      lower.setData(bb.lower.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
    }else{
      bbRefs.current={upper:null,middle:null,lower:null};
    }

    // Build 479: keep the visible price scale driven by the actual candles/Bollinger data.
    // Do not add invisible S2/R2 guide series: they widened the y-axis far beyond the
    // visible high/low and created large empty bands above and below the course.
    if(viewMode==="account"&&payload.cycleStartEquity&&payload.cycleStartEquity>0){
      series.createPriceLine({price:payload.cycleStartEquity,color:"rgba(229,190,75,.28)",lineWidth:1,lineStyle:2,axisLabelVisible:false,title:""});
    }

    const candleByTime=new Map(candles.map((row)=>[row.time,row]));
    const candleIndexByTime=new Map(candles.map((row,index)=>[row.time,index]));
    const bbUpperByTime=new Map(bb.upper.map((row:any)=>[Number(row.time),Number(row.value)]));
    const bbMiddleByTime=new Map(bb.middle.map((row:any)=>[Number(row.time),Number(row.value)]));
    const bbLowerByTime=new Map(bb.lower.map((row:any)=>[Number(row.time),Number(row.value)]));

    const syncOverlays=()=>{
      if(candleSeriesRef.current!==series||!container.isConnected)return;
      const height=Math.max(1,container.clientHeight),width=Math.max(1,container.clientWidth);
      const zoneLadder=advisorZoneLadderRef.current;
      const liveActiveZone=activeZoneRef.current;
      let structureDraft:StructureOverlayLayout=EMPTY_STRUCTURE_OVERLAY;
      if(viewMode!=="account"){
        // Strategy-zone prices belong to the account-equity axis only.
        // Performance and Active Trades keep the same zone footer context without
        // projecting account prices onto an incompatible chart scale.
        setZoneLayout([]);
        setZoneBoundaries([]);
      }else if(zoneLadder?.zones?.length){
        const zones=zoneLadder.zones.map((zone:any)=>{
          const upperY=zone.upper===Infinity?0:series.priceToCoordinate(zone.upper);
          const lowerY=zone.lower===-Infinity?height:series.priceToCoordinate(zone.lower);
          if(upperY===null||lowerY===null)return null;
          const rawTop=Math.min(Number(upperY),Number(lowerY));
          const rawBottom=Math.max(Number(upperY),Number(lowerY));
          const top=Math.max(0,Math.min(height,rawTop));
          const bottom=Math.max(0,Math.min(height,rawBottom));
          return {
            index:Number(zone.index),label:String(zone.label||""),
            top,height:Math.max(0,bottom-top),
            tone:zone.tone as ZoneLayout["tone"],
          };
        }).filter((zone:any)=>zone&&zone.height>1&&zone.top<height) as ZoneLayout[];
        setZoneLayout(zones);
        const boundaries=(zoneLadder.zones as any[]).slice(0,-1).map((zone:any)=>{
          const price=Number(zone.upper);
          const coordinate=Number.isFinite(price)?series.priceToCoordinate(price):null;
          if(coordinate===null)return null;
          const top=Number(coordinate);
          if(top<0||top>height)return null;
          const kind:ZoneBoundaryLayout["kind"]=liveActiveZone!==null&&zone.index===liveActiveZone
            ? "next-up"
            : liveActiveZone!==null&&zone.index===liveActiveZone-1
              ? "next-down"
              : "regular";
          return {price,top,kind,targetIndex:kind==="next-up"&&liveActiveZone!==null?liveActiveZone+1:kind==="next-down"&&liveActiveZone!==null?liveActiveZone-1:null};
        }).filter(Boolean) as ZoneBoundaryLayout[];
        setZoneBoundaries(boundaries);
      }else{
        setZoneBoundaries([]);
        const zoneCoordinates=payload.zones.map((zone)=>{
          const centerY=series.priceToCoordinate(zone.center);
          const upperY=series.priceToCoordinate(zone.upper);
          const lowerY=series.priceToCoordinate(zone.lower);
          if(centerY===null||upperY===null||lowerY===null)return null;
          return {
            index:zone.index,label:zone.label,
            centerY:Number(centerY),upperY:Number(upperY),lowerY:Number(lowerY),
            source:zone.source,
          };
        }).filter(Boolean);
        const zones=layoutPortfolioKoersZoneRegions(zoneCoordinates,height) as ZoneLayout[];
        setZoneLayout(zones);
      }

      if(viewMode==="account"&&zoneLadder?.zones?.length){
        const structurePrice=parsePortfolioEquityText(liveEquityTextRef.current)??payload.currentEquity??candles.at(-1)?.close??null;
        const marketContext=portfolioZoneContextFromLadder(zoneLadder,structurePrice);
        const rows=Array.isArray(zoneLadder.zones)?zoneLadder.zones as any[]:[];
        const activeIndex=marketContext?.activeIndex;
        const activeRow=rows.find((row:any)=>Number(row.index)===Number(activeIndex))??null;
        const step=Number(zoneLadder.step);
        const s1=Number.isFinite(Number(marketContext?.lowerBoundary))&&Number(marketContext?.lowerBoundary)>0
          ? Number(marketContext?.lowerBoundary)
          : Number.isFinite(Number(activeRow?.center))&&Number.isFinite(step)?Number(activeRow.center)-step/2:null;
        const r1=Number.isFinite(Number(marketContext?.upperBoundary))&&Number(marketContext?.upperBoundary)>0
          ? Number(marketContext?.upperBoundary)
          : Number.isFinite(Number(activeRow?.center))&&Number.isFinite(step)?Number(activeRow.center)+step/2:null;
        const below=rows.find((row:any)=>Number(row.index)===Number(activeIndex)-1);
        const above=rows.find((row:any)=>Number(row.index)===Number(activeIndex)+1);
        const s2=Number.isFinite(Number(below?.lower))?Number(below.lower):Number.isFinite(Number(s1))&&Number.isFinite(step)?Number(s1)-step:null;
        const r2=Number.isFinite(Number(above?.upper))?Number(above.upper):Number.isFinite(Number(r1))&&Number.isFinite(step)?Number(r1)+step:null;
        const activeLower=s1;
        const activeUpper=r1;
        const rawLevels=[
          {label:"R2",price:r2,side:"resistance"},
          {label:"R1",price:r1,side:"resistance"},
          {label:"S1",price:s1,side:"support"},
          {label:"S2",price:s2,side:"support"},
        ] as const;
        const levels=rawLevels.flatMap((level)=>{
          if(!Number.isFinite(Number(level.price))||Number(level.price)<=0)return [];
          const coordinate=series.priceToCoordinate(Number(level.price));
          if(coordinate===null)return [];
          const top=Number(coordinate);
          if(top<0||top>height)return [];
          return [{label:level.label,price:Number(level.price),top,side:level.side}] as StructureLevelLayout[];
        });
        const r1Level=levels.find((level)=>level.label==="R1");
        const r2Level=levels.find((level)=>level.label==="R2");
        const s1Level=levels.find((level)=>level.label==="S1");
        const activeUpperY=Number.isFinite(Number(activeUpper))?series.priceToCoordinate(Number(activeUpper)):null;
        const activeLowerY=Number.isFinite(Number(activeLower))?series.priceToCoordinate(Number(activeLower)):null;
        const activeTop=activeUpperY!==null&&activeLowerY!==null?Math.min(Number(activeUpperY),Number(activeLowerY)):null;
        const activeBottom=activeUpperY!==null&&activeLowerY!==null?Math.max(Number(activeUpperY),Number(activeLowerY)):null;
        const structureRange=chart.timeScale().getVisibleLogicalRange();
        const visibleCandles=candles.filter((_,index)=>!structureRange||(index>=Math.floor(structureRange.from)-1&&index<=Math.ceil(structureRange.to)+1));
        const visibleHigh=visibleCandles.reduce<Candle|null>((best,row)=>!best||row.high>best.high?row:best,null);
        const highX=visibleHigh?chart.timeScale().timeToCoordinate(visibleHigh.time as UTCTimestamp):null;
        const highY=visibleHigh?series.priceToCoordinate(visibleHigh.high):null;
        let roleFlipCandle:Candle|null=null;
        if(Number.isFinite(Number(s1))){
          for(let index=1;index<candles.length;index+=1){
            if(candles[index-1].close<=Number(s1)&&candles[index].close>Number(s1))roleFlipCandle=candles[index];
          }
        }
        const roleX=roleFlipCandle?chart.timeScale().timeToCoordinate(roleFlipCandle.time as UTCTimestamp):null;
        const roleY=Number.isFinite(Number(s1))?series.priceToCoordinate(Number(s1)):null;
        const zoneLabel=Number.isInteger(Number(activeIndex))?`Zone ${Number(activeIndex)} actief`:"Zone actief";
        structureDraft={
          levels,
          activeZone:activeTop!==null&&activeBottom!==null?{top:activeTop,height:Math.max(1,activeBottom-activeTop),label:zoneLabel}:null,
          roleFlip:roleX!==null&&roleY!==null&&Number(roleX)>70&&Number(roleX)<width-70?{left:Number(roleX),top:Number(roleY)}:null,
          newHigh:highX!==null&&highY!==null?{left:Math.max(92,Math.min(width-86,Number(highX))),top:Math.max(22,Number(highY)-28)}:null,
          breakout:r1Level?{left:Math.max(150,Math.min(width-92,width*.72)),top:Math.max(20,r1Level.top-30)}:null,
        };
      }else{
        structureDraft=EMPTY_STRUCTURE_OVERLAY;
      }

      const markerRows=markerRowsRef.current.filter((row)=>candleByTime.has(row.time));
      const visibleRange=chart.timeScale().getVisibleLogicalRange();
      const visibleMarkerRows=markerRows.filter((row)=>{
        const candleIndex=candleIndexByTime.get(row.time);
        if(candleIndex===undefined)return false;
        if(!visibleRange)return true;
        return candleIndex>=Math.floor(visibleRange.from)-1&&candleIndex<=Math.ceil(visibleRange.to)+1;
      });
      const candidates:any[]=[];
      for(let index=0;index<visibleMarkerRows.length;index+=1){
        const row=visibleMarkerRows[index],candle=candleByTime.get(row.time);
        if(!candle)continue;
        const visual=markerVisual(row);
        const x=chart.timeScale().timeToCoordinate(row.time as UTCTimestamp);
        const rawPrice=visual.position==="belowBar"?candle.low:candle.high;
        const performancePrice=performanceByTime.get(row.time);
        const markerPrice=viewMode==="performance"&&Number.isFinite(performancePrice)?Number(performancePrice):rawPrice;
        const y=series.priceToCoordinate(markerPrice);
        if(x===null||y===null)continue;
        const upperValue=bbUpperByTime.get(row.time),middleValue=bbMiddleByTime.get(row.time),lowerValue=bbLowerByTime.get(row.time);
        const upperY=Number.isFinite(upperValue)?series.priceToCoordinate(upperValue as number):null;
        const lowerY=Number.isFinite(lowerValue)?series.priceToCoordinate(lowerValue as number):null;
        const kind=String(row.kind||"").toLowerCase(),side=String(row.side||"").toUpperCase();
        const position=viewMode==="performance"
          ? (kind==="entry"&&side==="LONG"?"below":"above")
          : kind==="entry"
            ? (side==="SHORT"?"above":"below")
            : kind==="tp"&&Number.isFinite(middleValue)
              ? (candle.close>=Number(middleValue)?"above":"below")
              : visual.position==="belowBar"?"below":"above";
        const copy=markerPresentation(row);
        candidates.push({
          id:`${row.time}-${row.kind||""}-${row.side||""}-${index}`,
          x:Number(x),y:Number(y),time:row.time,kind:row.kind,
          priority:eventPriority(row),eventCount:Math.max(1,Number(row.count)||1),
          position,
          tone:copy.tone,title:copy.title,value:"",glyph:copy.glyph,multiplier:copy.multiplier,
          anchorLeft:Number(x),anchorTop:Number(y),markerTime:row.time,
          realizedPnlUsd:Number(row.realizedPnlUsd)||0,
          trades:Array.isArray(row.trades)?row.trades:[],
          bandTop:upperY===null?null:Number(upperY),bandBottom:lowerY===null?null:Number(lowerY),
          width:copy.tone==="cashflow"?92:copy.tone==="tp"?86:58,height:copy.tone==="tp"?34:30,
        });
      }
      const displayCandidates=selectPortfolioKoersReferenceCandidates(candidates,{tp:3,long:2,short:2,cashflow:1,other:1});
      const markerLayout=layoutPortfolioKoersMarkers(displayCandidates,{width,height},{priceAxisWidth:PRICE_AXIS_WIDTH,safetyCap:9});
      const reserved:StructureRect[]=[];
      if(structureDraft.activeZone){
        const zoneCenter=structureDraft.activeZone.top+structureDraft.activeZone.height/2;
        reserved.push({left:Math.max(0,width/2-58),right:Math.min(width-PRICE_AXIS_WIDTH,width/2+58),top:zoneCenter-16,bottom:zoneCenter+16});
      }
      setStructureOverlay({...structureDraft,roleFlip:null,newHigh:null,breakout:null});
      setEventLabels(markerLayout.all as EventLabel[]);
    };
    syncOverlaysRef.current=()=>requestAnimationFrame(syncOverlays);
    const onCrosshair=(param:any)=>{
      if(!param.time){setHover(null);return}
      const time=Number(param.time),candle=candleDataRef.current.find((row)=>row.time===time);
      if(!candle){setHover(null);return}
      setHover({candle,markers:markerRowsRef.current.filter((row)=>row.time===time)});
    };
    chart.subscribeCrosshairMove(onCrosshair);
    const sync=()=>syncOverlaysRef.current();
    chart.timeScale().subscribeVisibleLogicalRangeChange(sync);
    const resize=new ResizeObserver(()=>{
      if(chartRef.current!==chart||!container.isConnected)return;
      try{chart.applyOptions({width:Math.max(1,container.clientWidth),height:Math.max(220,container.clientHeight)});sync()}catch{/* disposed */}
    });
    resize.observe(container);
    container.addEventListener("pointermove",sync,{passive:true});
    container.addEventListener("touchmove",sync,{passive:true});
    chart.timeScale().setVisibleLogicalRange({
      from:viewMode==="active"?candles.length-focusVisibleBars-.5:Math.max(-.5,candles.length-focusVisibleBars-.5),
      to:candles.length-1+view.rightOffset,
    });
    sync();

    return()=>{
      resize.disconnect();chart.timeScale().unsubscribeVisibleLogicalRangeChange(sync);
      container.removeEventListener("pointermove",sync);container.removeEventListener("touchmove",sync);
      try{chart.unsubscribeCrosshairMove(onCrosshair);chart.remove()}catch{/* disposed */}
      if(chartRef.current===chart)chartRef.current=null;
      candleSeriesRef.current=null;bbRefs.current={upper:null,middle:null,lower:null};syncOverlaysRef.current=()=>{};setZoneBoundaries([]);setStructureOverlay(EMPTY_STRUCTURE_OVERLAY);setEventLabels([]);
    };
  },[baseCandles,activeCandles,payload.zones,payload.cycleStartEquity,timeframe,viewMode,cashflowSignature]);

  const fullscreen=async()=>{
    if(!shellRef.current)return;
    try{if(document.fullscreenElement)await document.exitFullscreen();else await shellRef.current.requestFullscreen()}catch{/* unsupported */}
  };
  const openPortfolioSettings=()=>{
    const nodes=Array.from(document.querySelectorAll<HTMLElement>("button,a,[role=button]"));
    const target=nodes.find((node)=>/botinstellingen|instellingen/i.test(node.textContent||"")&&!node.closest(".portfolio-koers-card"));
    target?.scrollIntoView({behavior:"smooth",block:"center"});
    target?.click();
  };
  const openPortfolioZones=()=>{
    if(commandCenterAvailable){setZoneSoldiersScreenOpen(true);return}
    window.dispatchEvent(new CustomEvent(ZONE_SOLDIERS_OPEN_EVENT));
  };

  const openTpCluster=useCallback(async(label:EventLabel)=>{
    setSelectedTpCluster(label);
    setTpDetailError("");
    const existing=Array.isArray(label.trades)?label.trades:[];
    const expected=Math.max(1,Number(label.eventCount)||1);
    if(existing.length>=expected&&existing.every((trade)=>trade.durationMinutes!==null))return;
    setTpDetailLoading(true);
    try{
      const response=record(await authenticatedRequest("/api/exchanges/aster/closed-trades",{cache:"no-store"}));
      const trades=tpTradesForBucketFromActivity(record(response.recentTradeActivity),timeframe,Number(label.markerTime)) as TpTrade[];
      setSelectedTpCluster((current)=>current?.id===label.id?{...current,trades}:current);
      if(!trades.length)setTpDetailError("Geen bevestigde fillregels voor dit cluster gevonden.");
    }catch(reason){
      setTpDetailError(advisorErrorText(reason,"Bevestigde filldetails tijdelijk niet beschikbaar."));
    }finally{
      setTpDetailLoading(false);
    }
  },[timeframe]);



  const latest=liveEquity??payload.currentEquity??baseCandles.at(-1)?.close??null;
  const activeHeaderValue=activePayload.currentOpenPnl;
  const activeHeaderPercent=activePayload.currentPnlPercent;
  const headerPerformanceSeries=cashflowAdjustedPortfolioSeries(timelineCandles,combinedMarkers);
  const headerPerformanceStart=Number(headerPerformanceSeries[0]?.value);
  const headerPerformanceEnd=Number(headerPerformanceSeries.at(-1)?.value);
  const headerPerformancePercent=Number.isFinite(headerPerformanceStart)&&headerPerformanceStart>0&&Number.isFinite(headerPerformanceEnd)
    ? ((headerPerformanceEnd-headerPerformanceStart)/headerPerformanceStart)*100
    : null;
  const zoneFormation=record(zoneSoldierReport.zoneFormation);
  const zoneCurrent=record(zoneSoldierReport.currentZone);
  const zoneOld=record(zoneSoldierReport.oldZonesOpen);
  const zoneOwned=record(zoneSoldierReport.strategyOwnedOpen);
  const zoneCurrentOwned=record(zoneSoldierReport.currentZoneOwned);
  const zoneExposure=record(zoneSoldierReport.exposure);
  const zoneBalancer=record(zoneSoldierReport.balancer);
  const zoneHomecomings=record(zoneSoldierReport.homecomings);
  const zoneEntrySizing=record(zoneSoldierReport.entrySizing);
  const zoneEntryMultiplier=Number(zoneEntrySizing.activeZoneMultiplier);
  const zoneEntryGrowthPercent=Number(zoneEntrySizing.growthPercentPerZone);
  const zoneEntryActiveUsd=Number(zoneEntrySizing.activeZoneEntryUsd);
  const zoneBaseLong=integerOrNull(zoneFormation.baseLongSoldiers);
  const zoneBaseShort=integerOrNull(zoneFormation.baseShortSoldiers);
  const zoneOpenLong=integerOrNull(zoneCurrent.openLong);
  const zoneOpenShort=integerOrNull(zoneCurrent.openShort);
  const zoneFreeLong=integerOrNull(zoneCurrent.freeLong);
  const zoneFreeShort=integerOrNull(zoneCurrent.freeShort);
  const oldOpenTotal=integerOrNull(zoneOld.total);
  const oldOpenLong=integerOrNull(zoneOld.long);
  const oldOpenShort=integerOrNull(zoneOld.short);
  const strategyOwnedTotal=integerOrNull(zoneOwned.total);
  const strategyOwnedLong=integerOrNull(zoneOwned.long);
  const strategyOwnedShort=integerOrNull(zoneOwned.short);
  const currentZoneOwnedLong=integerOrNull(zoneCurrentOwned.long);
  const currentZoneOwnedShort=integerOrNull(zoneCurrentOwned.short);
  const zoneTotalActive=integerOrNull(zoneSoldierReport.totalActive);
  const zoneTotalLong=integerOrNull(zoneSoldierReport.totalLongOpenCount);
  const zoneTotalShort=integerOrNull(zoneSoldierReport.totalShortOpenCount);
  const legacyUnassignedOpen=integerOrNull(zoneSoldierReport.legacyUnassignedOpenCount)??0;
  const longExposureUsd=Number(zoneExposure.totalLongNotional);
  const shortExposureUsd=Number(zoneExposure.totalShortNotional);
  const netExposureUsd=Number(zoneExposure.netExposureUsd);
  const netExposureSide=String(zoneExposure.netExposureSide||"FLAT");
  const zoneImbalancePercent=Number(zoneExposure.imbalancePercent);
  const balancerSide=String(zoneBalancer.activeSide||"");
  const balancerDesired=integerOrNull(zoneBalancer.desiredCount)??0;
  const balancerOpen=integerOrNull(zoneBalancer.openCount)??0;
  const balancerPending=Math.max(0,balancerDesired-balancerOpen);
  const balancerMessage=String(zoneBalancer.message||"Geen correctie nodig");
  const zoneEntriesSafe=runtimeZoneActive?runtimeTruth.zoneSafeForNewEntries===true:zoneSoldierReport.safeForNewEntries===true;
  const drainingOpenCount=integerOrNull(zoneSoldierReport.drainingOpenCount)??0;
  const advisorTimelineReady=advisorTimeline?.safeForAdvisor===true;
  const timelineGap=advisorTimeline?.gaps?.at(-1)??null;
  const timelineWait=advisorTimeline
    ? timelineGap
      ? `Historiegat ${clockTime(timelineGap.fromTime)}–${clockTime(timelineGap.toTime)} · nieuwe entries worden geblokkeerd zolang de prijszone-strategie actief is.`
      : !advisorTimelineReady
        ? `Wachten op ${Math.max(0,Number(advisorTimeline.requiredContiguousBars)-Number(advisorTimeline.contiguousBars))} extra bevestigde 15m-candles voor handelssturing.`
        : ""
    : "15m-zonebasis tijdelijk niet bevestigd; grafiek blijft informatief.";
  const instructionTitle=zoneSoldierEnabled
    ? (!zoneEntriesSafe?"Zone-entry wacht op bevestigde 15m-zone":balancerMessage)
    : zoneSoldierLifecycle==="DRAINING"
      ? `Zone-strategie uitgeschakeld · bestaande ${drainingOpenCount} positie(s) worden nog beheerd`
      : activeZone===null
        ? "Portfoliozone wordt berekend"
        : `Portfolio bevindt zich momenteel in Z${signedZone(activeZone)}`;
  const upperTrigger=zoneContext?.upperBoundary??null;
  const lowerTrigger=zoneContext?.lowerBoundary??null;
  const nextUpIndex=zoneContext?.nextUpIndex??null;
  const nextDownIndex=zoneContext?.nextDownIndex??null;
  const upperDistancePercent=portfolioZoneDistancePercent(upperTrigger,currentZonePrice);
  const lowerDistancePercent=portfolioZoneDistancePercent(lowerTrigger,currentZonePrice);
  const zoneProgressPercent=portfolioZoneProgress(currentZonePrice,lowerTrigger,upperTrigger);
  const nextTriggerSummary=[
    upperTrigger!==null&&nextUpIndex!==null&&upperDistancePercent!==null?`↑ Nog ${percent2(upperDistancePercent)} tot Z${signedZone(nextUpIndex)}`:"",
    lowerTrigger!==null&&nextDownIndex!==null&&lowerDistancePercent!==null?`↓ ${percent2(lowerDistancePercent,false)} tot Z${signedZone(nextDownIndex)}`:"",
  ].filter(Boolean);
  const zoneBandSummary=lowerTrigger!==null&&upperTrigger!==null
    ? `${levelUsd(lowerTrigger)}–${levelUsd(upperTrigger)}`
    : lowerTrigger!==null
      ? `vanaf ${levelUsd(lowerTrigger)}`
      : upperTrigger!==null
        ? `tot ${levelUsd(upperTrigger)}`
        : "—";
  const zoneBasisSummary=activeZone===null
    ? `Zonebasis: portfolio-equity · 15m support/resistance · ${timelineWait}`
    : `Zonebasis: portfolio-equity · 15m support/resistance · Z${signedZone(activeZone)} · ${zoneSoldierEnabled?"handelssturing expliciet actief":"informatief; geen orders of slotwijzigingen"}.`;
  const strategyStatus=zoneSoldierEnabled
    ? (!zoneEntriesSafe?"WACHT":balancerSide&&balancerPending>0?"BALANS NODIG":"ACTIEF")
    : zoneSoldierLifecycle==="DRAINING"?"DRAINING":"INFORMATIEF";
  const strategyTone=zoneSoldierEnabled
    ? (!zoneEntriesSafe?"waiting":balancerSide&&balancerPending>0?"balancing":"active")
    : zoneSoldierLifecycle==="DRAINING"?"draining":"informational";
  const strategyAction=zoneSoldierEnabled
    ? !zoneEntriesSafe
      ? "Wacht op zonebevestiging"
      : balancerSide&&balancerPending>0
        ? `+${balancerPending} ${balancerSide} gewenst`
        : ((zoneFreeLong??0)+(zoneFreeShort??0)>0
          ? `Wacht op entry · ${zoneFreeLong??0}L / ${zoneFreeShort??0}S vrij`
          : "Zone-stoelen gevuld")
    : instructionTitle;
  const exposureValue=Number.isFinite(netExposureUsd)
    ? (Math.abs(netExposureUsd)<.005?"FLAT":`${levelUsd(Math.abs(netExposureUsd))} ${netExposureSide}`)
    : "—";
  const activeZoneLabel=activeZone===null?"—":`Z${signedZone(activeZone)}`;
  const nextZoneLabel=nextUpIndex!==null?`Z${signedZone(nextUpIndex)}`:nextDownIndex!==null?`Z${signedZone(nextDownIndex)}`:"—";
  const nextZoneDistance=upperDistancePercent!==null
    ? `↑ ${percent2(upperDistancePercent)}`
    : lowerDistancePercent!==null
      ? `↓ ${percent2(lowerDistancePercent,false)}`
      : "—";

  const commandCenterVm=buildStrategyStatusCommandCenter({
    strategyEnabled:zoneSoldierEnabled,
    zoneSafe:zoneEntriesSafe,
    activeZone,
    nextZone:nextUpIndex,
    previousZone:nextDownIndex,
    currentZoneLower:lowerTrigger,
    currentZoneUpper:upperTrigger,
    nextZonePrice:upperTrigger,
    previousZonePrice:lowerTrigger,
    currentEquity:currentZonePrice,
    baseLong:zoneBaseLong,
    baseShort:zoneBaseShort,
    actualLong:liveLongText,
    actualShort:liveShortText,
    totalActive:zoneTotalActive,
    zoneOpenLong,
    zoneOpenShort,
    zoneFreeLong,
    zoneFreeShort,
    oldZonesOpenTotal:oldOpenTotal,
    oldZonesOpenLong:oldOpenLong,
    oldZonesOpenShort:oldOpenShort,
    strategyOwnedTotal,
    strategyOwnedLong,
    strategyOwnedShort,
    currentZoneOwnedLong,
    currentZoneOwnedShort,
    netExposureUsd,
    netExposureSide,
    entryPriority:zoneSoldierReport.entryPriority??zoneBalancer.prioritySide??zoneBalancer.activeSide,
    homecomingEvents:Array.isArray(zoneHomecomings.events)?zoneHomecomings.events:[],
    availableText:liveAvailableText,
    activeZoneEntryUsd:zoneEntrySizing.activeZoneEntryUsd,
    entrySizingMode:zoneEntrySizing.mode??advisorSeats.settings.entrySizingMode,
    minimumLeverage:advisorSeats.settings.minimumLeverage,
    entryFeeBufferUsd:advisorSeats.settings.entryFeeBufferUsd,
    minimumOrderMarginUsd:advisorSeats.settings.minimumOrderMarginUsd,
    dcaMarginUsd:advisorSeats.settings.dcaMarginUsd,
    dcaFeeBufferUsd:advisorSeats.settings.dcaFeeBufferUsd,
    maxDca:advisorSeats.settings.maxDca,
    unlimitedDca:advisorSeats.settings.unlimitedDca===true,
    soldierActivity,
  });

  return <section ref={shellRef} className={`portfolio-koers-card portfolio-zone-map portfolio-koers-ui41 ${advisorEnabled?"beta-zone-advisor":""}`} aria-label="Portfolio Koers" data-reference={PORTFOLIO_KOERS_UI41_REFERENCE} data-structure-reference={PORTFOLIO_STRUCTURE_REFERENCE} data-structure-baseline-reference={PORTFOLIO_STRUCTURE_BASELINE_REFERENCE} data-zone-advisor-reference={advisorEnabled?ZONE_ADVISOR_REFERENCE:undefined}>
    <header className="portfolio-koers-header portfolio-koers-ui41-header">
      <div className="portfolio-koers-ui41-top">
        <div className="portfolio-koers-heading">
          <div className="portfolio-koers-title-line"><h2>Portfolio Koers</h2><span className={(viewMode==="active"?activePayload.live:payload.live)?"portfolio-koers-live is-live":"portfolio-koers-live"}><i/>{(viewMode==="active"?activePayload.live:payload.live)?"Live":"Sync"}</span></div>
          <small>{viewMode==="active"?"Actieve Trades":"Accountwaarde"}</small>
        </div>
        <div className="portfolio-koers-ui41-actions">
          <button type="button" className="portfolio-koers-settings" onClick={openPortfolioSettings} aria-label="Portfolio Koers instellingen">⚙</button>
          <button type="button" className="portfolio-koers-zones-button" onClick={openPortfolioZones}><span aria-hidden="true">◎</span>Zones</button>
        </div>
      </div>
      <div className="portfolio-koers-ui41-value">
        <strong>{viewMode==="active"?signedUsd(activeHeaderValue):accountUsd(latest)}</strong>
        <span className={(viewMode==="active"?activeHeaderPercent:headerPerformancePercent)!==null&&Number(viewMode==="active"?activeHeaderPercent:headerPerformancePercent)<0?"negative":""}>{(viewMode==="active"?activeHeaderPercent:headerPerformancePercent)===null?"—":percent2(viewMode==="active"?activeHeaderPercent:headerPerformancePercent)}</span>
      </div>
      <div className="portfolio-koers-ui41-controls">
        <div className="portfolio-koers-toolbar" role="group" aria-label="Portfolio Koers timeframe">
          {PORTFOLIO_KOERS_TIMEFRAMES.map((value)=><button type="button" key={value} className={timeframe===value?"active":""} onClick={()=>setTimeframe(value)}>{value}</button>)}
        </div>
        <button type="button" className="portfolio-koers-fullscreen" onClick={fullscreen} aria-label="Portfolio Koers fullscreen">↗</button>
      </div>
      <div className="portfolio-koers-view-toggle" role="group" aria-label="Portfolio Koers weergave">
        <button type="button" className={viewMode==="performance"?"active":""} onClick={()=>setViewMode("performance")}>PERFORMANCE</button>
        <button type="button" className={viewMode==="account"?"active":""} onClick={()=>setViewMode("account")}>ACCOUNTWAARDE</button>
        {activeTradesAvailable?<button type="button" className={viewMode==="active"?"active":""} onClick={()=>setViewMode("active")}>ACTIEVE TRADES</button>:null}
      </div>
    </header>
    <div className="portfolio-koers-stage">
      <div ref={canvasRef} className="portfolio-koers-canvas"/>
      {!initialChartReady?<div className="portfolio-koers-state portfolio-koers-initial-state"><i/>Accountwaarde laden…</div>:null}
      {viewMode!=="active"&&recentChartGap?<div className="portfolio-koers-gap-warning" role="status">⚠ Historiegat {clockTime(recentChartGap.fromTime)}–{clockTime(recentChartGap.toTime)} · geen koerswaarden verzonnen</div>:null}
      {viewMode==="performance"?<div className="portfolio-koers-performance-note">PERFORMANCE · cashflow gecorrigeerd<span>Strategyzones staan alleen bij Accountwaarde</span></div>:null}
      {viewMode==="active"?<div className="portfolio-koers-active-note">ACTIEVE TRADES INDEX<span>Entry/exit gecorrigeerd · alleen open posities</span></div>:null}
      <div className={`portfolio-koers-zones ${zoneLayout.length?"is-ready":""}`} aria-hidden="true">{zoneLayout.map((zone)=><div key={zone.index} className={`portfolio-koers-zone zone-${zone.tone} ${zoneLevelClass(zone.index)} ${zone.index===activeZone?"active":""}`} style={{top:`${zone.top}px`,height:`${zone.height}px`}}><span>{zone.label}</span></div>)}</div>
      <div className="portfolio-koers-zone-boundaries" aria-hidden="true">{zoneBoundaries.map((boundary,index)=>{const distance=portfolioZoneDistancePercent(boundary.price,currentZonePrice);return <div key={`${boundary.price}-${index}`} className={`portfolio-koers-zone-boundary ${boundary.kind}`} style={{top:`${boundary.top}px`}}>{boundary.kind!=="regular"?<span title={`Exacte grens ${levelUsd(boundary.price)}`}>{boundary.kind==="next-up"?"↑":"↓"} Z{signedZone(boundary.targetIndex)} · {percent2(distance)}</span>:null}</div>})}</div>
      {viewMode==="account"?<div className="portfolio-koers-structure-layer" data-reference={PORTFOLIO_STRUCTURE_REFERENCE} aria-hidden="true">
        {structureOverlay.activeZone?<div className="portfolio-koers-structure-zone" style={{top:`${structureOverlay.activeZone.top}px`,height:`${structureOverlay.activeZone.height}px`}}><span>{structureOverlay.activeZone.label}</span></div>:null}
        {structureOverlay.levels.map((level)=><div key={level.label} className={`portfolio-koers-structure-level ${level.side}`} style={{top:`${level.top}px`}}><span>{level.label}</span></div>)}
      </div>:null}
      <div className="portfolio-koers-event-layer">{eventLabels.map((label)=>{
        const connector=connectorStyle(label);
        const isTp=label.tone==="tp";
        return <div key={label.id} className="portfolio-koers-event-group">
          {isTp&&connector?<span className="portfolio-koers-connector tp" style={connector}/>:null}
          {isTp&&Number.isFinite(label.anchorLeft)&&Number.isFinite(label.anchorTop)?<span className="portfolio-koers-anchor tp" style={{left:`${label.anchorLeft}px`,top:`${label.anchorTop}px`}}/>:null}
          <button
            type="button"
            className={`portfolio-koers-event portfolio-koers-event-chip ${label.tone} ${label.position} ${(label as any).compressed?"compressed":""}`}
            style={{left:`${label.left}px`,top:`${label.top}px`}}
            onClick={isTp?()=>void openTpCluster(label):undefined}
            tabIndex={isTp?0:-1}
            aria-label={isTp?`Take Profit cluster ${signedUsd(label.realizedPnlUsd)}, ${label.eventCount||1} trades`:undefined}
          >
            {label.tone==="long"?<DirectionArrow direction="up"/>:label.tone==="short"?<DirectionArrow direction="down"/>:isTp?<MoneyBagIcon/>:null}
            <b>{label.multiplier||`+${label.eventCount}`}</b>
            {isTp&&Number(label.eventCount)>1?<span className="portfolio-koers-event-count">{label.eventCount}</span>:null}
          </button>
        </div>
      })}</div>
      {selectedTpCluster?<div className="portfolio-koers-tp-detail-shell" data-reference={PORTFOLIO_KOERS_UI41_DETAIL_REFERENCE}>
        {tpDetailConnectorStyle(selectedTpCluster)?<span className="portfolio-koers-tp-detail-leader" style={tpDetailConnectorStyle(selectedTpCluster)}/>:null}
        <section className="portfolio-koers-tp-detail" onDoubleClick={()=>setSelectedTpCluster(null)} aria-label="Take Profit details">
          <header><MoneyBagIcon/><strong>Totaal gerealiseerd: <b>{signedUsd(selectedTpCluster.realizedPnlUsd)}</b></strong><button type="button" onClick={()=>setSelectedTpCluster(null)} aria-label="Sluiten">×</button></header>
          <div className="portfolio-koers-tp-trades">
            {(selectedTpCluster.trades||[]).map((trade,index)=><div className="portfolio-koers-tp-trade" key={`${trade.symbol}-${index}`}>
              <strong><CoinBadge symbol={trade.symbol}/><span>{String(trade.symbol||"").replace(/(?:USDT|USDC|BUSD|USD)$/,"")}</span></strong>
              <b>{signedUsd(trade.realizedPnlUsd)}</b>
              <span>{durationLabel(trade.durationMinutes)}</span>
            </div>)}
            {tpDetailLoading?<div className="portfolio-koers-tp-empty loading">Bevestigde fills laden…</div>:null}
            {!tpDetailLoading&&tpDetailError?<div className="portfolio-koers-tp-empty error">{tpDetailError}</div>:null}
            {!tpDetailLoading&&!tpDetailError&&!(selectedTpCluster.trades||[]).length?<div className="portfolio-koers-tp-empty">Geen bevestigde filldetails beschikbaar.</div>:null}
          </div>
          <footer>⌁&nbsp;&nbsp; Dubbeltik om te sluiten</footer>
        </section>
      </div>:null}
      {viewMode==="active"&&activeLoading&&!activeCandles.length?<div className="portfolio-koers-state"><i/>Actieve Trades laden…</div>:null}
      {viewMode==="active"&&!activeLoading&&!activeCandles.length&&!activeError?<div className="portfolio-koers-state"><strong>Actieve Trades-historie wordt opgebouwd</strong><span>Alleen exchange-bevestigde open posities worden opgeslagen; oudere waarden worden niet verzonnen.</span></div>:null}
      {viewMode==="active"&&activeError&&!activeCandles.length?<div className="portfolio-koers-state error"><strong>Actieve Trades tijdelijk niet beschikbaar</strong><span>{activeError}</span><button type="button" onClick={()=>void loadActiveTrades()}>Opnieuw proberen</button></div>:null}
      {viewMode!=="active"&&loading&&initialChartReady&&!baseCandles.length?<div className="portfolio-koers-state"><i/>Portfoliohistorie laden…</div>:null}
      {viewMode!=="active"&&!loading&&!baseCandles.length&&!error?<div className="portfolio-koers-state"><strong>Historie wordt opgebouwd</strong><span>Nieuwe candles gebruiken bevestigde Aster-equity; bestaande bevestigde browserhistorie wordt veilig hergebruikt als die beschikbaar is.</span></div>:null}
      {viewMode!=="active"&&error&&!baseCandles.length?<div className="portfolio-koers-state error"><strong>Portfolio Koers tijdelijk niet beschikbaar</strong><span>{error}</span><button type="button" onClick={()=>void load()}>Opnieuw proberen</button></div>:null}
      {hover?<div className="portfolio-koers-tooltip"><span>{localTime(hover.candle.time)}</span>{viewMode==="performance"?<b>Performance {compactUsd(hover.candle.close-portfolioCashflowShift(combinedMarkers,baseCandles[0]?.time??hover.candle.time,hover.candle.time))}</b>:<><b>O {viewMode==="active"?signedUsd(hover.candle.open):compactUsd(hover.candle.open)}</b><b>H {viewMode==="active"?signedUsd(hover.candle.high):compactUsd(hover.candle.high)}</b><b>L {viewMode==="active"?signedUsd(hover.candle.low):compactUsd(hover.candle.low)}</b><b>C {viewMode==="active"?signedUsd(hover.candle.close):compactUsd(hover.candle.close)}</b></>}{hover.markers.map((row,index)=><em key={`${row.kind}-${row.side}-${index}`}>{markerDetail(row)}</em>)}</div>:null}
    </div>
    <div className="portfolio-koers-ui41-footer" data-reference={PORTFOLIO_KOERS_UI41_REFERENCE}>
      <strong><span aria-hidden="true">◎</span>{activeZone===null?"Zone —":`Zone ${activeZone} actief`}</strong>
      <span className="portfolio-koers-ui41-next">Volgende: <b className="up">↑ {percent2(upperDistancePercent,false)}</b><b className="down">↓ {percent2(lowerDistancePercent,false)}</b></span>
      <span className="portfolio-koers-ui41-bb">BB 20,2</span>
      <span className="portfolio-koers-ui41-info" title="Bollinger Band 20,2 · actieve zone uit live portfolio-equity">i</span>
    </div>
    <div className="portfolio-koers-ui41-hint"><MoneyBagIcon/><span>Tik op een TP-marker om de posities te bekijken</span></div>
    {viewMode==="active"?<section className="portfolio-koers-active-summary" aria-label="Actieve Trades Samenvatting">
      <h3>Actieve Trades Samenvatting</h3>
      <div className="portfolio-koers-active-summary-grid">
        <article><small>HUIDIGE OPEN P&amp;L</small><strong className={Number(activePayload.currentOpenPnl)<0?"negative":"positive"}>{signedUsd(activePayload.currentOpenPnl)}</strong><em>{percent2(activePayload.currentPnlPercent)}</em></article>
        <article><small>HOOGSTE VANDAAG</small><strong className={Number(activePayload.dayHigh)<0?"negative":"positive"}>{signedUsd(activePayload.dayHigh)}</strong></article>
        <article><small>LAAGSTE VANDAAG</small><strong className={Number(activePayload.dayLow)<0?"negative":"positive"}>{signedUsd(activePayload.dayLow)}</strong></article>
        <article><small>HERSTEL VANAF BODEM</small><strong className="positive">{percent2(activePayload.recoveryPercent)}</strong></article>
        <article><small>LONG BIJDRAGE</small><strong className={Number(activePayload.longPnl)<0?"negative":"positive"}>↑ {signedUsd(activePayload.longPnl)}</strong><em>{percent2(activePayload.longSharePercent,false)} van notional</em></article>
        <article><small>SHORT BIJDRAGE</small><strong className={Number(activePayload.shortPnl)<0?"negative":"positive"}>↓ {signedUsd(activePayload.shortPnl)}</strong><em>{percent2(activePayload.shortSharePercent,false)} van notional</em></article>
        <article><small>AANTAL ACTIEVE TRADES</small><strong>{activePayload.activeTrades}</strong><em><b className="long">{activePayload.longTrades} LONG</b> · <b className="short">{activePayload.shortTrades} SHORT</b></em></article>
        <article><small>NOTIONAL TOTAAL</small><strong>{accountUsd(activePayload.totalNotional)}</strong><em>exchange-bevestigd</em></article>
      </div>
    </section>:null}
    {zoneSoldiersScreenOpen&&commandCenterAvailable?<ZoneSoldiersCommandCenterScreen vm={commandCenterVm} advisorMessage={advisorMessage} onClose={()=>setZoneSoldiersScreenOpen(false)}/>:null}
    {false?<section className={`portfolio-strategy-cockpit ${strategyTone}`} data-reference={ZONE_ADVISOR_REFERENCE} aria-live="polite">
      <header className="portfolio-strategy-head">
        <span className="portfolio-strategy-mark" aria-hidden="true">{zoneSoldierEnabled?"⌖":"◎"}</span>
        <div className="portfolio-strategy-heading">
          <small>{zoneSoldierEnabled?"PRIJSZONE-STOELEN":zoneSoldierLifecycle==="DRAINING"?"ZONE DRAINING":"PORTFOLIOZONE"}</small>
          <strong>Strategiestatus</strong>
        </div>
        <span className={`portfolio-strategy-status ${strategyTone}`}><i/>{strategyStatus}</span>
      </header>

      <div className={`portfolio-strategy-action ${balancerSide.toLowerCase()}`}>
        <span className="portfolio-strategy-action-icon" aria-hidden="true">{balancerSide==="LONG"?"↗":balancerSide==="SHORT"?"↘":zoneSoldierEnabled?"⚔":"⌖"}</span>
        <div>
          <small>NU</small>
          <strong>{strategyAction}</strong>
          <em>{zoneSoldierEnabled?(zoneEntriesSafe?`${activeZoneLabel} bevestigd · entries binnen zone-capaciteit`:"15m-zone nog niet veilig bevestigd"):zoneSoldierLifecycle==="DRAINING"?`${drainingOpenCount} lopende zone-posities worden beheerd`:"Geen automatische zone-acties"}</em>
        </div>
      </div>

      <div className="portfolio-strategy-grid">
        <article className="zone">
          <span className="portfolio-strategy-tile-icon" aria-hidden="true">⌖</span>
          <div><small>ACTIEVE ZONE</small><strong>{activeZoneLabel}</strong><em>{zoneBandSummary}</em></div>
        </article>
        <article className="formation">
          <span className="portfolio-strategy-tile-icon" aria-hidden="true">⚔</span>
          <div><small>STOELEN ACTIEVE ZONE</small><strong>{zoneSoldierEnabled?`${zoneOpenLong??"—"}L · ${zoneOpenShort??"—"}S`:"—"}</strong><em>{zoneSoldierEnabled?`doel ${zoneBaseLong??"—"}L · ${zoneBaseShort??"—"}S · vrij ${zoneFreeLong??"—"}L/${zoneFreeShort??"—"}S`:"alleen informatief"}</em></div>
        </article>
        <article className={`balance ${netExposureSide==="LONG"?"long":netExposureSide==="SHORT"?"short":"flat"}`}>
          <span className="portfolio-strategy-tile-icon" aria-hidden="true">⇄</span>
          <div><small>BALANS</small><strong>{zoneSoldierEnabled?exposureValue:"—"}</strong><em>{zoneSoldierEnabled&&Number.isFinite(zoneImbalancePercent)?`${zoneImbalancePercent.toFixed(1)}% onbalans`:"geen zone-sturing"}</em></div>
        </article>
        <article className="next-zone">
          <span className="portfolio-strategy-tile-icon" aria-hidden="true">↗</span>
          <div><small>VOLGENDE ZONE</small><strong>{nextZoneLabel}</strong><em>{nextZoneDistance}</em></div>
        </article>
      </div>

      {zoneProgressPercent!==null&&nextUpIndex!==null?<span className="portfolio-koers-zone-progress portfolio-strategy-progress" title={`Exacte zonegrenzen: ${zoneBandSummary}`}><i><em style={{width:`${zoneProgressPercent}%`}}/></i><b>{Math.round(zoneProgressPercent)}%</b><span>richting ↑ Z{signedZone(nextUpIndex)}</span></span>:null}

      <footer className="portfolio-strategy-foot">
        {zoneSoldierEnabled?<><span><b>{zoneTotalActive??"—"}</b> prijszone-posities · <b className="long">{zoneTotalLong??"—"}L</b> / <b className="short">{zoneTotalShort??"—"}S</b></span>{(oldOpenTotal??0)>0?<span>oude zones <b>{oldOpenTotal}</b></span>:null}</>:<span>{zoneBasisSummary}</span>}
        {advisorMessage?<em>{advisorMessage}</em>:null}
      </footer>

      <span className="portfolio-koers-cockpit-sr">
        {zoneSoldierEnabled?`ZONE-STURING ACTIEF. ZONEFORMATIE ${zoneBaseLong??"—"}L ${zoneBaseShort??"—"}S. IN ZONE OPEN ${zoneOpenLong??"—"}L ${zoneOpenShort??"—"}S. IN ZONE VRIJ ${zoneFreeLong??"—"}L ${zoneFreeShort??"—"}S. Oude zones nog open: ${oldOpenTotal??"—"}, ${oldOpenLong??"—"}L, ${oldOpenShort??"—"}S, ${legacyUnassignedOpen} legacy. Inzet zone: ${Number.isFinite(zoneEntryMultiplier)?"×"+zoneEntryMultiplier.toFixed(2):"—"}; ${Number.isFinite(zoneEntryGrowthPercent)?"+"+zoneEntryGrowthPercent.toFixed(1)+"% per zoneafstand":""}; ${Number.isFinite(zoneEntryActiveUsd)?levelUsd(zoneEntryActiveUsd):"—"}. Exposure: L ${Number.isFinite(longExposureUsd)?levelUsd(longExposureUsd):"—"}, S ${Number.isFinite(shortExposureUsd)?levelUsd(shortExposureUsd):"—"}, netto ${exposureValue}. ${balancerMessage}`:zoneSoldierLifecycle==="DRAINING"?"ZONE DRAINING · geen nieuwe zone-entrys. "+zoneBasisSummary:"INFORMATIEF. "+zoneBasisSummary}
      </span>
    </section>:null}
    <span className="portfolio-koers-current-sr">Actuele portfolio waarde {latest===null?"onbekend":compactUsd(latest)}</span>
  </section>;
}