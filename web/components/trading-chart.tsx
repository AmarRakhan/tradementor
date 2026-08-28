"use client";

import { Component, useCallback, useEffect, useMemo, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { AreaSeries, BarSeries, CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, createChart, createSeriesMarkers, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { authenticatedRequest } from "@/lib/cloud-client";
import { sanitizePortfolioEquityRows } from "@/lib/portfolio-equity-history";
import { layoutVerifiedTradeMarkers, type VerifiedTradeEvent } from "@/lib/trade-marker-layout";

export type ChartExchange = "aster" | "hyperliquid" | "portfolio";
export type TradeSelection = { id: string; symbol: string; exchange: ChartExchange; side: string; entry?: number; mark?: number; exit?: number; openedAt?: string; closedAt?: string; dcaCount?: number };
export type DcaChartLevel = { number: number; price: number };
const EMPTY_DCA_LEVELS: DcaChartLevel[] = [];
type TradeEvent = VerifiedTradeEvent;
type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number };
type ChartType = "candles" | "line" | "area" | "bars";
type IndicatorId = "ema9" | "ema21" | "ema50" | "ema100" | "ema200" | "sma20" | "sma50" | "sma200" | "bb" | "rsi" | "macd" | "atr" | "volume";

class ChartErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("TradingChart safely contained an error", error, info.componentStack); }
  componentDidUpdate(previous: { resetKey: string }) { if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false }); }
  render() {
    if (this.state.failed) return <section className="trading-terminal chart-safe-fallback"><div className="chart-state error"><strong>Grafiek tijdelijk opnieuw laden</strong><span>De positiegegevens blijven beschikbaar. Probeer de grafiek opnieuw zonder de pagina te verlaten.</span><button onClick={() => this.setState({ failed: false })}>Grafiek herstellen</button></div></section>;
    return this.props.children;
  }
}

export type TradingChartMode = "default" | "aster-detail";

export function SafeTradingChart({ selection, mode = "default", focusAtMs, breakEvenPrice, dcaLevels = EMPTY_DCA_LEVELS, selectedActionId }: { selection: TradeSelection; mode?: TradingChartMode; focusAtMs?: number; breakEvenPrice?: number; dcaLevels?: DcaChartLevel[]; selectedActionId?: string }) {
  return <ChartErrorBoundary resetKey={`${selection.exchange}:${selection.id}:${selection.symbol}:${mode}`}><TradingChart selection={selection} mode={mode} focusAtMs={focusAtMs} breakEvenPrice={breakEvenPrice} dcaLevels={dcaLevels} selectedActionId={selectedActionId} /></ChartErrorBoundary>;
}

const timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1D", "1W"];
const indicators: Array<[IndicatorId, string]> = [["ema9","EMA 9"],["ema21","EMA 21"],["ema50","EMA 50"],["ema100","EMA 100"],["ema200","EMA 200"],["sma20","SMA 20"],["sma50","SMA 50"],["sma200","SMA 200"],["bb","Bollinger Bands"],["rsi","RSI 14"],["macd","MACD"],["atr","ATR"],["volume","Volume"]];
const colors = ["#43e5c4", "#55a7ff", "#9b7cff", "#ffb74d", "#f06292", "#26c6da", "#ffee58", "#ab47bc"];
const PORTFOLIO_HISTORY_KEY = "tradementor.test.portfolioEquity.v1";
const RISK_HISTORY_KEY = "tradementor.test.riskTimeline.v1";

function portfolioCandles(timeframe: string): Candle[] {
  const seconds = ({"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,"1h":3600,"2h":7200,"4h":14400,"6h":21600,"12h":43200,"1D":86400,"1W":604800} as Record<string, number>)[timeframe] ?? 900;
  try {
    const stored = JSON.parse(window.localStorage.getItem(PORTFOLIO_HISTORY_KEY) || "[]");
    const riskStored = JSON.parse(window.localStorage.getItem(RISK_HISTORY_KEY) || "[]");
    const rows = sanitizePortfolioEquityRows([
      ...(Array.isArray(stored) ? stored : []),
      ...(Array.isArray(riskStored) ? riskStored.filter((row) => row?.exchange === "all").map((row) => ({ at:row.at, total:row.equity })) : []),
    ]);
    const buckets = new Map<number, number[]>();
    for (const row of rows) {
      const at = Number(row?.at), value = Number(row?.total);
      if (!Number.isFinite(at) || !Number.isFinite(value) || value <= 0) continue;
      const bucket = Math.floor(at / 1000 / seconds) * seconds;
      buckets.set(bucket, [...(buckets.get(bucket) || []), value]);
    }
    return [...buckets.entries()].sort((a,b)=>a[0]-b[0]).map(([time, values]) => ({ time, open:values[0], high:Math.max(...values), low:Math.min(...values), close:values[values.length-1], volume:0 }));
  } catch { return []; }
}

function average(values: number[], period: number, exponential: boolean) {
  const output: Array<{time: UTCTimestamp; value: number}> = [];
  let ema = values[0] ?? 0;
  const k = 2 / (period + 1);
  values.forEach((value, index) => {
    ema = index ? value * k + ema * (1 - k) : value;
    if (index >= period - 1) {
      const simple = values.slice(index - period + 1, index + 1).reduce((a,b) => a+b,0) / period;
      output.push({ time: 0 as UTCTimestamp, value: exponential ? ema : simple });
    }
  });
  return output;
}

function indicatorData(candles: Candle[], id: IndicatorId) {
  const closes = candles.map((c) => c.close);
  const period = Number(id.replace(/\D/g, "")) || (id === "bb" ? 20 : 14);
  if (id.startsWith("ema") || id.startsWith("sma")) {
    const values = average(closes, period, id.startsWith("ema"));
    return values.map((point, i) => ({ ...point, time: candles[i + period - 1].time as UTCTimestamp }));
  }
  if (id === "rsi") {
    let gain = 0, loss = 0;
    const values: Array<{time:UTCTimestamp;value:number}> = [];
    for (let i=1;i<candles.length;i++) { const delta=closes[i]-closes[i-1]; gain=(gain*13+Math.max(delta,0))/14; loss=(loss*13+Math.max(-delta,0))/14; if(i>=14) values.push({time:candles[i].time as UTCTimestamp,value:loss===0?100:100-(100/(1+gain/loss))}); }
    return values;
  }
  if (id === "atr") {
    return candles.slice(14).map((c,i) => { const range=candles.slice(i+1,i+15).reduce((sum,row,j)=>sum+Math.max(row.high-row.low,Math.abs(row.high-candles[i+j].close),Math.abs(row.low-candles[i+j].close)),0)/14; return {time:c.time as UTCTimestamp,value:range}; });
  }
  return [];
}

export function TradingChart({ selection, mode = "default", focusAtMs, breakEvenPrice, dcaLevels = EMPTY_DCA_LEVELS, selectedActionId }: { selection: TradeSelection; mode?: TradingChartMode; focusAtMs?: number; breakEvenPrice?: number; dcaLevels?: DcaChartLevel[]; selectedActionId?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const shellRef = useRef<HTMLElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceSeriesRef = useRef<ISeriesApi<any> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<any> | null>(null);
  const candleDataRef = useRef<Candle[]>([]);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [datasetVersion, setDatasetVersion] = useState(0);
  const [timeframe, setTimeframe] = useState("15m");
  const [chartType, setChartType] = useState<ChartType>("candles");
  const [activeIndicators, setActiveIndicators] = useState<IndicatorId[]>(mode === "aster-detail" ? ["bb"] : ["volume"]);
  const [indicatorOpen, setIndicatorOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [source, setSource] = useState("");
  const [crosshair, setCrosshair] = useState<Candle | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [tradeEvents, setTradeEvents] = useState<TradeEvent[]>([]);
  const [selectedMarkerEvents, setSelectedMarkerEvents] = useState<TradeEvent[]>([]);
  const [skin, setSkin] = useState<"original" | "suriname-heritage">("original");

  useEffect(() => {
    const readSkin = () => setSkin(document.documentElement.dataset.appSkin === "suriname-heritage" ? "suriname-heritage" : "original");
    readSkin();
    window.addEventListener("tradementor:skin-change", readSkin);
    return () => window.removeEventListener("tradementor:skin-change", readSkin);
  }, []);

  useEffect(() => {
    if (mode === "aster-detail") { setTimeframe("15m"); setChartType("candles"); setActiveIndicators(["bb"]); return; }
    const saved = window.localStorage.getItem("tradementor.chart.preferences");
    if (!saved) return;
    try { const p=JSON.parse(saved); if(timeframes.includes(p.timeframe)) setTimeframe(p.timeframe); if(["candles","line","area","bars"].includes(p.chartType)) setChartType(p.chartType); if(Array.isArray(p.indicators)) setActiveIndicators(p.indicators); } catch { /* ignore corrupt local preference */ }
  }, [mode]);
  useEffect(() => { if (mode !== "aster-detail") window.localStorage.setItem("tradementor.chart.preferences", JSON.stringify({timeframe,chartType,indicators:activeIndicators})); }, [mode,timeframe,chartType,activeIndicators]);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      if (selection.exchange === "portfolio") {
        const history = portfolioCandles(timeframe);
        if (!history.length) throw new Error("Portfoliohistorie wordt vanaf betrouwbare exchange-metingen opgebouwd.");
        candleDataRef.current=history;
        setCandles(history); setSource("Jouw exchange-bevestigde equitymetingen"); setDatasetVersion(version=>version+1);
        return;
      }
      const params = new URLSearchParams({exchange:selection.exchange,symbol:selection.symbol,interval:timeframe.toLowerCase(),limit:"600"});
      const response = await fetch(`/api/market-data?${params}`);
      const json = await response.json();
      if (!response.ok) throw new Error(json.error || "Candles konden niet worden geladen.");
      candleDataRef.current=json.candles;
      setCandles(json.candles); setSource(json.source); setDatasetVersion(version=>version+1);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Marktdata is tijdelijk niet beschikbaar."); }
    finally { setLoading(false); }
  }, [selection.exchange, selection.symbol, timeframe]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    let cancelled = false;
    if (selection.exchange !== "aster" || !/^(long|short)$/i.test(selection.side)) { setTradeEvents([]); return; }
    const query = new URLSearchParams({ symbol: selection.symbol, side: selection.side });
    if (mode === "aster-detail") query.set("all_cycles", "true");
    if (selection.closedAt) {
      const closedAtMs = new Date(selection.closedAt).getTime();
      if (Number.isFinite(closedAtMs) && closedAtMs > 0) query.set("closed_at_ms", String(closedAtMs));
    } else if (focusAtMs && Number.isFinite(focusAtMs) && focusAtMs > 0) query.set("anchor_at_ms", String(Math.floor(focusAtMs)));
    authenticatedRequest(`/api/exchanges/aster/trade-events?${query}`)
      .then((payload) => { if (!cancelled) setTradeEvents(Array.isArray(payload.events) ? payload.events as TradeEvent[] : []); })
      .catch(() => { if (!cancelled) setTradeEvents([]); });
    return () => { cancelled = true; };
  }, [selection.exchange, selection.symbol, selection.side, selection.closedAt, focusAtMs, mode]);

  useEffect(() => {
    const chartCandles=candleDataRef.current;
    if (!chartCandles.length || !containerRef.current) return;
    const container = containerRef.current;
    const heritage=skin==="suriname-heritage";
    const chart = createChart(container, { width:container.clientWidth, height:Math.max(390,container.clientHeight), layout:{background:{type:ColorType.Solid,color:heritage?"#031008":"#061225"},textColor:heritage?"#d8c58e":"#8fa6c8",panes:{separatorColor:heritage?"#27351f":"#172c4a",separatorHoverColor:heritage?"#d9ad48":"#2dd4bf"}}, grid:{vertLines:{color:heritage?"rgba(71,104,61,.18)":"rgba(69,96,133,.16)"},horzLines:{color:mode==="aster-detail"?"rgba(0,0,0,0)":heritage?"rgba(71,104,61,.18)":"rgba(69,96,133,.16)"}}, crosshair:{mode:CrosshairMode.MagnetOHLC,vertLine:{color:heritage?"#d8ad4a":"#70a8dc",labelBackgroundColor:heritage?"#5b4318":"#133252"},horzLine:{color:heritage?"#d8ad4a":"#70a8dc",labelBackgroundColor:heritage?"#5b4318":"#133252"}}, rightPriceScale:{borderColor:heritage?"#4b4325":"#1c3858"}, timeScale:{borderColor:heritage?"#4b4325":"#1c3858",timeVisible:true,secondsVisible:false,rightOffset:8}, handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false}, handleScale:{mouseWheel:true,pinch:true,axisPressedMouseMove:true} });
    chartRef.current=chart;
    let priceSeries: ISeriesApi<any>;
    const common={priceLineVisible:mode!=="aster-detail",lastValueVisible:mode!=="aster-detail"};
    if(chartType==="line") priceSeries=chart.addSeries(LineSeries,{...common,color:"#42d8ff",lineWidth:2});
    else if(chartType==="area") priceSeries=chart.addSeries(AreaSeries,{...common,lineColor:"#42d8ff",topColor:"rgba(66,216,255,.32)",bottomColor:"rgba(66,216,255,0)"});
    else if(chartType==="bars") priceSeries=chart.addSeries(BarSeries,{...common,upColor:"#21d6a2",downColor:"#ff5578"});
    else priceSeries=chart.addSeries(CandlestickSeries,{...common,upColor:"#21d6a2",downColor:"#ff5578",wickUpColor:"#21d6a2",wickDownColor:"#ff5578",borderVisible:false});
    priceSeriesRef.current=priceSeries;
    priceSeries.setData(chartCandles.map(c=>chartType==="line"||chartType==="area"?{time:c.time as UTCTimestamp,value:c.close}:{time:c.time as UTCTimestamp,open:c.open,high:c.high,low:c.low,close:c.close}));
    if(activeIndicators.includes("volume") && selection.exchange !== "portfolio"){ const volume=chart.addSeries(HistogramSeries,{priceFormat:{type:"volume"},priceScaleId:"volume",color:"#385e85"},1); volumeSeriesRef.current=volume; volume.setData(chartCandles.map(c=>({time:c.time as UTCTimestamp,value:c.volume,color:c.close>=c.open?"rgba(33,214,162,.45)":"rgba(255,85,120,.42)"}))); chart.panes()[1]?.setHeight(90); } else volumeSeriesRef.current=null;
    activeIndicators.filter(id=>id.startsWith("ema")||id.startsWith("sma")||id==="rsi"||id==="atr").forEach((id,index)=>{ const pane=id==="rsi"||id==="atr"?chart.panes().length:0; const series=chart.addSeries(LineSeries,{color:colors[index%colors.length],lineWidth:1,title:indicators.find(([key])=>key===id)?.[1]},pane); series.setData(indicatorData(chartCandles,id)); if(pane) chart.panes()[pane]?.setHeight(100); });
    if(activeIndicators.includes("bb")){ const period=20; const middle=average(chartCandles.map(c=>c.close),period,false).map((p,i)=>({...p,time:chartCandles[i+period-1].time as UTCTimestamp})); const upper=middle.map((p,i)=>{const vals=chartCandles.slice(i,i+period).map(c=>c.close),m=p.value,sd=Math.sqrt(vals.reduce((s,v)=>s+(v-m)**2,0)/period);return{time:p.time,value:m+2*sd}}); const lower=middle.map((p,i)=>{const vals=chartCandles.slice(i,i+period).map(c=>c.close),m=p.value,sd=Math.sqrt(vals.reduce((s,v)=>s+(v-m)**2,0)/period);return{time:p.time,value:m-2*sd}}); [[upper,"#ff5578"],[middle,"#42a5ff"],[lower,"#21d6a2"]].forEach(([data,color])=>{const s=chart.addSeries(LineSeries,{color:color as string,lineWidth:2});s.setData(data as any)}); }
    if(activeIndicators.includes("macd")){ const closes=chartCandles.map(c=>c.close),fast=average(closes,12,true),slow=average(closes,26,true); const macd=slow.map((point,i)=>({time:chartCandles[i+25].time as UTCTimestamp,value:(fast[i+14]?.value??point.value)-point.value})); const signalRaw=average(macd.map(p=>p.value),9,true); const pane=chart.panes().length; const macdLine=chart.addSeries(LineSeries,{color:"#55a7ff",lineWidth:1,title:"MACD"},pane); macdLine.setData(macd); const signal=chart.addSeries(LineSeries,{color:"#ffb74d",lineWidth:1,title:"Signal"},pane); signal.setData(signalRaw.map((p,i)=>({time:macd[i+8].time,value:p.value}))); chart.panes()[pane]?.setHeight(110); }
    const fallbackEvents:TradeEvent[]=[];const short=selection.side.toLowerCase()==="short";
    if(selection.exchange!=="aster"&&selection.entry)fallbackEvents.push({id:`${selection.id}:entry`,side:short?"SHORT":"LONG",kind:"entry",action:"increase",price:selection.entry,at:selection.openedAt||new Date(chartCandles.at(-1)!.time*1000).toISOString(),timestampMs:selection.openedAt?new Date(selection.openedAt).getTime():chartCandles.at(-1)!.time*1000,exchange:selection.exchange});
    if(selection.exchange!=="aster"&&selection.exit)fallbackEvents.push({id:`${selection.id}:close`,side:short?"SHORT":"LONG",kind:"close",action:"close",price:selection.exit,at:selection.closedAt||new Date(chartCandles.at(-1)!.time*1000).toISOString(),timestampMs:selection.closedAt?new Date(selection.closedAt).getTime():chartCandles.at(-1)!.time*1000,exchange:selection.exchange});
    const markerGroups=layoutVerifiedTradeMarkers(chartCandles,selection.exchange==="aster"?tradeEvents:fallbackEvents,activeIndicators.includes("bb"));
    for(const placement of ["above","below"] as const){const groups=markerGroups.filter(group=>group.placement===placement);if(!groups.length)continue;const markerSeries=chart.addSeries(LineSeries,{color:"rgba(0,0,0,0)",lineVisible:false,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});markerSeries.setData(groups.map(group=>({time:group.time as UTCTimestamp,value:group.displayPrice})));createSeriesMarkers(markerSeries,groups.map(group=>{const highlighted=(Boolean(selectedActionId)&&group.events.some(event=>event.id===selectedActionId))||(mode==="aster-detail"&&Boolean(focusAtMs)&&group.events.some(event=>Math.abs(event.timestampMs-Number(focusAtMs))<=900_000));const label=mode==="aster-detail"?(group.events.length>1?`${group.events.length} ACTIES`:group.events[0]?.kind==="dca"?"":group.events[0]?.kind==="close"?"SELL":"BUY"):(group.events.length>1?String(group.events.length):"");return{time:group.time as UTCTimestamp,position:"inBar",color:highlighted?"#ffd166":group.color,shape:group.shape,text:label,size:highlighted?1.8:group.events.some(event=>event.kind!=="dca")?1.35:1.15}}));}
    const onCrosshair=(param:any)=>{if(!param.time){setCrosshair(null);return;} const time=Number(param.time),c=candleDataRef.current.find(row=>row.time===time);if(c)setCrosshair(c);const group=markerGroups.filter(item=>item.time===time).flatMap(item=>item.events);if(group.length)setSelectedMarkerEvents(group)}; chart.subscribeCrosshairMove(onCrosshair);
    if (mode === "aster-detail") {
      if (Number.isFinite(breakEvenPrice) && Number(breakEvenPrice) > 0) {
        priceSeries.createPriceLine({ price:Number(breakEvenPrice), color:"#21d6a2", lineWidth:2, lineStyle:0, axisLabelVisible:true, title:"WINST VANAF" });
      }
      for (const level of dcaLevels) {
        if (!Number.isFinite(level?.price) || Number(level.price) <= 0 || !Number.isFinite(level?.number)) continue;
        priceSeries.createPriceLine({ price:Number(level.price), color:"#496985", lineWidth:1, lineStyle:2, axisLabelVisible:true, title:`DCA ${Math.round(Number(level.number))}` });
      }
    }
    if (mode === "aster-detail") {
      const targetSec = focusAtMs && Number.isFinite(focusAtMs) ? Math.floor(focusAtMs / 1000) : null;
      let centerIndex = targetSec === null ? chartCandles.length - 1 : chartCandles.reduce((best,row,index)=>Math.abs(row.time-targetSec)<Math.abs(chartCandles[best].time-targetSec)?index:best,0);
      if (targetSec === null && selection.openedAt) {
        const openedSec = Math.floor(new Date(selection.openedAt).getTime()/1000);
        const openedIndex = chartCandles.findIndex(row=>row.time>=openedSec);
        if (openedIndex >= 0 && chartCandles.length - openedIndex <= 60) centerIndex = Math.max(centerIndex, openedIndex + 24);
      }
      const historical = targetSec !== null || Boolean(selection.closedAt);
      const fromIndex = historical ? Math.max(0, centerIndex - 25) : Math.max(0, chartCandles.length - 50);
      const toIndex = historical ? Math.min(chartCandles.length - 1, fromIndex + 49) : chartCandles.length - 1;
      chart.timeScale().setVisibleRange({ from: chartCandles[fromIndex].time as UTCTimestamp, to: chartCandles[toIndex].time as UTCTimestamp });
    } else chart.timeScale().fitContent();
    const observer=new ResizeObserver(()=>{if(chartRef.current!==chart||!container.isConnected)return;try{chart.applyOptions({width:Math.max(1,container.clientWidth),height:Math.max(390,container.clientHeight)})}catch{/* chart may already be disposing */}}); observer.observe(container);
    return()=>{observer.disconnect();if(chartRef.current===chart)chartRef.current=null;priceSeriesRef.current=null;volumeSeriesRef.current=null;try{chart.unsubscribeCrosshairMove(onCrosshair);chart.remove()}catch{/* already removed during navigation */}};
  },[datasetVersion,chartType,activeIndicators,selection,tradeEvents,skin,mode,focusAtMs,breakEvenPrice,dcaLevels,selectedActionId]);

  useEffect(()=>{
    const next=candles.at(-1);
    if(!next||!priceSeriesRef.current)return;
    candleDataRef.current=candles;
    try {
      priceSeriesRef.current.update(chartType==="line"||chartType==="area"?{time:next.time as UTCTimestamp,value:next.close}:{time:next.time as UTCTimestamp,open:next.open,high:next.high,low:next.low,close:next.close});
      volumeSeriesRef.current?.update({time:next.time as UTCTimestamp,value:next.volume,color:next.close>=next.open?"rgba(33,214,162,.45)":"rgba(255,85,120,.42)"});
    } catch { /* ignore stale realtime ticks; the next confirmed dataset rebuilds the chart */ }
  },[candles,chartType]);

  useEffect(()=>{
    if(!candleDataRef.current.length)return;
    if(selection.exchange==="portfolio") { const timer=window.setInterval(load,15_000); return()=>window.clearInterval(timer); }
    let stopped=false, socket:WebSocket|undefined, retry:number|undefined;
    const connect=()=>{ if(stopped)return; setReconnecting(false); const coin=selection.symbol.toUpperCase().replace(/USDT$/,""); const tf=timeframe.toLowerCase(); const url=selection.exchange==="hyperliquid"?"wss://api.hyperliquid.xyz/ws":`wss://fstream.asterdex.com/ws/${coin.toLowerCase()}usdt@kline_${tf}`; socket=new WebSocket(url); socket.onopen=()=>{setReconnecting(false);if(selection.exchange==="hyperliquid")socket?.send(JSON.stringify({method:"subscribe",subscription:{type:"candle",coin,interval:tf}}))}; socket.onmessage=(event)=>{try{const msg=JSON.parse(event.data);const raw=selection.exchange==="hyperliquid"?(msg.channel==="candle"?msg.data:null):msg.k;if(!raw)return;const next: Candle=selection.exchange==="hyperliquid"?{time:Math.floor(Number(raw.t)/1000),open:Number(raw.o),high:Number(raw.h),low:Number(raw.l),close:Number(raw.c),volume:Number(raw.v)}:{time:Math.floor(Number(raw.t)/1000),open:Number(raw.o),high:Number(raw.h),low:Number(raw.l),close:Number(raw.c),volume:Number(raw.v)};if(!Number.isFinite(next.time)||!Number.isFinite(next.close))return;setCandles(rows=>{const last=rows.at(-1);if(!last)return[next];if(last.time===next.time)return[...rows.slice(0,-1),next];if(next.time<last.time)return rows;return[...rows,next].slice(-1200)});}catch{/* ignore malformed market tick */}}; socket.onclose=()=>{if(!stopped){setReconnecting(true);retry=window.setTimeout(connect,2500)}}; socket.onerror=()=>socket?.close();}; connect(); return()=>{stopped=true;if(retry)clearTimeout(retry);socket?.close()};
  },[selection.exchange,selection.symbol,timeframe,datasetVersion,load]);

  const ticker=useMemo(()=>{if(!candles.length)return null;const recent=candles.slice(-Math.min(candles.length,Math.max(2,Math.floor(86400/({"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,"1h":3600,"2h":7200,"4h":14400,"6h":21600,"12h":43200,"1D":86400,"1W":604800}[timeframe]||900)))));const first=recent[0],last=recent.at(-1)!;return{price:last.close,change:first.open?((last.close-first.open)/first.open)*100:0,high:Math.max(...recent.map(c=>c.high)),low:Math.min(...recent.map(c=>c.low)),volume:recent.reduce((s,c)=>s+c.volume,0)}} , [candles,timeframe]);
  const toggleIndicator=(id:IndicatorId)=>setActiveIndicators(current=>current.includes(id)?current.filter(value=>value!==id):[...current,id]);
  const fullscreen=async()=>{if(!shellRef.current)return;if(document.fullscreenElement)await document.exitFullscreen();else await shellRef.current.requestFullscreen()};
  return <section ref={shellRef} className={`trading-terminal ${mode === "aster-detail" ? "aster-detail-chart" : ""}`} aria-label={`Grafiek ${selection.symbol}`}>
    {mode === "aster-detail" ? <><div className="aster-detail-market-strip"><div><strong>{ticker ? ticker.price.toLocaleString("nl-NL",{maximumFractionDigits:8}) : "—"}</strong><span className={ticker && ticker.change >= 0 ? "positive" : "negative"}>{ticker ? `${ticker.change >= 0 ? "+" : ""}${ticker.change.toFixed(2)}%` : "—"}</span></div><small>Laatste 50 candles · {timeframe} · Bollinger Bands</small></div><div className="aster-detail-timeframes" role="group" aria-label="Timeframe kiezen">{timeframes.map(tf=><button type="button" key={tf} className={timeframe===tf?"active":""} onClick={()=>setTimeframe(tf)}>{tf}</button>)}</div></> : <>
      <header className="market-header"><div><span>{selection.exchange === "portfolio" ? "PERSOONLIJKE EQUITY · HISTORIE" : `${selection.exchange.toUpperCase()} · PERPETUAL`}</span><h1>{selection.exchange === "portfolio" ? "Jouw portfolio" : <>{selection.symbol.replace(/USDT$/,"")} <i>/ USDT</i></>}</h1><small>{selection.exchange === "portfolio" ? "Werkelijke portfoliowaarde als analyseerbare grafiek" : selection.side?`${selection.side.toUpperCase()} positie geselecteerd`:"Marktanalyse"}</small></div>{ticker&&<dl><div><dt>Actueel</dt><dd className={ticker.change>=0?"positive":"negative"}>{ticker.price.toLocaleString("nl-NL",{maximumFractionDigits:8})}</dd></div><div><dt>24h</dt><dd className={ticker.change>=0?"positive":"negative"}>{ticker.change>=0?"+":""}{ticker.change.toFixed(2)}%</dd></div><div><dt>High</dt><dd>{ticker.high.toLocaleString("nl-NL",{maximumFractionDigits:8})}</dd></div><div><dt>Low</dt><dd>{ticker.low.toLocaleString("nl-NL",{maximumFractionDigits:8})}</dd></div><div><dt>{selection.exchange === "portfolio" ? "Metingen" : "Volume"}</dt><dd>{selection.exchange === "portfolio" ? candles.length : ticker.volume.toLocaleString("nl-NL",{maximumFractionDigits:2})}</dd></div></dl>}</header>
      <div className="chart-toolbar"><div className="timeframe-strip">{timeframes.map(tf=><button key={tf} className={timeframe===tf?"active":""} onClick={()=>setTimeframe(tf)}>{tf}</button>)}</div><div className="chart-actions"><select aria-label="Grafiektype" value={chartType} onChange={e=>setChartType(e.target.value as ChartType)}><option value="candles">Candles</option><option value="line">Line</option><option value="area">Area</option><option value="bars">Bars</option></select><button className={indicatorOpen?"active":""} onClick={()=>setIndicatorOpen(v=>!v)}>Indicators · {activeIndicators.length}</button><button onClick={fullscreen} aria-label="Grafiek fullscreen">⛶</button></div></div>
      {indicatorOpen&&<div className="indicator-panel"><header><strong>Technische indicatoren</strong><button onClick={()=>setIndicatorOpen(false)}>Gereed</button></header><div>{indicators.map(([id,label])=>{const unavailable=selection.exchange==="portfolio"&&id==="volume";return <label key={id}><input type="checkbox" disabled={unavailable} checked={!unavailable&&activeIndicators.includes(id)} onChange={()=>toggleIndicator(id)}/><span>{unavailable?"Volume · niet van toepassing":label}</span></label>})}</div><small>{selection.exchange === "portfolio" ? "Indicatoren worden berekend uit jouw echte equitymetingen; handelsvolume is hier niet van toepassing." : "Indicatoren worden lokaal berekend uit de zichtbare exchange-candles."}</small></div>}
    </>}
    <div className="chart-stage">{loading&&<div className="chart-state"><i/>Candles laden…</div>}{error&&<div className="chart-state error"><strong>Marktdata tijdelijk niet beschikbaar</strong><span>{error}</span><button onClick={load}>Opnieuw proberen</button></div>}<div ref={containerRef} className="chart-canvas" />{crosshair&&<div className="ohlc-readout"><span>{new Date(crosshair.time*1000).toLocaleString("nl-NL")}</span><b>O {crosshair.open}</b><b>H {crosshair.high}</b><b>L {crosshair.low}</b><b>C {crosshair.close}</b><b>V {crosshair.volume}</b></div>}</div>
    {selectedMarkerEvents.length>0&&<aside className="trade-marker-details"><header><strong>{selectedMarkerEvents.length>1?`${selectedMarkerEvents.length} bevestigde fills`:"Bevestigde exchange-fill"}</strong><button onClick={()=>setSelectedMarkerEvents([])} aria-label="Filldetails sluiten">×</button></header>{selectedMarkerEvents.map(event=><dl key={event.id}><div><dt>Gebeurtenis</dt><dd>{event.kind==="dca"?`DCA${event.dcaNumber?` #${event.dcaNumber}`:""}`:event.kind}</dd></div><div><dt>Richting</dt><dd>{event.side}</dd></div><div><dt>Werkelijke prijs</dt><dd>{event.price.toLocaleString("nl-NL",{maximumFractionDigits:10})}</dd></div><div><dt>Tijd</dt><dd>{new Date(event.timestampMs).toLocaleString("nl-NL")}</dd></div><div><dt>Gevuld</dt><dd>{event.notional?`US$ ${event.notional.toFixed(2)}`:event.quantity??"—"}</dd></div><div><dt>Exchange</dt><dd>{event.exchange||selection.exchange}</dd></div></dl>)}</aside>}
    {mode !== "aster-detail" && <footer className="chart-footer"><span><i className={reconnecting?"reconnecting":""}/>{reconnecting?"Realtime opnieuw verbinden":"Realtime verbonden"}</span><span>Bron: {source||selection.exchange}</span><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">Charts by TradingView</a></footer>}
  </section>;
}
