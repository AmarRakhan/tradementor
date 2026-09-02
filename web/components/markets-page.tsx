"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { SafeTradingChart, type TradeSelection } from "@/components/trading-chart";
import styles from "./markets-page.module.css";

type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
type BbStatus = "above" | "between" | "below";
type BbFilter = "all" | BbStatus;
type SortKey = "volume" | "change" | "leverage" | "bb";
type SortDirection = "asc" | "desc";
type QuickSide = "LONG" | "SHORT";
type MarketRow = { symbol:string;baseAsset:string;lastPrice:number;change24hPct:number;quoteVolume24h:number;maxLeverage:number|null;bbStatus:BbStatus|null;bbUpper:number|null;bbMiddle:number|null;bbLower:number|null };
type MarketsPayload = { marketCount:number;updatedAt:number;interval:Timeframe;markets:MarketRow[] };
type EnrichedRow = Pick<MarketRow,"symbol"|"maxLeverage"|"bbStatus"|"bbUpper"|"bbMiddle"|"bbLower">;
type EnrichmentPayload = { markets:EnrichedRow[];errors?:Array<{symbol:string;detail:string}>;updatedAt:number };
type QuickTrade = { row:MarketRow;side:QuickSide;effective:Record<string,unknown>;idempotencyKey:string };
type PairDraft = { maxDca:string;dcaMarginUsd:string;dcaDistancePct:string;takeProfitPct:string };

const TIMEFRAMES:Timeframe[]=["1m","5m","15m","1h","4h","1d"];
const BB_FILTERS:Array<{id:BbFilter;label:string}>=[{id:"all",label:"Alle"},{id:"above",label:"Boven upper"},{id:"between",label:"Tussen banden"},{id:"below",label:"Onder lower"}];
const BB_RANK:Record<BbStatus,number>={above:3,between:2,below:1};
const ENRICH_BATCH_SIZE=8;
const asRecord=(value:unknown):Record<string,unknown>=>value&&typeof value==="object"&&!Array.isArray(value)?value as Record<string,unknown>:{};
const asNumber=(value:unknown,fallback=0)=>{const n=Number(value);return Number.isFinite(n)?n:fallback};
const compactUsd=(value:number)=>new Intl.NumberFormat("nl-NL",{style:"currency",currency:"USD",notation:"compact",maximumFractionDigits:1}).format(value);
const price=(value:number)=>new Intl.NumberFormat("en-US",{minimumFractionDigits:0,maximumFractionDigits:value>=1000?2:value>=1?4:value>=.01?5:7}).format(value);
const signedPercent=(value:number)=>`${value>0?"+":""}${value.toFixed(2)}%`;
const statusLabel=(status:BbStatus)=>status==="above"?"Above Upper":status==="below"?"Below Lower":"Between Bands";
const classifyBb=(livePrice:number,upper:number|null,lower:number|null,fallback:BbStatus|null)=>upper===null||lower===null?fallback:livePrice>upper?"above":livePrice<lower?"below":"between";

export function MarketsPage(){
  const [timeframe,setTimeframe]=useState<Timeframe>("15m");
  const [query,setQuery]=useState("");
  const [bbFilter,setBbFilter]=useState<BbFilter>("all");
  const [sortKey,setSortKey]=useState<SortKey>("volume");
  const [sortDirection,setSortDirection]=useState<SortDirection>("desc");
  const [data,setData]=useState<MarketsPayload|null>(null);
  const [loading,setLoading]=useState(true),[refreshing,setRefreshing]=useState(false),[enriching,setEnriching]=useState(false);
  const [error,setError]=useState(""),[quickMessage,setQuickMessage]=useState("");
  const [quickTrade,setQuickTrade]=useState<QuickTrade|null>(null),[quickBusy,setQuickBusy]=useState(false);
  const [chartRow,setChartRow]=useState<MarketRow|null>(null);
  const [strategySettings,setStrategySettings]=useState<Record<string,unknown>>({});
  const [activeBySymbol,setActiveBySymbol]=useState<Record<string,string[]>>({});
  const [pairRow,setPairRow]=useState<MarketRow|null>(null),[pairDraft,setPairDraft]=useState<PairDraft>({maxDca:"3",dcaMarginUsd:"2",dcaDistancePct:"0.30",takeProfitPct:"1.50"}),[pairBusy,setPairBusy]=useState(false);
  const generationRef=useRef(0);

  const loadAccount=useCallback(async()=>{
    try{
      const account=await authenticatedRequest("/api/exchanges/aster") as Record<string,unknown>;
      const strategy2=asRecord(account.strategy2); const settings=asRecord(strategy2.settings); setStrategySettings(settings);
      const map:Record<string,string[]>={};
      for(const raw of Array.isArray(account.positions)?account.positions:[]){const row=asRecord(raw);const symbol=String(row.symbol||"").toUpperCase();const side=String(row.side||row.positionSide||"").toUpperCase();if(symbol&&side){if(!map[symbol])map[symbol]=[];if(!map[symbol].includes(side))map[symbol].push(side)}}
      setActiveBySymbol(map);
    }catch{/* Markets-data blijft bruikbaar wanneer accountstatus tijdelijk niet kan worden gelezen. */}
  },[]);

  const enrich=useCallback(async(base:MarketsPayload,generation:number)=>{
    setEnriching(true);let partialFailures=0;
    try{
      const symbols=base.markets.map(row=>row.symbol);
      for(let index=0;index<symbols.length;index+=ENRICH_BATCH_SIZE){
        if(generationRef.current!==generation)return;
        const batch=symbols.slice(index,index+ENRICH_BATCH_SIZE);
        try{
          const payload=await authenticatedRequest(`/api/markets/aster?mode=enrich&interval=${encodeURIComponent(base.interval)}&symbols=${encodeURIComponent(batch.join(","))}`) as EnrichmentPayload;
          if(generationRef.current!==generation)return;if(!payload||!Array.isArray(payload.markets))throw new Error("Ongeldige enrichment");
          partialFailures+=Array.isArray(payload.errors)?payload.errors.length:0;const updates=new Map(payload.markets.map(row=>[row.symbol,row]));
          setData(current=>!current||current.interval!==base.interval?current:{...current,updatedAt:Math.max(current.updatedAt,payload.updatedAt||0),markets:current.markets.map(row=>{const update=updates.get(row.symbol);return update?{...row,...update,bbStatus:classifyBb(row.lastPrice,update.bbUpper,update.bbLower,update.bbStatus)}:row})});
        }catch{partialFailures+=batch.length}
      }
      if(generationRef.current===generation&&partialFailures>0)setError(`${partialFailures} markt${partialFailures===1?"":"en"} kon${partialFailures===1?"":"den"} nog niet volledig worden aangevuld.`);
    }finally{if(generationRef.current===generation)setEnriching(false)}
  },[]);

  const load=useCallback(async(background=false,runEnrichment=true)=>{
    const generation=runEnrichment?++generationRef.current:generationRef.current;background?setRefreshing(true):setLoading(true);setError("");
    try{
      const payload=await authenticatedRequest(`/api/markets/aster?mode=base&interval=${encodeURIComponent(timeframe)}`) as MarketsPayload;
      if(!payload||!Array.isArray(payload.markets))throw new Error("Markets-response heeft een ongeldig formaat");if(runEnrichment&&generationRef.current!==generation)return;
      setData(current=>{if(!current||current.interval!==payload.interval)return payload;const oldBySymbol=new Map(current.markets.map(row=>[row.symbol,row]));return{...payload,markets:payload.markets.map(fresh=>{const old=oldBySymbol.get(fresh.symbol);return old?{...fresh,maxLeverage:old.maxLeverage,bbUpper:old.bbUpper,bbMiddle:old.bbMiddle,bbLower:old.bbLower,bbStatus:classifyBb(fresh.lastPrice,old.bbUpper,old.bbLower,old.bbStatus)}:fresh})}});
      setLoading(false);setRefreshing(false);if(runEnrichment)void enrich(payload,generation);void loadAccount();
    }catch(reason){if(runEnrichment&&generationRef.current!==generation)return;setError(reason instanceof Error?reason.message:"Markets kon niet worden geladen");setLoading(false);setRefreshing(false);if(runEnrichment)setEnriching(false)}
  },[enrich,timeframe,loadAccount]);

  useEffect(()=>{void load(false,true)},[load]);
  useEffect(()=>{const timer=window.setInterval(()=>{if(document.visibilityState==="visible")void load(true,false)},60_000);return()=>window.clearInterval(timer)},[load]);
  useEffect(()=>{if(!chartRow&&!pairRow)return;const previous=document.body.style.overflow;document.body.style.overflow="hidden";const esc=(event:KeyboardEvent)=>{if(event.key==="Escape"){setChartRow(null);setPairRow(null)}};window.addEventListener("keydown",esc);return()=>{document.body.style.overflow=previous;window.removeEventListener("keydown",esc)}},[chartRow,pairRow]);

  const enrichedCount=useMemo(()=>(data?.markets||[]).filter(row=>row.maxLeverage!==null&&row.bbStatus!==null).length,[data]);
  const rows=useMemo(()=>{const normalized=query.trim().toUpperCase();const filtered=(data?.markets||[]).filter(row=>!normalized||row.symbol.includes(normalized)||row.baseAsset.includes(normalized)).filter(row=>bbFilter==="all"||row.bbStatus===bbFilter);const direction=sortDirection==="asc"?1:-1;return[...filtered].sort((a,b)=>{if((sortKey==="leverage"&&(a.maxLeverage===null||b.maxLeverage===null))||(sortKey==="bb"&&(a.bbStatus===null||b.bbStatus===null))){const ar=sortKey==="leverage"?a.maxLeverage!==null:a.bbStatus!==null;const br=sortKey==="leverage"?b.maxLeverage!==null:b.bbStatus!==null;if(ar!==br)return ar?-1:1}let delta=0;if(sortKey==="volume")delta=a.quoteVolume24h-b.quoteVolume24h;else if(sortKey==="change")delta=a.change24hPct-b.change24hPct;else if(sortKey==="leverage")delta=(a.maxLeverage||0)-(b.maxLeverage||0);else if(a.bbStatus&&b.bbStatus)delta=BB_RANK[a.bbStatus]-BB_RANK[b.bbStatus];return delta*direction||a.symbol.localeCompare(b.symbol)})},[data,query,bbFilter,sortKey,sortDirection]);
  const chooseSort=(key:SortKey)=>{if(sortKey===key)setSortDirection(value=>value==="desc"?"asc":"desc");else{setSortKey(key);setSortDirection("desc")}};
  const arrow=(key:SortKey)=>sortKey===key?(sortDirection==="desc"?"↓":"↑"):"↕";
  const updated=data?.updatedAt?new Date(data.updatedAt).toLocaleTimeString("nl-NL",{hour:"2-digit",minute:"2-digit",second:"2-digit"}):"—";

  function effectiveSettings(row:MarketRow,side:QuickSide){const direction=asRecord(side==="LONG"?strategySettings.standardLong:strategySettings.standardShort);const overrides=asRecord(strategySettings.pairOverrides);const pair=asRecord(overrides[row.symbol]);return{...strategySettings,...direction,...pair}}
  async function prepareQuickTrade(row:MarketRow,side:QuickSide){setQuickBusy(true);setQuickMessage("");try{if(!Object.keys(strategySettings).length)await loadAccount();const effective=effectiveSettings(row,side);setQuickTrade({row,side,effective,idempotencyKey:`${row.symbol}-${side}-${crypto.randomUUID()}`})}catch(reason){setQuickMessage(reason instanceof Error?reason.message:"Strategy 2-instellingen konden niet worden geladen.")}finally{setQuickBusy(false)}}
  async function confirmQuickTrade(){if(!quickTrade||quickBusy)return;setQuickBusy(true);setQuickMessage(`${quickTrade.row.symbol} ${quickTrade.side}: OPENING · wachten op Aster fill…`);try{const result=await authenticatedRequest("/api/exchanges/aster/strategy2/quick-trade",{method:"POST",body:JSON.stringify({symbol:quickTrade.row.symbol,side:quickTrade.side,idempotency_key:quickTrade.idempotencyKey,confirm:true})}) as Record<string,unknown>;const cycle=String(result.cycleId||"");const status=String(result.status||"ACTIVE").toUpperCase();setQuickMessage(`${quickTrade.row.symbol} ${quickTrade.side}: ${status}${cycle?` · cycle ${cycle}`:""}.`);setQuickTrade(null);await loadAccount()}catch(reason){setQuickMessage(`FAILED · ${reason instanceof Error?reason.message:"Positie kon niet worden geopend."}`)}finally{setQuickBusy(false)}}

  function openPairSettings(row:MarketRow){const overrides=asRecord(strategySettings.pairOverrides);const override=asRecord(overrides[row.symbol]);const standard=asRecord(strategySettings.standardLong);const merged={...standard,...override};setPairRow(row);setPairDraft({maxDca:String(merged.maxDca??3),dcaMarginUsd:String(merged.dcaMarginUsd??2),dcaDistancePct:String((asNumber(merged.dcaDistance,.003)*100).toFixed(2)),takeProfitPct:String((asNumber(merged.takeProfit,.015)*100).toFixed(2))})}
  async function savePairOverride(reset=false){if(!pairRow||pairBusy)return;setPairBusy(true);setQuickMessage("");try{const overrides={...asRecord(strategySettings.pairOverrides)};if(reset)delete overrides[pairRow.symbol];else overrides[pairRow.symbol]={...asRecord(overrides[pairRow.symbol]),maxDca:Math.max(0,Math.round(asNumber(pairDraft.maxDca,3))),dcaMarginUsd:Math.max(.01,asNumber(pairDraft.dcaMarginUsd,2)),dcaDistance:Math.max(.0001,asNumber(pairDraft.dcaDistancePct,.3)/100),takeProfit:Math.max(.001,asNumber(pairDraft.takeProfitPct,1.5)/100)};const next={...strategySettings,pairOverrides:overrides};await authenticatedRequest("/api/exchanges/aster/strategy2/settings",{method:"PUT",body:JSON.stringify({settings:next})});setStrategySettings(next);setQuickMessage(reset?`${pairRow.symbol}: Reset naar standaard opgeslagen.`:`${pairRow.symbol}: CUSTOM pair override server-side opgeslagen zonder cycle reset.`);setPairRow(null)}catch(reason){setQuickMessage(reason instanceof Error?reason.message:"Pair override kon niet worden opgeslagen.")}finally{setPairBusy(false)}}

  const chartSelection:TradeSelection=chartRow?{id:`markets:${chartRow.symbol}`,symbol:chartRow.symbol,exchange:"aster",side:""}:{id:"markets:none",symbol:"BTCUSDT",exchange:"aster",side:""};
  return <section className={styles.page} aria-labelledby="markets-title">
    <header className={styles.heading}><div><span className={styles.eyebrow}>ASTER · USDT PERPETUALS</span><h1 id="markets-title">Markets</h1><p>Realtime markten, leverage, Bollinger-status, chart en veilige Strategy 2 quick trades.</p></div><button type="button" className={styles.refresh} onClick={()=>void load(true,false)} disabled={loading||refreshing}>{refreshing?"Verversen…":"↻ Vernieuwen"}</button></header>
    <div className={styles.controlCard}><label className={styles.search}><span>⌕</span><input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Search symbol" aria-label="Search symbol"/></label><div className={styles.timeframes} role="group" aria-label="Bollinger timeframe">{TIMEFRAMES.map(value=><button key={value} type="button" className={timeframe===value?styles.active:""} onClick={()=>setTimeframe(value)}>{value}</button>)}</div><div className={styles.bbFilters} role="group" aria-label="Bollinger Band filter">{BB_FILTERS.map(item=><button key={item.id} type="button" className={bbFilter===item.id?styles.activeFilter:""} onClick={()=>setBbFilter(item.id)}>{item.label}</button>)}</div></div>
    <div className={styles.meta}><span>{data?`${data.marketCount} tradable markten`:"Aster markten"}</span><span>BB 20 · 2σ · {timeframe}</span><span>{enriching&&data?`Data ${enrichedCount}/${data.marketCount}`:`Update ${updated}`}</span></div>
    <div className={styles.sortBar} role="group" aria-label="Markets sortering"><button type="button" onClick={()=>chooseSort("volume")} className={sortKey==="volume"?styles.activeSort:""}>Volume {arrow("volume")}</button><button type="button" onClick={()=>chooseSort("change")} className={sortKey==="change"?styles.activeSort:""}>24h {arrow("change")}</button><button type="button" onClick={()=>chooseSort("leverage")} className={sortKey==="leverage"?styles.activeSort:""}>Leverage {arrow("leverage")}</button><button type="button" onClick={()=>chooseSort("bb")} className={sortKey==="bb"?styles.activeSort:""}>BB {arrow("bb")}</button></div>

    {loading&&!data?<div className={styles.state}><div className={styles.spinner}/><strong>Aster Markets laden</strong><span>Actieve USDT-perpetuals en realtime tickerdata worden opgehaald.</span></div>:error&&!data?<div className={`${styles.state} ${styles.error}`}><strong>Markets tijdelijk niet beschikbaar</strong><span>{error}</span><button type="button" onClick={()=>void load(false,true)}>Opnieuw proberen</button></div>:rows.length===0&&enriching&&bbFilter!=="all"?<div className={styles.state}><div className={styles.spinner}/><strong>Bollinger-data veilig aanvullen</strong><span>BB-data wordt gedoseerd opgehaald om Aster rate-limits te respecteren.</span></div>:rows.length===0?<div className={styles.state}><strong>Geen markten gevonden</strong><span>Pas je zoekterm of Bollinger-filter aan.</span></div>:<div className={styles.list} aria-live="polite">{rows.map(row=>{const active=activeBySymbol[row.symbol]||[];const overrides=asRecord(strategySettings.pairOverrides);const custom=Boolean(overrides[row.symbol]);return <article key={row.symbol} className={styles.row}>
      <button type="button" className={styles.identityButton} onClick={()=>setChartRow(row)} aria-label={`Open chart ${row.symbol}`}><div className={styles.identity}><span className={styles.coin}>{row.baseAsset.slice(0,2)}</span><div><div className={styles.symbolLine}><strong>{row.symbol}</strong><em>{row.maxLeverage!==null?`${row.maxLeverage}x`:"—"}</em>{custom&&<b className={styles.customBadge}>CUSTOM</b>}</div><small>Vol {compactUsd(row.quoteVolume24h)} · Open chart ↗</small></div></div></button>
      <div className={styles.marketPrice}><strong>${price(row.lastPrice)}</strong><span className={row.change24hPct>0?styles.positive:row.change24hPct<0?styles.negative:""}>{signedPercent(row.change24hPct)}</span></div>
      {row.bbStatus&&row.bbUpper!==null&&row.bbMiddle!==null&&row.bbLower!==null?<div className={`${styles.bbBadge} ${styles[row.bbStatus]}`} title={`Upper ${price(row.bbUpper)} · Mid ${price(row.bbMiddle)} · Lower ${price(row.bbLower)}`}><i/>{statusLabel(row.bbStatus)}</div>:<div className={styles.bbBadge} title="Bollinger-data wordt veilig gedoseerd opgehaald"><i/>BB laden</div>}
      {active.length>0&&<div className={styles.activeStatus}>{active.map(side=><span key={side}>ACTIVE {side}</span>)}</div>}
      <div className={styles.quickActions}><button type="button" className={styles.buyLong} disabled={quickBusy||active.includes("LONG")} onClick={()=>void prepareQuickTrade(row,"LONG")}>{active.includes("LONG")?"ACTIVE LONG":"Buy Long"}</button><button type="button" className={styles.buyShort} disabled={quickBusy||active.includes("SHORT")} onClick={()=>void prepareQuickTrade(row,"SHORT")}>{active.includes("SHORT")?"ACTIVE SHORT":"Buy Short"}</button><button type="button" className={styles.pairSettings} onClick={()=>openPairSettings(row)}>⚙</button></div>
    </article>})}</div>}
    {error&&data&&<div className={styles.staleWarning}>{error}</div>}{quickMessage&&<div className={styles.quickMessage}>{quickMessage}</div>}

    {chartRow&&<div className={styles.chartOverlay} role="presentation" onMouseDown={()=>setChartRow(null)}><section className={styles.chartSheet} role="dialog" aria-modal="true" aria-label={`${chartRow.symbol} chart`} onMouseDown={event=>event.stopPropagation()}><header><div><span className={styles.eyebrow}>TRADE CENTER CHART</span><h2>{chartRow.symbol}</h2><p>Dezelfde chartcomponent en Aster candle-datapad als Trade Center.</p></div><button type="button" onClick={()=>setChartRow(null)}>×</button></header><SafeTradingChart selection={chartSelection} mode="aster-detail"/></section></div>}

    {pairRow&&<div className={styles.quickOverlay} role="presentation" onClick={()=>!pairBusy&&setPairRow(null)}><div className={styles.quickSheet} role="dialog" aria-modal="true" aria-label={`${pairRow.symbol} pair override`} onClick={event=>event.stopPropagation()}><span className={styles.eyebrow}>PAIR SETTINGS · CUSTOM</span><h2>{pairRow.symbol}</h2><p>Alleen deze pair. Bestaande fills, entry en dcaCount blijven behouden.</p><div className={styles.pairGrid}><label>Max DCA<input value={pairDraft.maxDca} onChange={event=>setPairDraft({...pairDraft,maxDca:event.target.value})}/></label><label>DCA margin USDT<input value={pairDraft.dcaMarginUsd} onChange={event=>setPairDraft({...pairDraft,dcaMarginUsd:event.target.value})}/></label><label>DCA afstand %<input value={pairDraft.dcaDistancePct} onChange={event=>setPairDraft({...pairDraft,dcaDistancePct:event.target.value})}/></label><label>Take Profit %<input value={pairDraft.takeProfitPct} onChange={event=>setPairDraft({...pairDraft,takeProfitPct:event.target.value})}/></label></div><div className={styles.quickConfirm}><button type="button" disabled={pairBusy} onClick={()=>void savePairOverride(true)}>Reset naar standaard</button><button type="button" disabled={pairBusy} className={styles.buyLong} onClick={()=>void savePairOverride(false)}>{pairBusy?"Opslaan…":"CUSTOM opslaan"}</button></div></div></div>}

    {quickTrade&&<div className={styles.quickOverlay} role="presentation" onClick={()=>!quickBusy&&setQuickTrade(null)}><div className={styles.quickSheet} role="dialog" aria-modal="true" aria-label={`Open ${quickTrade.row.symbol} ${quickTrade.side}?`} onClick={event=>event.stopPropagation()}><span className={styles.eyebrow}>STRATEGY 2 QUICK TRADE</span><h2>Open {quickTrade.row.symbol} {quickTrade.side}?</h2><div className={styles.quickSummary}><span>Profiel <b>STANDARD {quickTrade.side}</b></span><span>Margin <b>${asNumber(quickTrade.effective.entryMarginUsd).toFixed(2)}</b></span><span>Leverage <b>{asNumber(quickTrade.effective.minimumLeverage)}x</b></span><span>Max DCA <b>{String(quickTrade.effective.unlimitedDca===true?"Onbeperkt":quickTrade.effective.maxDca??"—")}</b></span><span>DCA bedrag <b>${asNumber(quickTrade.effective.dcaMarginUsd).toFixed(2)}</b></span><span>TP <b>{(asNumber(quickTrade.effective.takeProfit)*100).toFixed(2)}%</b></span></div><p>OPENING is alleen optimistisch. ACTIVE verschijnt pas na bevestigde Aster fill; bij exchange-afwijzing wordt FAILED gemeld en ontstaat geen tweede cycle.</p><div className={styles.quickConfirm}><button type="button" onClick={()=>setQuickTrade(null)} disabled={quickBusy}>Annuleren</button><button type="button" className={quickTrade.side==="LONG"?styles.buyLong:styles.buyShort} onClick={()=>void confirmQuickTrade()} disabled={quickBusy}>{quickBusy?"OPENING…":`Open ${quickTrade.side}`}</button></div></div></div>}
  </section>;
}
