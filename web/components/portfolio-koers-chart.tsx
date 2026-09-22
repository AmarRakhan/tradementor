"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CandlestickSeries, ColorType, CrosshairMode, LineSeries, createChart, createSeriesMarkers, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { authenticatedRequest } from "@/lib/cloud-client";
import { PORTFOLIO_KOERS_DEFAULT_TIMEFRAME, PORTFOLIO_KOERS_TIMEFRAMES, bollinger20x2, markerVisual, mergeRealtimeEquitySample, normalizePortfolioKoersPayload, parsePortfolioEquityText, portfolioZoneForPrice } from "@/lib/portfolio-koers-chart.mjs";

type Candle={time:number;atMs:number;open:number;high:number;low:number;close:number;samples:number;sourceAtMs:number};
type Zone={index:number;label:string;center:number;lower:number;upper:number;touches:number;atr:number;source:string};
type Marker={time:number;atMs:number;kind?:string;side?:string;label?:string;count?:number;notionalUsd?:number;realizedPnlUsd?:number;amountUsd?:number;cashflowType?:string};
type Payload={timeframe:string;candles:Candle[];markers:Marker[];zones:Zone[];currentZone:number|null;cycleStartEquity:number|null;currentEquity:number|null;snapshotAtMs:number|null;live:boolean;persistent:boolean;externalCashflowsSeparated:boolean;readOnly:boolean;ordersSent:number;source:string};
type ZoneLayout={index:number;label:string;top:number;height:number};

const EMPTY=normalizePortfolioKoersPayload({}) as Payload;
const money=(value:number|null|undefined)=>Number.isFinite(Number(value))?new Intl.NumberFormat("nl-NL",{style:"currency",currency:"USD",minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(value)):"—";
const localTime=(seconds:number)=>new Date(seconds*1000).toLocaleString("nl-NL",{timeZone:"Europe/Amsterdam",day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit",hourCycle:"h23"});

export function PortfolioKoersChart({liveEquityText}:{liveEquityText:string}) {
  const shellRef=useRef<HTMLElement>(null);
  const canvasRef=useRef<HTMLDivElement>(null);
  const chartRef=useRef<IChartApi|null>(null);
  const candleSeriesRef=useRef<ISeriesApi<any>|null>(null);
  const bbRefs=useRef<{upper:ISeriesApi<any>|null;middle:ISeriesApi<any>|null;lower:ISeriesApi<any>|null}>({upper:null,middle:null,lower:null});
  const candleDataRef=useRef<Candle[]>([]);
  const syncZonesRef=useRef<()=>void>(()=>{});
  const [timeframe,setTimeframe]=useState(PORTFOLIO_KOERS_DEFAULT_TIMEFRAME);
  const [payload,setPayload]=useState<Payload>(EMPTY);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(true);
  const [zoneLayout,setZoneLayout]=useState<ZoneLayout[]>([]);
  const [hover,setHover]=useState<{candle:Candle;markers:Marker[]}|null>(null);
  const [liveEquity,setLiveEquity]=useState<number|null>(null);

  useEffect(()=>{
    try{
      const saved=window.localStorage.getItem("tradementor.portfolio-koers.timeframe.v1");
      if(PORTFOLIO_KOERS_TIMEFRAMES.includes(saved)) setTimeframe(saved);
    }catch{/* private storage can be unavailable */}
  },[]);
  useEffect(()=>{try{window.localStorage.setItem("tradementor.portfolio-koers.timeframe.v1",timeframe)}catch{/* ignore */}},[timeframe]);

  const load=useCallback(async()=>{
    try{
      const response=await authenticatedRequest(`/api/exchanges/aster/portfolio-chart?timeframe=${encodeURIComponent(timeframe)}&limit=320`,{cache:"no-store"});
      const normalized=normalizePortfolioKoersPayload(response) as Payload;
      setPayload(normalized);
      setError("");
      if(normalized.currentEquity) setLiveEquity(normalized.currentEquity);
    }catch(reason){
      setError(reason instanceof Error?reason.message:"Portfolio Koers kon niet worden geladen.");
    }finally{setLoading(false)}
  },[timeframe]);

  useEffect(()=>{
    setLoading(true);
    void load();
    const timer=window.setInterval(()=>{if(document.visibilityState==="visible")void load()},45_000);
    const visible=()=>{if(document.visibilityState==="visible")void load()};
    document.addEventListener("visibilitychange",visible);
    return()=>{window.clearInterval(timer);document.removeEventListener("visibilitychange",visible)};
  },[load]);

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
      syncZonesRef.current();
    }catch{/* the next confirmed payload rebuilds a stale chart safely */}
  },[liveEquityText,timeframe]);

  const activeZone=useMemo(()=>portfolioZoneForPrice(payload.zones,liveEquity??payload.currentEquity??payload.candles.at(-1)?.close),[payload.zones,payload.currentEquity,payload.candles,liveEquity]);

  useEffect(()=>{
    const container=canvasRef.current;
    if(!container||!payload.candles.length){candleDataRef.current=[];setZoneLayout([]);return}
    const candles=payload.candles;
    candleDataRef.current=candles.map((row)=>({...row}));
    const chart=createChart(container,{
      width:Math.max(1,container.clientWidth),height:Math.max(300,container.clientHeight),
      layout:{background:{type:ColorType.Solid,color:"#031009"},textColor:"#aebcac"},
      grid:{vertLines:{color:"rgba(80,116,91,.12)"},horzLines:{color:"rgba(80,116,91,.14)"}},
      crosshair:{mode:CrosshairMode.MagnetOHLC,vertLine:{color:"rgba(232,184,61,.58)",labelBackgroundColor:"#513d16"},horzLine:{color:"rgba(232,184,61,.58)",labelBackgroundColor:"#513d16"}},
      rightPriceScale:{borderColor:"rgba(232,184,61,.22)",minimumWidth:76,scaleMargins:{top:.08,bottom:.08}},
      timeScale:{borderColor:"rgba(232,184,61,.2)",timeVisible:true,secondsVisible:false,rightOffset:4,tickMarkFormatter:(time:unknown)=>{
        const sec=typeof time==="number"?time:0; return sec?new Date(sec*1000).toLocaleTimeString("nl-NL",{timeZone:"Europe/Amsterdam",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}):"";
      }},
      localization:{locale:"nl-NL",timeFormatter:(time:unknown)=>localTime(Number(time)||0)},
      handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:true},
      handleScale:{mouseWheel:true,pinch:true,axisPressedMouseMove:true},
    });
    chartRef.current=chart;
    const series=chart.addSeries(CandlestickSeries,{upColor:"#25ef91",downColor:"#ff5b7a",wickUpColor:"#25ef91",wickDownColor:"#ff5b7a",borderVisible:false,priceLineColor:"#e8b83d",priceLineWidth:1,lastValueVisible:true});
    candleSeriesRef.current=series;
    series.setData(candles.map((row)=>({time:row.time as UTCTimestamp,open:row.open,high:row.high,low:row.low,close:row.close})));

    const bb=bollinger20x2(candles);
    const upper=chart.addSeries(LineSeries,{color:"rgba(83,179,255,.78)",lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    const middle=chart.addSeries(LineSeries,{color:"rgba(232,184,61,.82)",lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    const lower=chart.addSeries(LineSeries,{color:"rgba(83,179,255,.78)",lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    bbRefs.current={upper,middle,lower};
    upper.setData(bb.upper.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
    middle.setData(bb.middle.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));
    lower.setData(bb.lower.map((row:any)=>({time:row.time as UTCTimestamp,value:row.value})));

    if(payload.cycleStartEquity&&payload.cycleStartEquity>0){
      series.createPriceLine({price:payload.cycleStartEquity,color:"#e8b83d",lineWidth:1,lineStyle:2,axisLabelVisible:true,title:"CYCLE START"});
    }

    const candleTimes=new Set(candles.map((row)=>row.time));
    const visualMarkers=payload.markers.filter((row)=>candleTimes.has(row.time)).map((row)=>{
      const visual=markerVisual(row);
      const color=visual.tone==="long"?"#25ef91":visual.tone==="short"?"#ff5b7a":visual.tone==="cashflow"?"#6bbcff":"#e8b83d";
      return {time:row.time as UTCTimestamp,position:visual.position as any,shape:visual.shape as any,color,text:visual.text,size:visual.tone==="cashflow"?.9:1.05};
    });
    if(visualMarkers.length) createSeriesMarkers(series,visualMarkers);

    const syncZones=()=>{
      if(candleSeriesRef.current!==series||!container.isConnected){return}
      const height=Math.max(1,container.clientHeight);
      const next:ZoneLayout[]=[];
      for(const zone of payload.zones){
        const upperY=series.priceToCoordinate(zone.upper), lowerY=series.priceToCoordinate(zone.lower);
        if(upperY===null||lowerY===null)continue;
        const top=Math.max(0,Math.min(Number(upperY),Number(lowerY))), bottom=Math.min(height,Math.max(Number(upperY),Number(lowerY)));
        if(bottom<=0||top>=height||bottom-top<1)continue;
        next.push({index:zone.index,label:zone.label,top,height:Math.max(2,bottom-top)});
      }
      setZoneLayout(next);
    };
    syncZonesRef.current=()=>requestAnimationFrame(syncZones);
    const onCrosshair=(param:any)=>{
      if(!param.time){setHover(null);return}
      const time=Number(param.time), candle=candleDataRef.current.find((row)=>row.time===time);
      if(!candle){setHover(null);return}
      setHover({candle,markers:payload.markers.filter((row)=>row.time===time)});
    };
    chart.subscribeCrosshairMove(onCrosshair);
    const sync=()=>syncZonesRef.current();
    chart.timeScale().subscribeVisibleLogicalRangeChange(sync);
    const resize=new ResizeObserver(()=>{
      if(chartRef.current!==chart||!container.isConnected)return;
      try{chart.applyOptions({width:Math.max(1,container.clientWidth),height:Math.max(300,container.clientHeight)});sync()}catch{/* disposed */}
    });
    resize.observe(container);
    container.addEventListener("pointermove",sync,{passive:true});
    container.addEventListener("touchmove",sync,{passive:true});
    chart.timeScale().fitContent();
    sync();

    return()=>{
      resize.disconnect();chart.timeScale().unsubscribeVisibleLogicalRangeChange(sync);
      container.removeEventListener("pointermove",sync);container.removeEventListener("touchmove",sync);
      try{chart.unsubscribeCrosshairMove(onCrosshair);chart.remove()}catch{/* disposed */}
      if(chartRef.current===chart)chartRef.current=null;
      candleSeriesRef.current=null;bbRefs.current={upper:null,middle:null,lower:null};syncZonesRef.current=()=>{};
    };
  },[payload.candles,payload.markers,payload.zones,payload.cycleStartEquity]);

  const fullscreen=async()=>{
    if(!shellRef.current)return;
    try{if(document.fullscreenElement)await document.exitFullscreen();else await shellRef.current.requestFullscreen()}catch{/* unsupported */}
  };
  const latest=liveEquity??payload.currentEquity??payload.candles.at(-1)?.close??null;

  return <section ref={shellRef} className="portfolio-koers-card" aria-label="Portfolio Koers">
    <header className="portfolio-koers-header">
      <div className="portfolio-koers-title"><span className="portfolio-koers-kicker">PORTFOLIO KOERS</span><strong>{money(latest)}</strong><small>{activeZone===null?"Zone wordt opgebouwd":activeZone===0?"Zone 0":`Zone ${activeZone>0?"+":""}${activeZone}`} · Bollinger 20,2</small></div>
      <div className="portfolio-koers-actions"><span className={payload.live?"portfolio-koers-live is-live":"portfolio-koers-live"}><i/>{payload.live?"LIVE":"SYNC"}</span><button type="button" onClick={fullscreen} aria-label="Portfolio Koers fullscreen">⛶</button></div>
    </header>
    <div className="portfolio-koers-toolbar" role="group" aria-label="Portfolio Koers timeframe">
      {PORTFOLIO_KOERS_TIMEFRAMES.map((value)=><button type="button" key={value} className={timeframe===value?"active":""} onClick={()=>setTimeframe(value)}>{value}</button>)}
    </div>
    <div className="portfolio-koers-stage">
      <div ref={canvasRef} className="portfolio-koers-canvas"/>
      <div className="portfolio-koers-zones" aria-hidden="true">{zoneLayout.map((zone)=><div key={zone.index} className={`portfolio-koers-zone ${zone.index===activeZone?"active":""} ${zone.index===0?"zero":zone.index>0?"positive":"negative"}`} style={{top:`${zone.top}px`,height:`${zone.height}px`}}><span>{zone.label}</span></div>)}</div>
      {loading&&!payload.candles.length?<div className="portfolio-koers-state"><i/>Portfoliohistorie laden…</div>:null}
      {!loading&&!payload.candles.length&&!error?<div className="portfolio-koers-state"><strong>Historie wordt opgebouwd</strong><span>Alleen echte, bevestigde Aster-equitymetingen worden opgeslagen.</span></div>:null}
      {error&&!payload.candles.length?<div className="portfolio-koers-state error"><strong>Portfolio Koers tijdelijk niet beschikbaar</strong><span>{error}</span><button type="button" onClick={()=>void load()}>Opnieuw proberen</button></div>:null}
      {hover?<div className="portfolio-koers-tooltip"><span>{localTime(hover.candle.time)}</span><b>O {money(hover.candle.open)}</b><b>H {money(hover.candle.high)}</b><b>L {money(hover.candle.low)}</b><b>C {money(hover.candle.close)}</b>{hover.markers.map((row,index)=><em key={`${row.kind}-${row.side}-${index}`}>{row.label}</em>)}</div>:null}
    </div>
    <footer className="portfolio-koers-footer"><span><i/>Candles: echte portfolio-equity</span><span>Zones: swing/S&amp;R + ATR</span><span>Transfers apart</span></footer>
  </section>;
}
