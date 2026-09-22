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

export function portfolioZoneForPrice(zones, price) {
  const rows=Array.isArray(zones)?zones:[], value=finite(price);
  if(value<=0||!rows.length) return null;
  const inside=rows.find((row)=>finite(row.lower)<=value&&value<=finite(row.upper));
  if(inside) return Math.trunc(finite(inside.index));
  return Math.trunc(finite(rows.reduce((best,row)=>Math.abs(finite(row.center)-value)<Math.abs(finite(best.center)-value)?row:best).index));
}

export function markerVisual(row) {
  const kind=String(row?.kind||"").toLowerCase(), side=String(row?.side||"").toUpperCase();
  if(kind==="cashflow") return {position:"aboveBar",shape:"square",tone:"cashflow",text:String(row.label||"BALANS")};
  if(kind==="entry"&&side==="LONG") return {position:"belowBar",shape:"arrowUp",tone:"long",text:String(row.label||"ENTRY L")};
  if(kind==="entry"&&side==="SHORT") return {position:"aboveBar",shape:"arrowDown",tone:"short",text:String(row.label||"ENTRY S")};
  return {position:"aboveBar",shape:"circle",tone:"tp",text:String(row?.label||"TP")};
}
