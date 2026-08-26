"use client";

export function AsterStrategy2FocusPairSelector({rows,value,onChange}:{rows:Record<string,unknown>[];value:string;onChange:(symbol:string)=>void}){
 const selected=value.toUpperCase().trim();
 const eligible=rows.filter(row=>row.eligible!==false&&String(row.symbol||"").trim());
 return <div>
  <div style={{maxHeight:280,overflowY:"auto",display:"grid",gap:6,paddingRight:4}} aria-label="Focus pair selecteren">
   {eligible.length===0&&<small>Nog geen actuele Focus-ranking beschikbaar. Zet Focus Shadow kort aan om de lijst te laden.</small>}
   {eligible.map((row,index)=>{const symbol=String(row.symbol||"").toUpperCase();const active=symbol===selected;const change=Number(row.change_24h_pct??row.change24hPct??0)*100;const price=Number(row.price||0);return <button key={symbol} type="button" onClick={()=>onChange(symbol)} aria-pressed={active} className="strategy-message" style={{textAlign:"left",cursor:"pointer",outline:active?"2px solid currentColor":"none"}}>
    <b>{index+1}. {symbol}</b><br/><small>{Number.isFinite(change)?`${change>=0?"+":""}${change.toFixed(2)}% 24u`:"—"} · {price>0?`$${price.toLocaleString(undefined,{maximumFractionDigits:8})}`:"prijs —"}{active?" · GESELECTEERD":""}</small>
   </button>})}
  </div>
 </div>
}
