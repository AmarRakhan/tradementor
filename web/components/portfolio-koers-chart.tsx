"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CandlestickSeries, ColorType, CrosshairMode, LineSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { authenticatedRequest } from "@/lib/cloud-client";
import { useAuthSession } from "@/components/auth-provider";
import { sanitizePortfolioEquityRows } from "@/lib/portfolio-equity-history";
import { PORTFOLIO_KOERS_DEFAULT_TIMEFRAME, PORTFOLIO_KOERS_TIMEFRAMES, aggregatePortfolioEquityHistory, bollinger20x2, markerVisual, mergePortfolioKoersCandles, mergeRealtimeEquitySample, normalizePortfolioKoersPayload, parsePortfolioEquityText, portfolioKoersFocusBars, portfolioKoersTimelineHealth, portfolioZoneDistancePercent, portfolioZoneForPrice, portfolioZoneProgress } from "@/lib/portfolio-koers-chart.mjs";
import { eventPriority, layoutPortfolioKoersMarkers, layoutPortfolioKoersZoneRegions } from "@/lib/portfolio-koers-marker-layout.mjs";
import { derivePortfolioZoneLadder, portfolioZoneContextFromLadder } from "@/lib/portfolio-zone-advisor.mjs";

type Candle={time:number;atMs:number;open:number;high:number;low:number;close:number;samples:number;sourceAtMs:number};
type Zone={index:number;label:string;center:number;lower:number;upper:number;touches:number;atr:number;source:string};
type Marker={time:number;atMs:number;kind?:string;side?:string;label?:string;count?:number;notionalUsd?:number;realizedPnlUsd?:number;amountUsd?:number;cashflowType?:string;originZones?:number[];soldierRoles?:string[]};
type Payload={timeframe:string;candles:Candle[];markers:Marker[];zones:Zone[];currentZone:number|null;cycleStartEquity:number|null;currentEquity:number|null;snapshotAtMs:number|null;live:boolean;persistent:boolean;externalCashflowsSeparated:boolean;readOnly:boolean;ordersSent:number;source:string};
type ZoneLayout={index:number;label:string;top:number;height:number;tone:"red"|"amber"|"green"|"blue"};
type ZoneBoundaryLayout={price:number;top:number;kind:"regular"|"next-up"|"next-down";targetIndex:number|null};
type EventLabel={id:string;left:number;top:number;position:"above"|"below";tone:"long"|"short"|"tp"|"cashflow"|"cluster";title:string;value:string;glyph?:string;multiplier?:string;compact?:boolean;eventCount?:number;anchorLeft?:number;anchorTop?:number};
type AdvisorSeats={longSlots:number|null;shortSlots:number|null;activeLong:number|null;activeShort:number|null;settings:Record<string,unknown>;zoneSoldiers:Record<string,unknown>};

const EMPTY=normalizePortfolioKoersPayload({}) as Payload;
const EMPTY_ADVISOR:AdvisorSeats={longSlots:null,shortSlots:null,activeLong:null,activeShort:null,settings:{},zoneSoldiers:{}};
const ZONE_ADVISOR_REFERENCE="file_00000000d9b081f59f77ecf35043ec32";
const PRICE_AXIS_WIDTH=48;
const TIMEFRAME_VIEW:Record<string,{visibleBars:number;barSpacing:number;rightOffset:number}>={
  "1m":{visibleBars:24,barSpacing:7.0,rightOffset:1.2},
  "5m":{visibleBars:20,barSpacing:7.8,rightOffset:1.2},
  "15m":{visibleBars:16,barSpacing:9.0,rightOffset:1.4},
  "1u":{visibleBars:16,barSpacing:9.6,rightOffset:1.5},
  "4u":{visibleBars:14,barSpacing:10.8,rightOffset:1.7},
  "24u":{visibleBars:12,barSpacing:12.0,rightOffset:1.9},
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
  const primaryReport=record(strategy2.multiBb);
  const report=Object.keys(primaryReport).length?primaryReport:record(strategy2.multiBbReport);
  const zoneSoldiers=record(strategy2.zoneSoldiers);
  const reportZoneSoldiers=record(report.zoneSoldiers);
  return {
    longSlots:integerOrNull(settings.longSlots),
    shortSlots:integerOrNull(settings.shortSlots),
    activeLong:integerOrNull(report.activeLong),
    activeShort:integerOrNull(report.activeShort),
    settings,
    zoneSoldiers:Object.keys(zoneSoldiers).length?zoneSoldiers:reportZoneSoldiers,
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

function markerPresentation(row:Marker) {
  const kind=String(row.kind||"").toLowerCase(),side=String(row.side||"").toUpperCase(),count=Math.max(1,Number(row.count)||1);
  if(kind==="cashflow")return {tone:"cashflow" as const,glyph:"↕",multiplier:count>1?`×${count}`:"",title:String(row.cashflowType||"Transfer").replaceAll("_"," "),value:""};
  if(kind==="entry")return {tone:(side==="SHORT"?"short":"long") as "short"|"long",glyph:"⚔",multiplier:`×${count}`,title:side==="SHORT"?"SHORT":"LONG",value:""};
  return {tone:"tp" as const,glyph:"💰",multiplier:count>1?`TP ×${count}`:"TP",title:"Take Profit",value:""};
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
    const role=roles.length===1?` · ${roles[0]==="EXPOSURE_BALANCER"?"exposure-balancer":roles[0]==="ZONE_BASE"?"basis-soldaat":roles[0].toLowerCase().replaceAll("_","-")}`:"";
    return `${side==="SHORT"?"SHORT":"LONG"}${count>1?` ×${count}`:""} ${compactUsd(row.notionalUsd)}${origin}${role}`.trim();
  }
  return `💰${count>1?` ×${count}`:""} ${compactUsd(row.realizedPnlUsd)}`.trim();
}

export function PortfolioKoersChart({liveEquityText}:{liveEquityText:string}) {
  const { user }=useAuthSession();
  const shellRef=useRef<HTMLElement>(null);
  const canvasRef=useRef<HTMLDivElement>(null);
  const chartRef=useRef<IChartApi|null>(null);
  const candleSeriesRef=useRef<ISeriesApi<any>|null>(null);
  const bbRefs=useRef<{upper:ISeriesApi<any>|null;middle:ISeriesApi<any>|null;lower:ISeriesApi<any>|null}>({upper:null,middle:null,lower:null});
  const candleDataRef=useRef<Candle[]>([]);
  const syncOverlaysRef=useRef<()=>void>(()=>{});
  const advisorZoneLadderRef=useRef<any>(null);
  const activeZoneRef=useRef<number|null>(null);
  const liveEquityTextRef=useRef(liveEquityText);
  const [timeframe,setTimeframe]=useState(PORTFOLIO_KOERS_DEFAULT_TIMEFRAME);
  const [payload,setPayload]=useState<Payload>(EMPTY);
  const [browserCandles,setBrowserCandles]=useState<Candle[]>([]);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(true);
  const [zoneLayout,setZoneLayout]=useState<ZoneLayout[]>([]);
  const [zoneBoundaries,setZoneBoundaries]=useState<ZoneBoundaryLayout[]>([]);
  const [eventLabels,setEventLabels]=useState<EventLabel[]>([]);
  const [hover,setHover]=useState<{candle:Candle;markers:Marker[]}|null>(null);
  const [liveEquity,setLiveEquity]=useState<number|null>(null);
  const [advisorEnabled,setAdvisorEnabled]=useState(false);
  const [advisorSeats,setAdvisorSeats]=useState<AdvisorSeats>(EMPTY_ADVISOR);
  const [advisorZones,setAdvisorZones]=useState<Zone[]>([]);
  const [advisorTimeline,setAdvisorTimeline]=useState<any>(null);
  const [advisorMessage,setAdvisorMessage]=useState("");
  liveEquityTextRef.current=liveEquityText;

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

  const loadAdvisor=useCallback(async()=>{
    try{
      const release=record(await authenticatedRequest("/api/releases/me",{cache:"no-store"}));
      const features=record(release.features);
      const zoneFeature=record(features.zone_soldiers);
      const ownerStrategyAccess=String(release.channel||"").toUpperCase()==="BETA"&&zoneFeature.enabled===true;
      setAdvisorEnabled(ownerStrategyAccess);
      if(ownerStrategyAccess){
        const account=await authenticatedRequest("/api/exchanges/aster",{cache:"no-store"});
        setAdvisorSeats(advisorSeatsFromPayload(account));
      }else{
        setAdvisorSeats(EMPTY_ADVISOR);
      }
    }catch{
      setAdvisorEnabled(false);
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
  },[]);

  useEffect(()=>{
    void loadAdvisor();
    const timer=window.setInterval(()=>{if(document.visibilityState==="visible")void loadAdvisor()},45_000);
    return()=>window.clearInterval(timer);
  },[loadAdvisor]);

  const load=useCallback(async()=>{
    try{
      const response=await authenticatedRequest(`/api/exchanges/aster/portfolio-chart?timeframe=${encodeURIComponent(timeframe)}&limit=320`,{cache:"no-store"});
      const normalized=normalizePortfolioKoersPayload(response) as Payload;
      setPayload(normalized);
      setError("");
    }catch(reason){
      setError(reason instanceof Error?reason.message:"Portfolio Koers kon niet worden geladen.");
    }finally{setLoading(false)}
  },[timeframe]);

  useEffect(()=>{
    setLoading(true);
    void load();
    const timer=window.setInterval(()=>{if(document.visibilityState==="visible")void load()},45_000);
    const visible=()=>{if(document.visibilityState==="visible"){loadBrowserHistory();void load()}};
    document.addEventListener("visibilitychange",visible);
    return()=>{window.clearInterval(timer);document.removeEventListener("visibilitychange",visible)};
  },[load,loadBrowserHistory]);

  useEffect(()=>{
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
      candleSeriesRef.current.update({time:candle.time as UTCTimestamp,open:candle.open,high:candle.high,low:candle.low,close:candle.close});
      const bb=bollinger20x2(next);
      bbRefs.current.upper?.setData(bb.upper.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
      bbRefs.current.middle?.setData(bb.middle.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
      bbRefs.current.lower?.setData(bb.lower.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
      syncOverlaysRef.current();
      if(previousTime===null||candle.time>previousTime){
        setHover(null);
        requestAnimationFrame(()=>{try{chartRef.current?.timeScale().scrollToRealTime()}catch{/* disposed */}});
      }
    }catch{/* the next confirmed payload rebuilds a stale chart safely */}
  },[liveEquityText,timeframe]);

  const baseCandles=useMemo(()=>mergePortfolioKoersCandles(browserCandles,payload.candles,320) as Candle[],[browserCandles,payload.candles]);
  const timelineCandles=useMemo(()=>liveEquity?mergeRealtimeEquitySample(baseCandles,liveEquity,Date.now(),timeframe) as Candle[]:baseCandles,[baseCandles,liveEquity,timeframe]);
  const chartTimeline=useMemo(()=>portfolioKoersTimelineHealth(timelineCandles,timeframe,Date.now(),1),[timelineCandles,timeframe]);
  const visibleTimelineStart=timelineCandles[Math.max(0,timelineCandles.length-((TIMEFRAME_VIEW[timeframe]||TIMEFRAME_VIEW["15m"]).visibleBars+3))]?.time??0;
  const recentChartGap=chartTimeline.gaps?.filter((gap:any)=>gap.beforeTime>=visibleTimelineStart).at(-1)??null;
  const currentZonePrice=liveEquity??payload.currentEquity??baseCandles.at(-1)?.close??null;
  const confirmedActiveZone=useMemo(()=>portfolioZoneForPrice(payload.zones,currentZonePrice),[payload.zones,currentZonePrice]);
  const advisorZoneSource=useMemo(()=>advisorTimeline?.safeForAdvisor===true&&advisorZones.length?advisorZones:payload.zones,[advisorTimeline?.safeForAdvisor,advisorZones,payload.zones]);
  const advisorZoneLadder=useMemo(()=>advisorZoneSource.length?derivePortfolioZoneLadder(advisorZoneSource):null,[advisorZoneSource]);
  const zoneContext=useMemo(()=>portfolioZoneContextFromLadder(advisorZoneLadder,currentZonePrice),[advisorZoneLadder,currentZonePrice]);
  const zoneSoldierReport=advisorSeats.zoneSoldiers;
  const zoneSoldierEnabled=advisorEnabled&&zoneSoldierReport.enabled===true;
  const zoneSoldierLifecycle=String(zoneSoldierReport.lifecycle||"OFF").toUpperCase();
  const zoneSoldierActiveZone=signedIntegerOrNull(zoneSoldierReport.activeZone);
  const activeZone=zoneSoldierEnabled&&zoneSoldierActiveZone!==null?zoneSoldierActiveZone:zoneContext?.activeIndex??confirmedActiveZone;
  advisorZoneLadderRef.current=advisorZoneLadder;
  activeZoneRef.current=activeZone;

  useEffect(()=>{syncOverlaysRef.current()},[advisorZoneLadder,activeZone]);

  useEffect(()=>{
    const container=canvasRef.current;
    const observedEquity=parsePortfolioEquityText(liveEquityTextRef.current);
    const candles=(observedEquity?mergeRealtimeEquitySample(baseCandles,observedEquity,Date.now(),timeframe):baseCandles) as Candle[];
    if(!container||!candles.length){candleDataRef.current=[];setZoneLayout([]);setZoneBoundaries([]);setEventLabels([]);return}
    candleDataRef.current=candles.map((row)=>({...row}));
    const view=TIMEFRAME_VIEW[timeframe]||TIMEFRAME_VIEW["15m"];
    const initialFocusPrice=observedEquity??payload.currentEquity??candles.at(-1)?.close??null;
    const initialFocusContext=portfolioZoneContextFromLadder(advisorZoneLadderRef.current,initialFocusPrice);
    const fallbackFocusIndex=portfolioZoneForPrice(payload.zones,initialFocusPrice);
    const fallbackFocusZone=fallbackFocusIndex===null?null:payload.zones.find((zone)=>zone.index===fallbackFocusIndex)??null;
    const focusLower=initialFocusContext?.lowerBoundary??fallbackFocusZone?.lower??null;
    const focusUpper=initialFocusContext?.upperBoundary??fallbackFocusZone?.upper??null;
    const focusVisibleBars=portfolioKoersFocusBars(candles,view.visibleBars,initialFocusPrice,focusLower,focusUpper);
    const chart=createChart(container,{
      width:Math.max(1,container.clientWidth),height:Math.max(220,container.clientHeight),
      layout:{background:{type:ColorType.Solid,color:"#03131b"},textColor:"#9fb0ba",fontSize:10,attributionLogo:false} as any,
      grid:{vertLines:{color:"rgba(75,133,160,.035)"},horzLines:{color:"rgba(75,133,160,.045)"}},
      crosshair:{mode:CrosshairMode.MagnetOHLC,vertLine:{color:"rgba(106,198,255,.48)",labelBackgroundColor:"#17394a"},horzLine:{color:"rgba(106,198,255,.48)",labelBackgroundColor:"#17394a"}},
      rightPriceScale:{borderColor:"rgba(85,160,190,.22)",minimumWidth:PRICE_AXIS_WIDTH,scaleMargins:{top:.12,bottom:.12}},
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
    const series=chart.addSeries(CandlestickSeries,{upColor:"#17e6a0",downColor:"#ff5a66",wickUpColor:"#17e6a0",wickDownColor:"#ff6a74",borderVisible:false,priceLineColor:"#d9b34a",priceLineWidth:1,lastValueVisible:true});
    candleSeriesRef.current=series;
    series.setData(candles.map((row)=>({time:row.time as UTCTimestamp,open:row.open,high:row.high,low:row.low,close:row.close})));

    const bb=bollinger20x2(candles);
    const upper=chart.addSeries(LineSeries,{color:"#1298ff",lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    const middle=chart.addSeries(LineSeries,{color:"rgba(226,235,239,.78)",lineWidth:1,lineStyle:2 as any,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    const lower=chart.addSeries(LineSeries,{color:"#f02e49",lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    bbRefs.current={upper,middle,lower};
    upper.setData(bb.upper.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
    middle.setData(bb.middle.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
    lower.setData(bb.lower.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));

    if(Number.isFinite(Number(initialFocusPrice))&&Number.isFinite(Number(focusLower))&&Number.isFinite(Number(focusUpper))&&Number(focusUpper)>Number(focusLower)){
      const focusSpan=Math.max(Number(focusUpper)-Number(focusLower),Number(initialFocusPrice)*0.006);
      const focusPadding=Math.max(focusSpan*0.32,Number(initialFocusPrice)*0.0025);
      const guideLow=Math.max(Number.EPSILON,Number(focusLower)-focusPadding);
      const guideHigh=Number(focusUpper)+focusPadding;
      const guideFrom=candles[Math.max(0,candles.length-focusVisibleBars)]?.time??candles[0]?.time;
      const guideTo=candles.at(-1)?.time;
      if(guideFrom&&guideTo){
        const lowGuide=chart.addSeries(LineSeries,{color:"rgba(0,0,0,0)",lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
        const highGuide=chart.addSeries(LineSeries,{color:"rgba(0,0,0,0)",lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
        lowGuide.setData([{time:guideFrom as UTCTimestamp,value:guideLow},{time:guideTo as UTCTimestamp,value:guideLow}]);
        highGuide.setData([{time:guideFrom as UTCTimestamp,value:guideHigh},{time:guideTo as UTCTimestamp,value:guideHigh}]);
      }
    }

    if(payload.cycleStartEquity&&payload.cycleStartEquity>0){
      series.createPriceLine({price:payload.cycleStartEquity,color:"rgba(229,190,75,.72)",lineWidth:1,lineStyle:2,axisLabelVisible:true,title:"CYCLE"});
    }

    const candleByTime=new Map(candles.map((row)=>[row.time,row]));
    const markerRows=payload.markers.filter((row)=>candleByTime.has(row.time));
    const bbUpperByTime=new Map(bb.upper.map((row:any)=>[Number(row.time),Number(row.value)]));
    const bbMiddleByTime=new Map(bb.middle.map((row:any)=>[Number(row.time),Number(row.value)]));
    const bbLowerByTime=new Map(bb.lower.map((row:any)=>[Number(row.time),Number(row.value)]));

    const syncOverlays=()=>{
      if(candleSeriesRef.current!==series||!container.isConnected)return;
      const height=Math.max(1,container.clientHeight),width=Math.max(1,container.clientWidth);
      const zoneLadder=advisorZoneLadderRef.current;
      const liveActiveZone=activeZoneRef.current;
      if(zoneLadder?.zones?.length){
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

      const candidates:any[]=[];
      for(let index=0;index<markerRows.length;index+=1){
        const row=markerRows[index],candle=candleByTime.get(row.time);
        if(!candle)continue;
        const visual=markerVisual(row);
        const x=chart.timeScale().timeToCoordinate(row.time as UTCTimestamp);
        const price=visual.position==="belowBar"?candle.low:candle.high;
        const y=series.priceToCoordinate(price);
        if(x===null||y===null)continue;
        const upperValue=bbUpperByTime.get(row.time),middleValue=bbMiddleByTime.get(row.time),lowerValue=bbLowerByTime.get(row.time);
        const upperY=Number.isFinite(upperValue)?series.priceToCoordinate(upperValue as number):null;
        const lowerY=Number.isFinite(lowerValue)?series.priceToCoordinate(lowerValue as number):null;
        const kind=String(row.kind||"").toLowerCase(),side=String(row.side||"").toUpperCase();
        const position=kind==="entry"
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
          anchorLeft:Number(x),anchorTop:Number(y),
          bandTop:upperY===null?null:Number(upperY),bandBottom:lowerY===null?null:Number(lowerY),
          width:copy.multiplier?48:42,height:44,
        });
      }
      const markerLayout=layoutPortfolioKoersMarkers(candidates,{width,height},{maxFull:3,maxCompact:2,priceAxisWidth:PRICE_AXIS_WIDTH});
      setEventLabels(markerLayout.all as EventLabel[]);
    };
    syncOverlaysRef.current=()=>requestAnimationFrame(syncOverlays);
    const onCrosshair=(param:any)=>{
      if(!param.time){setHover(null);return}
      const time=Number(param.time),candle=candleDataRef.current.find((row)=>row.time===time);
      if(!candle){setHover(null);return}
      setHover({candle,markers:payload.markers.filter((row)=>row.time===time)});
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
      from:Math.max(-.5,candles.length-focusVisibleBars-.5),
      to:candles.length-1+view.rightOffset,
    });
    sync();

    return()=>{
      resize.disconnect();chart.timeScale().unsubscribeVisibleLogicalRangeChange(sync);
      container.removeEventListener("pointermove",sync);container.removeEventListener("touchmove",sync);
      try{chart.unsubscribeCrosshairMove(onCrosshair);chart.remove()}catch{/* disposed */}
      if(chartRef.current===chart)chartRef.current=null;
      candleSeriesRef.current=null;bbRefs.current={upper:null,middle:null,lower:null};syncOverlaysRef.current=()=>{};setZoneBoundaries([]);setEventLabels([]);
    };
  },[baseCandles,payload.markers,payload.zones,payload.cycleStartEquity,timeframe]);

  const fullscreen=async()=>{
    if(!shellRef.current)return;
    try{if(document.fullscreenElement)await document.exitFullscreen();else await shellRef.current.requestFullscreen()}catch{/* unsupported */}
  };



  const latest=liveEquity??payload.currentEquity??baseCandles.at(-1)?.close??null;
  const zoneFormation=record(zoneSoldierReport.zoneFormation);
  const zoneCurrent=record(zoneSoldierReport.currentZone);
  const zoneOld=record(zoneSoldierReport.oldZonesOpen);
  const zoneExposure=record(zoneSoldierReport.exposure);
  const zoneBalancer=record(zoneSoldierReport.balancer);
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
  const zoneEntriesSafe=zoneSoldierReport.safeForNewEntries===true;
  const drainingOpenCount=integerOrNull(zoneSoldierReport.drainingOpenCount)??0;
  const advisorTimelineReady=advisorTimeline?.safeForAdvisor===true;
  const timelineGap=advisorTimeline?.gaps?.at(-1)??null;
  const timelineWait=advisorTimeline
    ? timelineGap
      ? `Historiegat ${clockTime(timelineGap.fromTime)}–${clockTime(timelineGap.toTime)} · zone-entrys worden geblokkeerd zolang de Zone-Soldatenstrategie actief is.`
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
  const biasLabel=zoneSoldierEnabled?(balancerSide?`BALANSER ${balancerSide}`:"ZONE-STURING ACTIEF"):zoneSoldierLifecycle==="DRAINING"?"ZONE DRAINING":"INFORMATIEF";
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
          : "Formatie compleet")
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

  return <section ref={shellRef} className={`portfolio-koers-card portfolio-zone-map ${advisorEnabled?"beta-zone-advisor":""}`} aria-label="Portfolio Koers" data-reference="file_00000000dd24820eaa6e54ec1054904f" data-zone-advisor-reference={advisorEnabled?ZONE_ADVISOR_REFERENCE:undefined}>
    <header className="portfolio-koers-header">
      <div className="portfolio-koers-heading">
        <div className="portfolio-koers-title-line"><h2>Portfolio Koers</h2><span className={payload.live?"portfolio-koers-live is-live":"portfolio-koers-live"}><i/>{payload.live?"Live":"Sync"}</span></div>
        <small>Totale portfolio waarde (USDT)</small><span className="portfolio-koers-context">{timeframe} candles · {timeframe} zones · BB 20,2</span>
      </div>
      <div className="portfolio-koers-toolbar" role="group" aria-label="Portfolio Koers timeframe">
        {PORTFOLIO_KOERS_TIMEFRAMES.map((value)=><button type="button" key={value} className={timeframe===value?"active":""} onClick={()=>setTimeframe(value)}>{value}</button>)}
      </div>
      <button type="button" className="portfolio-koers-fullscreen" onClick={fullscreen} aria-label="Portfolio Koers fullscreen">↗</button>
    </header>
    <div className="portfolio-koers-stage">
      <div ref={canvasRef} className="portfolio-koers-canvas"/>
      {recentChartGap?<div className="portfolio-koers-gap-warning" role="status">⚠ Historiegat {clockTime(recentChartGap.fromTime)}–{clockTime(recentChartGap.toTime)} · geen koerswaarden verzonnen</div>:null}
      {activeZone!==null?<div className="portfolio-koers-bias neutral" aria-hidden="true"><b>{biasLabel}</b><span>Z{signedZone(activeZone)}{zoneSoldierEnabled&&zoneBaseLong!==null&&zoneBaseShort!==null?` · ${zoneBaseLong}L / ${zoneBaseShort}S`:""}</span></div>:null}
      <div className={`portfolio-koers-zones ${zoneLayout.length?"is-ready":""}`} aria-hidden="true">{zoneLayout.map((zone)=><div key={zone.index} className={`portfolio-koers-zone zone-${zone.tone} ${zoneLevelClass(zone.index)} ${zone.index===activeZone?"active":""}`} style={{top:`${zone.top}px`,height:`${zone.height}px`}}><span>{zone.label}</span></div>)}</div>
      <div className="portfolio-koers-zone-boundaries" aria-hidden="true">{zoneBoundaries.map((boundary,index)=>{const distance=portfolioZoneDistancePercent(boundary.price,currentZonePrice);return <div key={`${boundary.price}-${index}`} className={`portfolio-koers-zone-boundary ${boundary.kind}`} style={{top:`${boundary.top}px`}}>{boundary.kind!=="regular"?<span title={`Exacte grens ${levelUsd(boundary.price)}`}>{boundary.kind==="next-up"?"↑":"↓"} Z{signedZone(boundary.targetIndex)} · {percent2(distance)}</span>:null}</div>})}</div>
      <div className="portfolio-koers-event-layer" aria-hidden="true">{eventLabels.map((label)=><div key={label.id} className="portfolio-koers-event-group">{!label.compact&&connectorStyle(label)?<i className={`portfolio-koers-connector ${label.tone}`} style={connectorStyle(label)}/>:null}{!label.compact&&Number.isFinite(label.anchorLeft)&&Number.isFinite(label.anchorTop)?<i className={`portfolio-koers-anchor ${label.tone}`} style={{left:`${label.anchorLeft}px`,top:`${label.anchorTop}px`}}/>:null}<div className={`portfolio-koers-event ${label.tone} ${label.position} ${label.compact?"compact":""}`} style={{left:`${label.left}px`,top:`${label.top}px`}}>{label.compact?<b>{label.multiplier||`+${label.eventCount}`}</b>:<><span className="portfolio-koers-event-icon"><b className="portfolio-koers-event-glyph">{label.glyph}</b></span>{label.multiplier?<small className="portfolio-koers-event-badge">{label.multiplier}</small>:null}</>}</div></div>)}</div>
      {loading&&!baseCandles.length?<div className="portfolio-koers-state"><i/>Portfoliohistorie laden…</div>:null}
      {!loading&&!baseCandles.length&&!error?<div className="portfolio-koers-state"><strong>Historie wordt opgebouwd</strong><span>Nieuwe candles gebruiken bevestigde Aster-equity; bestaande bevestigde browserhistorie wordt veilig hergebruikt als die beschikbaar is.</span></div>:null}
      {error&&!baseCandles.length?<div className="portfolio-koers-state error"><strong>Portfolio Koers tijdelijk niet beschikbaar</strong><span>{error}</span><button type="button" onClick={()=>void load()}>Opnieuw proberen</button></div>:null}
      {hover?<div className="portfolio-koers-tooltip"><span>{localTime(hover.candle.time)}</span><b>O {compactUsd(hover.candle.open)}</b><b>H {compactUsd(hover.candle.high)}</b><b>L {compactUsd(hover.candle.low)}</b><b>C {compactUsd(hover.candle.close)}</b>{hover.markers.map((row,index)=><em key={`${row.kind}-${row.side}-${index}`}>{markerDetail(row)}</em>)}</div>:null}
    </div>
    {(activeZone!==null||zoneSoldierEnabled||zoneSoldierLifecycle==="DRAINING")?<section className={`portfolio-strategy-cockpit ${strategyTone}`} data-reference={ZONE_ADVISOR_REFERENCE} aria-live="polite">
      <header className="portfolio-strategy-head">
        <span className="portfolio-strategy-mark" aria-hidden="true">{zoneSoldierEnabled?"⌖":"◎"}</span>
        <div className="portfolio-strategy-heading">
          <small>{zoneSoldierEnabled?"ZONE-SOLDATEN":zoneSoldierLifecycle==="DRAINING"?"ZONE DRAINING":"PORTFOLIOZONE"}</small>
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
          <div><small>FORMATIE</small><strong>{zoneSoldierEnabled?`${zoneOpenLong??"—"}L · ${zoneOpenShort??"—"}S`:"—"}</strong><em>{zoneSoldierEnabled?`doel ${zoneBaseLong??"—"}L · ${zoneBaseShort??"—"}S · vrij ${zoneFreeLong??"—"}L/${zoneFreeShort??"—"}S`:"alleen informatief"}</em></div>
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
        {zoneSoldierEnabled?<><span><b>{zoneTotalActive??"—"}</b> soldaten · <b className="long">{zoneTotalLong??"—"}L</b> / <b className="short">{zoneTotalShort??"—"}S</b></span>{(oldOpenTotal??0)>0?<span>oude zones <b>{oldOpenTotal}</b></span>:null}</>:<span>{zoneBasisSummary}</span>}
        {advisorMessage?<em>{advisorMessage}</em>:null}
      </footer>

      <span className="portfolio-koers-cockpit-sr">
        {zoneSoldierEnabled?`ZONE-STURING ACTIEF. ZONEFORMATIE ${zoneBaseLong??"—"}L ${zoneBaseShort??"—"}S. IN ZONE OPEN ${zoneOpenLong??"—"}L ${zoneOpenShort??"—"}S. IN ZONE VRIJ ${zoneFreeLong??"—"}L ${zoneFreeShort??"—"}S. Oude zones nog open: ${oldOpenTotal??"—"}, ${oldOpenLong??"—"}L, ${oldOpenShort??"—"}S, ${legacyUnassignedOpen} legacy. Inzet zone: ${Number.isFinite(zoneEntryMultiplier)?"×"+zoneEntryMultiplier.toFixed(2):"—"}; ${Number.isFinite(zoneEntryGrowthPercent)?"+"+zoneEntryGrowthPercent.toFixed(1)+"% per zoneafstand":""}; ${Number.isFinite(zoneEntryActiveUsd)?levelUsd(zoneEntryActiveUsd):"—"}. Exposure: L ${Number.isFinite(longExposureUsd)?levelUsd(longExposureUsd):"—"}, S ${Number.isFinite(shortExposureUsd)?levelUsd(shortExposureUsd):"—"}, netto ${exposureValue}. ${balancerMessage}`:zoneSoldierLifecycle==="DRAINING"?"ZONE DRAINING · geen nieuwe zone-entrys. "+zoneBasisSummary:"INFORMATIEF. "+zoneBasisSummary}
      </span>
    </section>:null}
    <span className="portfolio-koers-current-sr">Actuele portfolio waarde {latest===null?"onbekend":compactUsd(latest)}</span>
  </section>;
}
