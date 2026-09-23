"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CandlestickSeries, ColorType, CrosshairMode, LineSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { authenticatedRequest } from "@/lib/cloud-client";
import { useAuthSession } from "@/components/auth-provider";
import { sanitizePortfolioEquityRows } from "@/lib/portfolio-equity-history";
import { PORTFOLIO_KOERS_DEFAULT_TIMEFRAME, PORTFOLIO_KOERS_TIMEFRAMES, aggregatePortfolioEquityHistory, bollinger20x2, markerVisual, mergePortfolioKoersCandles, mergeRealtimeEquitySample, normalizePortfolioKoersPayload, parsePortfolioEquityText, portfolioZoneForPrice } from "@/lib/portfolio-koers-chart.mjs";
import { eventPriority, layoutPortfolioKoersMarkers, layoutPortfolioKoersZoneRegions } from "@/lib/portfolio-koers-marker-layout.mjs";
import { derivePortfolioZoneInstruction, derivePortfolioZoneLadder, portfolioZoneContextFromLadder, portfolioZoneFromLadder } from "@/lib/portfolio-zone-advisor.mjs";

type Candle={time:number;atMs:number;open:number;high:number;low:number;close:number;samples:number;sourceAtMs:number};
type Zone={index:number;label:string;center:number;lower:number;upper:number;touches:number;atr:number;source:string};
type Marker={time:number;atMs:number;kind?:string;side?:string;label?:string;count?:number;notionalUsd?:number;realizedPnlUsd?:number;amountUsd?:number;cashflowType?:string};
type Payload={timeframe:string;candles:Candle[];markers:Marker[];zones:Zone[];currentZone:number|null;cycleStartEquity:number|null;currentEquity:number|null;snapshotAtMs:number|null;live:boolean;persistent:boolean;externalCashflowsSeparated:boolean;readOnly:boolean;ordersSent:number;source:string};
type ZoneLayout={index:number;label:string;top:number;height:number;tone:"red"|"amber"|"green"|"blue"};
type ZoneBoundaryLayout={price:number;top:number;kind:"regular"|"next-up"|"next-down";targetIndex:number|null};
type EventLabel={id:string;left:number;top:number;position:"above"|"below";tone:"long"|"short"|"tp"|"cashflow"|"cluster";title:string;value:string;glyph?:string;multiplier?:string;compact?:boolean;eventCount?:number;anchorLeft?:number;anchorTop?:number};
type AdvisorSeats={longSlots:number|null;shortSlots:number|null;activeLong:number|null;activeShort:number|null;settings:Record<string,unknown>};

const EMPTY=normalizePortfolioKoersPayload({}) as Payload;
const EMPTY_ADVISOR:AdvisorSeats={longSlots:null,shortSlots:null,activeLong:null,activeShort:null,settings:{}};
const ZONE_ADVISOR_REFERENCE="file_00000000d9b081f59f77ecf35043ec32";
const PRICE_AXIS_WIDTH=48;
const TIMEFRAME_VIEW:Record<string,{visibleBars:number;barSpacing:number;rightOffset:number}>={
  "1m":{visibleBars:72,barSpacing:5.2,rightOffset:1.2},
  "5m":{visibleBars:60,barSpacing:6.1,rightOffset:1.2},
  "15m":{visibleBars:52,barSpacing:7.2,rightOffset:1.4},
  "1u":{visibleBars:48,barSpacing:8.4,rightOffset:1.5},
  "4u":{visibleBars:42,barSpacing:10.4,rightOffset:1.7},
  "24u":{visibleBars:34,barSpacing:13.2,rightOffset:1.9},
};
const localTime=(seconds:number)=>new Date(seconds*1000).toLocaleString("nl-NL",{timeZone:"Europe/Amsterdam",day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit",hourCycle:"h23"});
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
  return {
    longSlots:integerOrNull(settings.longSlots),
    shortSlots:integerOrNull(settings.shortSlots),
    activeLong:integerOrNull(report.activeLong),
    activeShort:integerOrNull(report.activeShort),
    settings,
  };
}
const signedZone=(value:number|null)=>value===null?"—":value===0?"0":value>0?`+${value}`:`${value}`;
const zoneLevelClass=(value:number)=>value<0?`level-n${Math.abs(value)}`:value>0?`level-p${value}`:"level-0";
const levelUsd=(value:number|null|undefined)=>Number.isFinite(Number(value))
  ? `${new Intl.NumberFormat("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(value))}`
  : "—";

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
  if(kind==="entry")return `${side==="SHORT"?"SHORT":"LONG"}${count>1?` ×${count}`:""} ${compactUsd(row.notionalUsd)}`.trim();
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
  const [advisorBusy,setAdvisorBusy]=useState(false);
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
      const betaFeature=record(features.bot_configurator_v2);
      const enabled=String(release.channel||"").toUpperCase()==="BETA"&&betaFeature.enabled===true;
      setAdvisorEnabled(enabled);
      if(!enabled){setAdvisorSeats(EMPTY_ADVISOR);setAdvisorZones([]);setAdvisorMessage("");return}
      const account=await authenticatedRequest("/api/exchanges/aster",{cache:"no-store"});
      setAdvisorSeats(advisorSeatsFromPayload(account));
      try{
        const canonical=normalizePortfolioKoersPayload(await authenticatedRequest("/api/exchanges/aster/portfolio-chart?timeframe=15m&limit=320",{cache:"no-store"})) as Payload;
        setAdvisorZones(canonical.zones);
      }catch{
        setAdvisorZones([]);
      }
    }catch(reason){
      setAdvisorEnabled(false);
      setAdvisorSeats(EMPTY_ADVISOR);
      setAdvisorZones([]);
      setAdvisorMessage(reason instanceof Error?reason.message:"Koersinstructie kon niet worden geladen.");
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
    }catch{/* the next confirmed payload rebuilds a stale chart safely */}
  },[liveEquityText,timeframe]);

  const baseCandles=useMemo(()=>mergePortfolioKoersCandles(browserCandles,payload.candles,320) as Candle[],[browserCandles,payload.candles]);
  const currentZonePrice=liveEquity??payload.currentEquity??baseCandles.at(-1)?.close??null;
  const confirmedActiveZone=useMemo(()=>portfolioZoneForPrice(payload.zones,currentZonePrice),[payload.zones,currentZonePrice]);
  const advisorZoneSource=useMemo(()=>advisorEnabled&&advisorZones.length?advisorZones:payload.zones,[advisorEnabled,advisorZones,payload.zones]);
  const advisorZoneLadder=useMemo(()=>advisorEnabled?derivePortfolioZoneLadder(advisorZoneSource):null,[advisorEnabled,advisorZoneSource]);
  const zoneContext=useMemo(()=>advisorEnabled?portfolioZoneContextFromLadder(advisorZoneLadder,currentZonePrice):null,[advisorEnabled,advisorZoneLadder,currentZonePrice]);
  const activeZone=advisorEnabled?zoneContext?.activeIndex??null:confirmedActiveZone;
  const advisorInstruction=useMemo(()=>advisorEnabled?derivePortfolioZoneInstruction({
    zoneIndex:activeZone,
    longSlots:advisorSeats.longSlots,
    shortSlots:advisorSeats.shortSlots,
    activeLong:advisorSeats.activeLong,
    activeShort:advisorSeats.activeShort,
  }):null,[advisorEnabled,activeZone,advisorSeats.longSlots,advisorSeats.shortSlots,advisorSeats.activeLong,advisorSeats.activeShort]);

  useEffect(()=>{
    const container=canvasRef.current;
    const observedEquity=parsePortfolioEquityText(liveEquityTextRef.current);
    const candles=(observedEquity?mergeRealtimeEquitySample(baseCandles,observedEquity,Date.now(),timeframe):baseCandles) as Candle[];
    if(!container||!candles.length){candleDataRef.current=[];setZoneLayout([]);setZoneBoundaries([]);setEventLabels([]);return}
    candleDataRef.current=candles.map((row)=>({...row}));
    const view=TIMEFRAME_VIEW[timeframe]||TIMEFRAME_VIEW["15m"];
    const chart=createChart(container,{
      width:Math.max(1,container.clientWidth),height:Math.max(220,container.clientHeight),
      layout:{background:{type:ColorType.Solid,color:"#03131b"},textColor:"#b8c8d2",attributionLogo:false} as any,
      grid:{vertLines:{color:advisorEnabled?"rgba(75,133,160,.025)":"rgba(75,133,160,.07)"},horzLines:{color:advisorEnabled?"rgba(75,133,160,.032)":"rgba(75,133,160,.09)"}},
      crosshair:{mode:CrosshairMode.MagnetOHLC,vertLine:{color:"rgba(106,198,255,.48)",labelBackgroundColor:"#17394a"},horzLine:{color:"rgba(106,198,255,.48)",labelBackgroundColor:"#17394a"}},
      rightPriceScale:{borderColor:"rgba(85,160,190,.28)",minimumWidth:PRICE_AXIS_WIDTH,scaleMargins:{top:.08,bottom:.08}},
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
      if(advisorEnabled&&advisorZoneLadder?.zones?.length){
        const zones=advisorZoneLadder.zones.map((zone:any)=>{
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
        const boundaries=(advisorZoneLadder.zones as any[]).slice(0,-1).map((zone:any)=>{
          const price=Number(zone.upper);
          const coordinate=Number.isFinite(price)?series.priceToCoordinate(price):null;
          if(coordinate===null)return null;
          const top=Number(coordinate);
          if(top<0||top>height)return null;
          const kind:ZoneBoundaryLayout["kind"]=activeZone!==null&&zone.index===activeZone
            ? "next-up"
            : activeZone!==null&&zone.index===activeZone-1
              ? "next-down"
              : "regular";
          return {price,top,kind,targetIndex:kind==="next-up"&&activeZone!==null?activeZone+1:kind==="next-down"&&activeZone!==null?activeZone-1:null};
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
    const visibleBars=Math.min(candles.length,view.visibleBars);
    chart.timeScale().setVisibleLogicalRange({
      from:Math.max(-.5,candles.length-visibleBars-.5),
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
  },[baseCandles,payload.markers,payload.zones,payload.cycleStartEquity,timeframe,advisorEnabled,advisorZoneLadder,activeZone]);

  const fullscreen=async()=>{
    if(!shellRef.current)return;
    try{if(document.fullscreenElement)await document.exitFullscreen();else await shellRef.current.requestFullscreen()}catch{/* unsupported */}
  };

  const applySoldierInstruction=async()=>{
    if(!advisorEnabled||advisorBusy||!advisorInstruction)return;
    if(!["ADD","PARTIAL_ADD","REMOVE"].includes(String(advisorInstruction.status)))return;
    setAdvisorBusy(true);setAdvisorMessage("");
    try{
      const release=record(await authenticatedRequest("/api/releases/me",{cache:"no-store"}));
      const betaFeature=record(record(release.features).bot_configurator_v2);
      if(String(release.channel||"").toUpperCase()!=="BETA"||betaFeature.enabled!==true)throw new Error("Deze koersinstructie is niet actief voor dit account.");
      const account=await authenticatedRequest("/api/exchanges/aster",{cache:"no-store"});
      const fresh=advisorSeatsFromPayload(account);
      if(!Object.keys(fresh.settings).length)throw new Error("Actuele botinstellingen ontbreken; er is niets gewijzigd.");
      const canonical=normalizePortfolioKoersPayload(await authenticatedRequest("/api/exchanges/aster/portfolio-chart?timeframe=15m&limit=320",{cache:"no-store"})) as Payload;
      const freshLadder=derivePortfolioZoneLadder(canonical.zones);
      const freshPrice=parsePortfolioEquityText(liveEquityTextRef.current)??canonical.currentEquity;
      const freshZone=portfolioZoneFromLadder(freshLadder,freshPrice);
      if(freshZone===null)throw new Error("Actuele prijszone kon niet veilig worden bevestigd; er is niets gewijzigd.");
      const instruction=derivePortfolioZoneInstruction({
        zoneIndex:freshZone,
        longSlots:fresh.longSlots,
        shortSlots:fresh.shortSlots,
        activeLong:fresh.activeLong,
        activeShort:fresh.activeShort,
      });
      if(!["ADD","PARTIAL_ADD","REMOVE"].includes(String(instruction.status)))throw new Error("De live situatie is veranderd; de koersinstructie is opnieuw berekend.");
      const targetLong=Math.max(Number(instruction.activeLong)||0,Number(instruction.targetLongSlots)||0);
      const targetShort=Math.max(Number(instruction.activeShort)||0,Number(instruction.targetShortSlots)||0);
      if(targetLong+targetShort>100)throw new Error("Maximaal 100 totale stoelen toegestaan.");
      const nextSettings={...fresh.settings,longSlots:targetLong,shortSlots:targetShort,maximumPositions:targetLong+targetShort};
      const result=await authenticatedRequest("/api/exchanges/aster/strategy2/settings",{method:"PUT",body:JSON.stringify({settings:nextSettings})});
      const confirmed=advisorSeatsFromPayload(result);
      if(confirmed.longSlots!==targetLong||confirmed.shortSlots!==targetShort){
        throw new Error("Server heeft de nieuwe LONG/SHORT-stoelverdeling niet bevestigd.");
      }
      setAdvisorSeats(confirmed);
      const verb=String(instruction.status)==="REMOVE"?"naar huis geroepen":"gestuurd";
      setAdvisorMessage(`${instruction.amount} ${instruction.side}-soldaten ${verb} · nu ${targetLong}L / ${targetShort}S.`);
      await loadAdvisor();
    }catch(reason){
      setAdvisorMessage(reason instanceof Error?reason.message:"Soldaten aanpassen is mislukt.");
      await loadAdvisor();
    }finally{setAdvisorBusy(false)}
  };

  const latest=liveEquity??payload.currentEquity??baseCandles.at(-1)?.close??null;
  const instructionStatus=String(advisorInstruction?.status||"UNAVAILABLE");
  const instructionSide=String(advisorInstruction?.side||"");
  const instructionAmount=Math.max(0,Number(advisorInstruction?.amount)||0);
  const instructionActionable=["ADD","PARTIAL_ADD","REMOVE"].includes(instructionStatus);
  const instructionTitle=instructionStatus==="ADD"||instructionStatus==="PARTIAL_ADD"
    ? `Stuur ${instructionAmount} extra ${instructionSide}-soldaten`
    : instructionStatus==="REMOVE"
      ? `Roep ${instructionAmount} ${instructionSide}-soldaten naar huis`
      : instructionStatus==="BLOCKED"
        ? `${instructionAmount} extra ${instructionSide}-soldaten nodig`
        : instructionStatus==="OK"
          ? "Formatie klopt · geen actie nodig"
          : activeZone===null&&advisorSeats.longSlots!==null&&advisorSeats.shortSlots!==null
            ? "Prijszones worden gesynchroniseerd"
            : "Live stoelbezetting wordt geladen";
  const actionLabel=advisorBusy?"OPSLAAN…":instructionStatus==="REMOVE"
    ? `−${instructionAmount} ${instructionSide}`
    : instructionStatus==="ADD"||instructionStatus==="PARTIAL_ADD"
      ? `+${instructionAmount} ${instructionSide}`
      : instructionStatus==="BLOCKED"?"LIMIET 100":activeZone===null?"WACHTEN":"✓ GEREED";
  const biasLabel=activeZone===null?"ZONE":activeZone>0?"SHORT BIAS":activeZone<0?"LONG BIAS":"BALANS";
  const desiredLong=integerOrNull(advisorInstruction?.desiredLongSlots??advisorSeats.longSlots);
  const desiredShort=integerOrNull(advisorInstruction?.desiredShortSlots??advisorSeats.shortSlots);
  const upperTrigger=zoneContext?.upperBoundary??null;
  const lowerTrigger=zoneContext?.lowerBoundary??null;
  const nextUpIndex=zoneContext?.nextUpIndex??null;
  const nextDownIndex=zoneContext?.nextDownIndex??null;
  const instructionReason=String(advisorInstruction?.reason||"");
  const nextTriggerSummary=[
    upperTrigger!==null&&nextUpIndex!==null?`↑ ${levelUsd(upperTrigger)} → Z${signedZone(nextUpIndex)}`:"",
    lowerTrigger!==null&&nextDownIndex!==null?`↓ ${levelUsd(lowerTrigger)} → Z${signedZone(nextDownIndex)}`:"",
  ].filter(Boolean);

  return <section ref={shellRef} className={advisorEnabled?"portfolio-koers-card beta-zone-advisor":"portfolio-koers-card"} aria-label="Portfolio Koers" data-reference="file_00000000dd24820eaa6e54ec1054904f" data-zone-advisor-reference={advisorEnabled?ZONE_ADVISOR_REFERENCE:undefined}>
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
      {advisorEnabled&&advisorInstruction?<div className={`portfolio-koers-bias ${activeZone&&activeZone>0?"short":activeZone&&activeZone<0?"long":"neutral"}`} aria-hidden="true"><b>{biasLabel}</b><span>Z{signedZone(activeZone)} · {Number.isFinite(desiredLong)?desiredLong:"—"}L / {Number.isFinite(desiredShort)?desiredShort:"—"}S</span></div>:null}
      <div className="portfolio-koers-zones" aria-hidden="true">{zoneLayout.map((zone)=><div key={zone.index} className={`portfolio-koers-zone zone-${zone.tone} ${zoneLevelClass(zone.index)} ${zone.index===activeZone?"active":""}`} style={{top:`${zone.top}px`,height:`${zone.height}px`}}><span>{zone.label}</span></div>)}</div>
      {advisorEnabled?<div className="portfolio-koers-zone-boundaries" aria-hidden="true">{zoneBoundaries.map((boundary,index)=><div key={`${boundary.price}-${index}`} className={`portfolio-koers-zone-boundary ${boundary.kind}`} style={{top:`${boundary.top}px`}}>{boundary.kind!=="regular"?<span>{boundary.kind==="next-up"?"VOLGENDE ↑":"VOLGENDE ↓"} {levelUsd(boundary.price)}</span>:null}</div>)}</div>:null}
      <div className="portfolio-koers-event-layer" aria-hidden="true">{eventLabels.map((label)=><div key={label.id} className="portfolio-koers-event-group">{!label.compact&&connectorStyle(label)?<i className={`portfolio-koers-connector ${label.tone}`} style={connectorStyle(label)}/>:null}{!label.compact&&Number.isFinite(label.anchorLeft)&&Number.isFinite(label.anchorTop)?<i className={`portfolio-koers-anchor ${label.tone}`} style={{left:`${label.anchorLeft}px`,top:`${label.anchorTop}px`}}/>:null}<div className={`portfolio-koers-event ${label.tone} ${label.position} ${label.compact?"compact":""}`} style={{left:`${label.left}px`,top:`${label.top}px`}}>{label.compact?<b>{label.multiplier||`+${label.eventCount}`}</b>:<><span className="portfolio-koers-event-icon"><b className="portfolio-koers-event-glyph">{label.glyph}</b></span>{label.multiplier?<small className="portfolio-koers-event-badge">{label.multiplier}</small>:null}</>}</div></div>)}</div>
      {loading&&!baseCandles.length?<div className="portfolio-koers-state"><i/>Portfoliohistorie laden…</div>:null}
      {!loading&&!baseCandles.length&&!error?<div className="portfolio-koers-state"><strong>Historie wordt opgebouwd</strong><span>Nieuwe candles gebruiken bevestigde Aster-equity; bestaande bevestigde browserhistorie wordt veilig hergebruikt als die beschikbaar is.</span></div>:null}
      {error&&!baseCandles.length?<div className="portfolio-koers-state error"><strong>Portfolio Koers tijdelijk niet beschikbaar</strong><span>{error}</span><button type="button" onClick={()=>void load()}>Opnieuw proberen</button></div>:null}
      {hover?<div className="portfolio-koers-tooltip"><span>{localTime(hover.candle.time)}</span><b>O {compactUsd(hover.candle.open)}</b><b>H {compactUsd(hover.candle.high)}</b><b>L {compactUsd(hover.candle.low)}</b><b>C {compactUsd(hover.candle.close)}</b>{hover.markers.map((row,index)=><em key={`${row.kind}-${row.side}-${index}`}>{markerDetail(row)}</em>)}</div>:null}
    </div>
    {advisorEnabled?<div className={`portfolio-koers-instruction ${instructionStatus.toLowerCase()}`} data-reference={ZONE_ADVISOR_REFERENCE}>
      <span className="portfolio-koers-instruction-icon" aria-hidden="true">⌖</span>
      <div className="portfolio-koers-instruction-copy" aria-live="polite">
        <small>KOERSINSTRUCTIE · ZONE {signedZone(activeZone)}</small>
        <strong>{instructionTitle}</strong>
        <span>Gewenst: <b className="long">{Number.isFinite(desiredLong)?desiredLong:"—"}L</b> / <b className="short">{Number.isFinite(desiredShort)?desiredShort:"—"}S</b> · Huidig: <b className="long">{advisorSeats.longSlots??"—"}L</b> / <b className="short">{advisorSeats.shortSlots??"—"}S</b></span>
        {instructionReason?<span className="portfolio-koers-instruction-reason">{instructionReason}</span>:null}
        {nextTriggerSummary.length?<span className="portfolio-koers-next-levels"><i>VOLGENDE LEVEL</i>{nextTriggerSummary.map((item,index)=><b key={index}>{item}</b>)}</span>:null}
        {advisorMessage?<em>{advisorMessage}</em>:null}
      </div>
      <button type="button" className={instructionSide==="LONG"?"long":instructionSide==="SHORT"?"short":"neutral"} disabled={!instructionActionable||advisorBusy} onClick={()=>void applySoldierInstruction()}>{actionLabel}</button>
    </div>:null}
    <span className="portfolio-koers-current-sr">Actuele portfolio waarde {latest===null?"onbekend":compactUsd(latest)}</span>
  </section>;
}
