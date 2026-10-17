"use client";
import { useMemo, useState } from "react";

/** UI-only preview; deliberately no settings writes or exchange actions. */
export function ShortRecoveryPlanPreview() {
  const [flipped, setFlipped] = useState(false);
  const [distance, setDistance] = useState("3");
  const [steps, setSteps] = useState("4");
  const n = Number(steps), gap = Number(distance);
  const valid = Number.isInteger(n) && n>=1 && n<=100 && Number.isFinite(gap) && gap>0 && n*gap<100;
  const levels = useMemo(()=>valid?Array.from({length:n},(_,i)=>({
    index:i+1, level:(i+1)*gap, closed:(i+1)*100/n
  })):[],[n,gap,valid]);
  return <section aria-label="SHORT Recovery Plan voorbeeld" style={{margin:"16px 0",perspective:1200}}>
    <div style={{position:"relative",minHeight:flipped?310:245,transition:"min-height .2s"}}>
      <div style={{position:"relative",transformStyle:"preserve-3d",transform:flipped?"rotateY(180deg)":"rotateY(0)",transition:"transform .65s ease"}}>
        <div style={{backfaceVisibility:"hidden",padding:18,border:"1px solid #b89343",borderRadius:20,background:"#111b18",color:"#e8dfc7",minHeight:245}}>
          <strong style={{color:"#d6b75c"}}>SHORT RECOVERY PLAN</strong>
          <label style={{display:"flex",alignItems:"center",gap:8,marginTop:12,fontSize:13}}>
            <input type="checkbox" checked={false} disabled aria-label="SHORT Recovery activeren (nog niet beschikbaar)" />
            <span>SHORT Recovery activeren — UIT (veiligheidstests nog bezig)</span>
          </label>
          <p style={{fontSize:12,opacity:.8}}>Extra afbouwfunctie · voorlopig alleen voorbeeld, geen orders</p>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
            <label>Koersdaling per stap (%)<input aria-label="Koersdaling per stap" type="number" min=".01" step=".1" value={distance} onChange={e=>setDistance(e.target.value)} style={{width:"100%",padding:8,borderRadius:8,color:"white",background:"#25332d"}} /></label>
            <label>Aantal afbouwstappen<input aria-label="Aantal afbouwstappen" type="number" min="1" max="100" step="1" value={steps} onChange={e=>setSteps(e.target.value)} style={{width:"100%",padding:8,borderRadius:8,color:"white",background:"#25332d"}} /></label>
          </div>
          {valid?<p style={{marginTop:12}}>Per stap <b>{(100/n).toLocaleString("nl-NL",{maximumFractionDigits:4})}% SHORT</b> · laatste niveau <b>−{(n*gap).toLocaleString("nl-NL")}%</b></p>:<p role="alert" style={{color:"#ff8f8f"}}>Ongeldige combinatie: laatste koersniveau moet boven nul blijven.</p>}
          <button type="button" onClick={()=>setFlipped(true)} style={{border:"1px solid #bd9650",borderRadius:10,padding:10,marginTop:12,color:"#e7c66b",background:"#17261d"}}>Draai kaart ↻</button>
        </div>
        <div style={{position:"absolute",inset:0,backfaceVisibility:"hidden",transform:"rotateY(180deg)",padding:18,border:"1px solid #b89343",borderRadius:20,background:"#111b18",color:"#e8dfc7",minHeight:310}}>
          <strong style={{color:"#d6b75c"}}>AFBOUWCYCLUS</strong>
          <div style={{overflowY:"auto",maxHeight:215,marginTop:12}}>
            {levels.map(x=><div key={x.index} style={{padding:"6px 0",borderBottom:"1px solid #354438"}}>Stap {x.index}: koers −{x.level.toLocaleString("nl-NL")}% · SHORT {Math.max(0,100-x.closed).toLocaleString("nl-NL",{maximumFractionDigits:2})}% over</div>)}
          </div>
          <p style={{fontSize:12}}>Na de laatste bevestigde SHORT-sluiting: netto TP controleren, anders nieuwe 1:1 hedge.</p>
          <button type="button" onClick={()=>setFlipped(false)} style={{border:"1px solid #bd9650",borderRadius:10,padding:10,color:"#e7c66b",background:"#17261d"}}>↶ Instellingen</button>
        </div>
      </div>
    </div>
  </section>;
}
