export type MarkerCandle={time:number;open:number;high:number;low:number;close:number};
export type VerifiedTradeEvent={id:string;side:"LONG"|"SHORT";kind:"entry"|"dca"|"close"|"hedge";action:"increase"|"close";price:number;at:string;timestampMs:number;quantity?:number;notional?:number;dcaNumber?:number;realizedPnl?:number;exchange?:string};
export type TradeMarkerGroup={time:number;displayPrice:number;placement:"above"|"below";color:string;shape:"arrowUp"|"arrowDown";events:VerifiedTradeEvent[]};

function bands(candles:MarkerCandle[],period=20,deviation=2){
  const out=new Map<number,{upper:number;lower:number}>();
  for(let i=period-1;i<candles.length;i++){
    const values=candles.slice(i-period+1,i+1).map(row=>row.close),mean=values.reduce((a,b)=>a+b,0)/period;
    const sd=Math.sqrt(values.reduce((sum,value)=>sum+(value-mean)**2,0)/period);
    out.set(candles[i].time,{upper:mean+deviation*sd,lower:mean-deviation*sd});
  }
  return out;
}

export function layoutVerifiedTradeMarkers(candles:MarkerCandle[],events:VerifiedTradeEvent[],bollingerVisible:boolean):TradeMarkerGroup[]{
  if(!candles.length)return[];
  const bb=bollingerVisible?bands(candles):new Map<number,{upper:number;lower:number}>(),groups=new Map<string,TradeMarkerGroup>();
  for(const event of events){
    const target=event.timestampMs/1000;
    const candle=candles.reduce((best,row)=>Math.abs(row.time-target)<Math.abs(best.time-target)?row:best,candles[0]);
    const short=event.side==="SHORT",increase=event.action==="increase";
    const placement:("above"|"below")=increase?(short?"above":"below"):(short?"below":"above");
    const range=Math.max(candle.high-candle.low,Math.abs(candle.close)*0.001),margin=Math.max(range*.2,Math.abs(candle.close)*0.0004);
    const band=bb.get(candle.time);
    const displayPrice=placement==="above"?Math.max(candle.high,band?.upper??candle.high)+margin:Math.min(candle.low,band?.lower??candle.low)-margin;
    const key=`${candle.time}:${placement}`;const existing=groups.get(key);
    if(existing){existing.events.push(event);existing.displayPrice=placement==="above"?Math.max(existing.displayPrice,displayPrice):Math.min(existing.displayPrice,displayPrice);continue;}
    groups.set(key,{time:candle.time,displayPrice,placement,color:placement==="above"?"#ff5578":"#21d6a2",shape:placement==="above"?"arrowDown":"arrowUp",events:[event]});
  }
  return [...groups.values()].sort((a,b)=>a.time-b.time);
}
