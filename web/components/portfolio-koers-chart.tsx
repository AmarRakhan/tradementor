"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CandlestickSeries, ColorType, CrosshairMode, LineSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { authenticatedRequest } from "@/lib/cloud-client";
import { useAuthSession } from "@/components/auth-provider";
import { sanitizePortfolioEquityRows } from "@/lib/portfolio-equity-history";
import { PORTFOLIO_KOERS_DEFAULT_TIMEFRAME, PORTFOLIO_KOERS_TIMEFRAMES, aggregatePortfolioEquityHistory, bollinger20x2, markerVisual, mergePortfolioKoersCandles, mergeRealtimeEquitySample, normalizePortfolioKoersPayload, parsePortfolioEquityText, portfolioZoneForPrice } from "@/lib/portfolio-koers-chart.mjs";
import { eventPriority, layoutPortfolioKoersMarkers, zoneToneForRank } from "@/lib/portfolio-koers-marker-layout.mjs";

type Candle={time:number;atMs:number;open:number;high:number;low:number;close:number;samples:number;sourceAtMs:number};
type Zone={index:number;label:string;center:number;lower:number;upper:number;touches:number;atr:number;source:string};
type Marker={time:number;atMs:number;kind?:string;side?:string;label?:string;count?:number;notionalUsd?:number;realizedPnlUsd?:number;amountUsd?:number;cashflowType?:string};
type Payload={timeframe:string;candles:Candle[];markers:Marker[];zones:Zone[];currentZone:number|null;cycleStartEquity:number|null;currentEquity:number|null;snapshotAtMs:number|null;live:boolean;persistent:boolean;externalCashflowsSeparated:boolean;readOnly:boolean;ordersSent:number;source:string};
type ZoneLayout={index:number;label:string;top:number;height:number;tone:"red"|"amber"|"green"|"blue"};
type EventLabel={id:string;left:number;top:number;position:"above"|"below";tone:"long"|"short"|"tp"|"cashflow"|"cluster";title:string;value:string;glyph?:string;multiplier?:string;compact?:boolean;eventCount?:number;anchorLeft?:number;anchorTop?:number};

const EMPTY=normalizePortfolioKoersPayload({}) as Payload;
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

function markerPresentation(row:Marker) {
  const kind=String(row.kind||"").toLowerCase(),side=String(row.side||"").toUpperCase(),count=Math.max(1,Number(row.count)||1);
  const multiplier=count>1?`×${count}`:"";
  if(kind==="cashflow")return {tone:"cashflow" as const,glyph:"↕",multiplier,title:String(row.cashflowType||"Transfer").replaceAll("_"," "),value:""};
  if(kind==="entry")return {tone:(side==="SHORT"?"short":"long") as "short"|"long",glyph:"♟",multiplier,title:side==="SHORT"?"SHORT":"LONG",value:""};
  return {tone:"tp" as const,glyph:"💰",multiplier,title:"Take Profit",value:""};
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
  const [eventLabels,setEventLabels]=useState<EventLabel[]>([]);
  const [hover,setHover]=useState<{candle:Candle;markers:Marker[]}|null>(null);
  const [liveEquity,setLiveEquity]=useState<number|null>(null);
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
  const activeZone=useMemo(()=>portfolioZoneForPrice(payload.zones,liveEquity??payload.currentEquity??baseCandles.at(-1)?.close),[payload.zones,payload.currentEquity,baseCandles,liveEquity]);

  useEffect(()=>{
    const container=canvasRef.current;
    const observedEquity=parsePortfolioEquityText(liveEquityTextRef.current);
    const candles=(observedEquity?mergeRealtimeEquitySample(baseCandles,observedEquity,Date.now(),timeframe):baseCandles) as Candle[];
    if(!container||!candles.length){candleDataRef.current=[];setZoneLayout([]);setEventLabels([]);return}
    candleDataRef.current=candles.map((row)=>({...row}));
    const view=TIMEFRAME_VIEW[timeframe]||TIMEFRAME_VIEW["15m"];
    const chart=createChart(container,{
      width:Math.max(1,container.clientWidth),height:Math.max(220,container.clientHeight),
      layout:{background:{type:ColorType.Solid,color:"#03131b"},textColor:"#b8c8d2",attributionLogo:false} as any,
      grid:{vertLines:{color:"rgba(75,133,160,.07)"},horzLines:{color:"rgba(75,133,160,.09)"}},
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
      const orderedZones=[...payload.zones].sort((a,b)=>b.center-a.center);
      const zones:ZoneLayout[]=[];
      for(let rank=0;rank<orderedZones.length;rank+=1){
        const zone=orderedZones[rank];
        const upperY=series.priceToCoordinate(zone.upper),lowerY=series.priceToCoordinate(zone.lower);
        if(upperY===null||lowerY===null)continue;
        const top=Math.max(0,Math.min(Number(upperY),Number(lowerY))),bottom=Math.min(height,Math.max(Number(upperY),Number(lowerY)));
        if(bottom<=0||top>=height||bottom-top<1)continue;
        zones.push({index:zone.index,label:zone.label,top,height:Math.max(2,bottom-top),tone:zoneToneForRank(rank,orderedZones.length) as ZoneLayout["tone"]});
      }
      setZoneLayout(zones);

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
          width:copy.multiplier?40:26,height:22,
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
      candleSeriesRef.current=null;bbRefs.current={upper:null,middle:null,lower:null};syncOverlaysRef.current=()=>{};setEventLabels([]);
    };
  },[baseCandles,payload.markers,payload.zones,payload.cycleStartEquity,timeframe]);

  const fullscreen=async()=>{
    if(!shellRef.current)return;
    try{if(document.fullscreenElement)await document.exitFullscreen();else await shellRef.current.requestFullscreen()}catch{/* unsupported */}
  };
  const latest=liveEquity??payload.currentEquity??baseCandles.at(-1)?.close??null;

  return <section ref={shellRef} className="portfolio-koers-card" aria-label="Portfolio Koers" data-reference="file_00000000c7ec820ab9697735bb027326">
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
      <div className="portfolio-koers-zones" aria-hidden="true">{zoneLayout.map((zone)=><div key={zone.index} className={`portfolio-koers-zone zone-${zone.tone} ${zone.index===activeZone?"active":""}`} style={{top:`${zone.top}px`,height:`${zone.height}px`}}><span>{zone.label}</span></div>)}</div>
      <div className="portfolio-koers-event-layer" aria-hidden="true">{eventLabels.map((label)=><div key={label.id} className="portfolio-koers-event-group">{!label.compact&&Number.isFinite(label.anchorLeft)&&Number.isFinite(label.anchorTop)?<i className={`portfolio-koers-anchor ${label.tone}`} style={{left:`${label.anchorLeft}px`,top:`${label.anchorTop}px`}}/>:null}<div className={`portfolio-koers-event ${label.tone} ${label.position} ${label.compact?"compact":""}`} style={{left:`${label.left}px`,top:`${label.top}px`}}>{label.compact?<b>{label.multiplier||`+${label.eventCount}`}</b>:<><b className="portfolio-koers-event-glyph">{label.glyph}</b>{label.multiplier?<small>{label.multiplier}</small>:null}</>}</div></div>)}</div>
      {loading&&!baseCandles.length?<div className="portfolio-koers-state"><i/>Portfoliohistorie laden…</div>:null}
      {!loading&&!baseCandles.length&&!error?<div className="portfolio-koers-state"><strong>Historie wordt opgebouwd</strong><span>Nieuwe candles gebruiken bevestigde Aster-equity; bestaande bevestigde browserhistorie wordt veilig hergebruikt als die beschikbaar is.</span></div>:null}
      {error&&!baseCandles.length?<div className="portfolio-koers-state error"><strong>Portfolio Koers tijdelijk niet beschikbaar</strong><span>{error}</span><button type="button" onClick={()=>void load()}>Opnieuw proberen</button></div>:null}
      {hover?<div className="portfolio-koers-tooltip"><span>{localTime(hover.candle.time)}</span><b>O {compactUsd(hover.candle.open)}</b><b>H {compactUsd(hover.candle.high)}</b><b>L {compactUsd(hover.candle.low)}</b><b>C {compactUsd(hover.candle.close)}</b>{hover.markers.map((row,index)=><em key={`${row.kind}-${row.side}-${index}`}>{markerDetail(row)}</em>)}</div>:null}
    </div>
    <span className="portfolio-koers-current-sr">Actuele portfolio waarde {latest===null?"onbekend":compactUsd(latest)}</span>
  </section>;
}
