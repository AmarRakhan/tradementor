export const PORTFOLIO_KOERS_TIMEFRAMES = Object.freeze(["1m","5m","15m","1u","4u","24u"]);
export const PORTFOLIO_KOERS_DEFAULT_TIMEFRAME = "15m";
export const PORTFOLIO_KOERS_TIMEFRAME_SECONDS = Object.freeze({
  "1m":60,"5m":300,"15m":900,"1u":3600,"4u":14400,"24u":86400,
});

function finite(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

export function normalizePortfolioKoersPayload(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  const byTime = new Map();
  for (const row of Array.isArray(source.candles) ? source.candles : []) {
    if (!row || typeof row !== "object") continue;
    const time = Math.floor(finite(row.time));
    const open = finite(row.open), high = finite(row.high), low = finite(row.low), close = finite(row.close);
    if (time <= 0 || Math.min(open,high,low,close) <= 0 || high < low || high < Math.max(open,close) || low > Math.min(open,close)) continue;
    byTime.set(time, { time, atMs: Math.floor(finite(row.atMs)) || time*1000, open, high, low, close, samples: Math.max(1,Math.floor(finite(row.samples))), sourceAtMs: Math.floor(finite(row.sourceAtMs)) });
  }
  const candles = [...byTime.values()].sort((a,b)=>a.time-b.time);
  const markers = (Array.isArray(source.markers) ? source.markers : []).filter((row)=>row && typeof row==="object" && finite(row.time)>0).map((row)=>({
    ...row, time:Math.floor(finite(row.time)), atMs:Math.floor(finite(row.atMs)) || Math.floor(finite(row.time))*1000,
    count:Math.max(1,Math.floor(finite(row.count))), notionalUsd:finite(row.notionalUsd), realizedPnlUsd:finite(row.realizedPnlUsd), amountUsd:finite(row.amountUsd),
  })).sort((a,b)=>a.time-b.time);
  const zones = (Array.isArray(source.zones) ? source.zones : []).filter((row)=>row && typeof row==="object").map((row)=>({
    index:Math.trunc(finite(row.index)), label:String(row.label||""), center:finite(row.center), lower:finite(row.lower), upper:finite(row.upper),
    touches:Math.max(0,Math.floor(finite(row.touches))), atr:finite(row.atr), source:String(row.source||""),
  })).filter((row)=>row.center>0 && row.lower>0 && row.upper>=row.lower).sort((a,b)=>a.index-b.index);
  return {
    timeframe:PORTFOLIO_KOERS_TIMEFRAMES.includes(String(source.timeframe)) ? String(source.timeframe) : PORTFOLIO_KOERS_DEFAULT_TIMEFRAME,
    candles, markers, zones,
    currentZone:Number.isInteger(source.currentZone) ? Number(source.currentZone) : null,
    cycleStartEquity:finite(source.cycleStartEquity) || null,
    currentEquity:finite(source.currentEquity) || null,
    snapshotAtMs:Math.floor(finite(source.snapshotAtMs)) || null,
    live:source.live===true,
    persistent:source.persistent===true,
    externalCashflowsSeparated:source.externalCashflowsSeparated===true,
    readOnly:source.readOnly===true,
    ordersSent:Math.max(0,Math.floor(finite(source.ordersSent))),
    source:String(source.source||""),
  };
}

export function bollinger20x2(candles) {
  const clean = Array.isArray(candles) ? candles : [];
  const period=20, multiplier=2, upper=[], middle=[], lower=[];
  for(let index=period-1;index<clean.length;index+=1){
    const window=clean.slice(index-period+1,index+1).map((row)=>finite(row.close));
    if(window.some((value)=>value<=0)) continue;
    const mean=window.reduce((sum,value)=>sum+value,0)/period;
    const variance=window.reduce((sum,value)=>sum+((value-mean)**2),0)/period;
    const deviation=Math.sqrt(variance);
    const time=Math.floor(finite(clean[index].time));
    upper.push({time,value:mean+multiplier*deviation});
    middle.push({time,value:mean});
    lower.push({time,value:mean-multiplier*deviation});
  }
  return {upper,middle,lower,period,multiplier};
}

export function parsePortfolioEquityText(text) {
  const raw=String(text??"").trim().replace(/\s/g,"").replace(/[^0-9,.-]/g,"");
  if(!raw) return null;
  const lastComma=raw.lastIndexOf(","), lastDot=raw.lastIndexOf(".");
  let normalized=raw;
  if(lastComma>=0 && lastDot>=0){
    if(lastComma>lastDot) normalized=raw.replace(/\./g,"").replace(",",".");
    else normalized=raw.replace(/,/g,"");
  } else if(lastComma>=0) {
    const decimals=raw.length-lastComma-1;
    normalized=decimals===3 && lastComma>0 ? raw.replace(/,/g,"") : raw.replace(",",".");
  } else if((raw.match(/\./g)||[]).length>1) {
    const parts=raw.split(".");
    normalized=parts.slice(0,-1).join("")+"."+parts.at(-1);
  }
  const value=Number(normalized);
  return Number.isFinite(value)&&value>0?value:null;
}

export function aggregatePortfolioEquityHistory(rows, timeframe, limit=320) {
  const step=PORTFOLIO_KOERS_TIMEFRAME_SECONDS[String(timeframe)];
  if(!step) return [];
  const buckets=new Map();
  for(const raw of Array.isArray(rows)?rows:[]) {
    if(!raw || typeof raw!=="object") continue;
    const stamp=Math.floor(finite(raw.at));
    const value=finite(raw.aster);
    if(stamp<=0 || value<=0) continue;
    const time=Math.floor(stamp/1000/step)*step;
    const previous=buckets.get(time);
    if(!previous) {
      buckets.set(time,{time,atMs:time*1000,open:value,high:value,low:value,close:value,samples:1,sourceAtMs:stamp});
      continue;
    }
    previous.high=Math.max(previous.high,value);
    previous.low=Math.min(previous.low,value);
    previous.close=value;
    previous.samples+=1;
    previous.sourceAtMs=Math.max(previous.sourceAtMs,stamp);
  }
  return [...buckets.values()].sort((a,b)=>a.time-b.time).slice(-Math.max(1,Math.floor(finite(limit))||320));
}

export function mergePortfolioKoersCandles(browserCandles, serverCandles, limit=320) {
  const byTime=new Map();
  for(const source of [browserCandles,serverCandles]) {
    for(const raw of Array.isArray(source)?source:[]) {
      if(!raw || typeof raw!=="object") continue;
      const time=Math.floor(finite(raw.time));
      const open=finite(raw.open),high=finite(raw.high),low=finite(raw.low),close=finite(raw.close);
      if(time<=0 || Math.min(open,high,low,close)<=0 || high<low) continue;
      byTime.set(time,{...raw,time,atMs:Math.floor(finite(raw.atMs))||time*1000,open,high,low,close});
    }
  }
  return [...byTime.values()].sort((a,b)=>a.time-b.time).slice(-Math.max(1,Math.floor(finite(limit))||320));
}

export function mergeRealtimeEquitySample(candles, equity, atMs, timeframe) {
  const rows=(Array.isArray(candles)?candles:[]).map((row)=>({...row}));
  const value=finite(equity), stamp=Math.floor(finite(atMs)), step=PORTFOLIO_KOERS_TIMEFRAME_SECONDS[String(timeframe)];
  if(value<=0||stamp<=0||!step) return rows;
  const time=Math.floor(stamp/1000/step)*step;
  const last=rows.at(-1);
  if(!last || time>finite(last.time)){
    rows.push({time,atMs:time*1000,open:value,high:value,low:value,close:value,samples:1,sourceAtMs:stamp});
    return rows;
  }
  if(time<finite(last.time)) return rows;
  rows[rows.length-1]={...last,high:Math.max(finite(last.high),value),low:Math.min(finite(last.low),value),close:value,sourceAtMs:stamp};
  return rows;
}

export function portfolioKoersTimelineHealth(candles, timeframe, nowMs=Date.now(), requiredContiguousBars=14) {
  const step=PORTFOLIO_KOERS_TIMEFRAME_SECONDS[String(timeframe)];
  const required=Math.max(1,Math.floor(finite(requiredContiguousBars))||14);
  const rows=(Array.isArray(candles)?candles:[])
    .filter((row)=>row&&typeof row==="object"&&finite(row.time)>0)
    .map((row)=>({...row,time:Math.floor(finite(row.time))}))
    .sort((a,b)=>a.time-b.time);
  if(!step||!rows.length){
    return {healthy:false,safeForAdvisor:false,stepSeconds:step||0,requiredContiguousBars:required,contiguousBars:0,latestTime:null,currentBucketTime:null,gaps:[]};
  }
  const gaps=[];
  let contiguousStart=0;
  for(let index=1;index<rows.length;index+=1){
    const previous=rows[index-1].time,current=rows[index].time,delta=current-previous;
    if(delta>step){
      const missingBars=Math.max(1,Math.ceil(delta/step)-1);
      gaps.push({afterTime:previous,beforeTime:current,fromTime:previous+step,toTime:current-step,missingBars});
      contiguousStart=index;
    }
  }
  const latestTime=rows.at(-1).time;
  const stamp=Math.floor(finite(nowMs));
  const currentBucketTime=stamp>0?Math.floor(stamp/1000/step)*step:latestTime;
  const contiguousBars=rows.length-contiguousStart;
  const latestFresh=latestTime>=currentBucketTime;
  const safeForAdvisor=latestFresh&&contiguousBars>=required;
  return {
    healthy:latestFresh&&gaps.length===0,
    safeForAdvisor,
    stepSeconds:step,
    requiredContiguousBars:required,
    contiguousBars,
    latestTime,
    currentBucketTime,
    gaps,
  };
}

export function portfolioZoneForPrice(zones, price) {
  const rows=Array.isArray(zones)?zones:[], value=finite(price);
  if(value<=0||!rows.length) return null;
  const inside=rows.find((row)=>finite(row.lower)<=value&&value<=finite(row.upper));
  if(inside) return Math.trunc(finite(inside.index));
  return Math.trunc(finite(rows.reduce((best,row)=>Math.abs(finite(row.center)-value)<Math.abs(finite(best.center)-value)?row:best).index));
}

export function portfolioZoneDistancePercent(boundaryPrice, currentPrice) {
  const boundary=Number(boundaryPrice), current=Number(currentPrice);
  if(!Number.isFinite(boundary)||!Number.isFinite(current)||current<=0) return null;
  return ((boundary-current)/current)*100;
}

export function portfolioZoneProgress(currentPrice, lowerBoundary, upperBoundary) {
  const current=Number(currentPrice), lower=Number(lowerBoundary), upper=Number(upperBoundary);
  if(!Number.isFinite(current)||!Number.isFinite(lower)||!Number.isFinite(upper)||upper<=lower) return null;
  return Math.max(0,Math.min(100,((current-lower)/(upper-lower))*100));
}

export function portfolioKoersFocusBars(candles, maxVisibleBars, currentPrice, lowerBoundary, upperBoundary) {
  const rows=Array.isArray(candles)?candles:[];
  const requested=Math.max(1,Math.floor(Number(maxVisibleBars))||rows.length||1);
  const maxBars=Math.min(rows.length,requested);
  if(maxBars<=1) return maxBars;

  const current=Number(currentPrice), lower=Number(lowerBoundary), upper=Number(upperBoundary);
  if(!Number.isFinite(current)||current<=0||!Number.isFinite(lower)||!Number.isFinite(upper)||lower<=0||upper<=lower) return maxBars;

  const span=Math.max(upper-lower,current*0.006);
  const padding=Math.max(span*0.65,current*0.004);
  const focusFloor=Math.max(Number.EPSILON,lower-padding);
  const focusCeiling=upper+padding;
  const minBars=Math.min(maxBars,Math.max(6,Math.round(maxBars*0.35)));
  let visible=0;

  for(let index=rows.length-1;index>=0&&visible<maxBars;index-=1){
    const row=rows[index]||{};
    const low=Number(row.low),high=Number(row.high);
    const outside=Number.isFinite(low)&&Number.isFinite(high)&&low>0&&high>0&&(low<focusFloor||high>focusCeiling);
    if(visible>=minBars&&outside) break;
    visible+=1;
  }
  return Math.max(1,Math.min(maxBars,Math.max(minBars,visible)));
}

export function markerVisual(row) {
  const kind=String(row?.kind||"").toLowerCase(), side=String(row?.side||"").toUpperCase();
  if(kind==="cashflow") return {position:"aboveBar",shape:"square",tone:"cashflow",text:String(row.label||"BALANS")};
  if(kind==="entry"&&side==="LONG") return {position:"belowBar",shape:"arrowUp",tone:"long",text:String(row.label||"ENTRY L")};
  if(kind==="entry"&&side==="SHORT") return {position:"aboveBar",shape:"arrowDown",tone:"short",text:String(row.label||"ENTRY S")};
  return {position:"aboveBar",shape:"circle",tone:"tp",text:String(row?.label||"TP")};
}
