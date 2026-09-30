export const EVENT_MARKER_SAFETY_CAP = 160;

function finite(value, fallback=0) {
  const number=Number(value);
  return Number.isFinite(number)?number:fallback;
}

function maybeFinite(value) {
  const number=Number(value);
  return Number.isFinite(number)?number:null;
}

function intersects(a,b,padding=4) {
  return !(a.right+padding<=b.left || b.right+padding<=a.left || a.bottom+padding<=b.top || b.bottom+padding<=a.top);
}

function markerRect(candidate,left,top,compressed=false) {
  const width=compressed
    ? Math.max(32,Math.min(82,finite(candidate.width,44)-6))
    : Math.max(38,Math.min(96,finite(candidate.width,52)));
  const height=compressed
    ? Math.max(24,Math.min(34,finite(candidate.height,36)-6))
    : Math.max(28,Math.min(44,finite(candidate.height,34)));
  return {left:left-width/2,right:left+width/2,top:top-height/2,bottom:top+height/2,width,height};
}

function inside(rect,bounds) {
  return rect.left>=bounds.left && rect.right<=bounds.right && rect.top>=bounds.top && rect.bottom<=bounds.bottom;
}

function envelopeBoundary(candidate,position) {
  const bandTop=maybeFinite(candidate?.bandTop);
  const bandBottom=maybeFinite(candidate?.bandBottom);
  if(position==="above"&&bandTop!==null)return bandTop;
  if(position==="below"&&bandBottom!==null)return bandBottom;
  return null;
}

function outsideEnvelope(rect,candidate,gap=5) {
  const boundary=envelopeBoundary(candidate,String(candidate?.position||"above"));
  if(boundary===null)return true;
  return String(candidate?.position)==="below"
    ? rect.top>=boundary+gap
    : rect.bottom<=boundary-gap;
}

function preferredTop(candidate,height,stackIndex=0) {
  const position=String(candidate?.position)==="below"?"below":"above";
  const boundary=envelopeBoundary(candidate,position);
  const direction=position==="below"?1:-1;
  const stackOffset=stackIndex*(height+4);
  if(boundary!==null){
    return position==="below"
      ? boundary+7+height/2+stackOffset
      : boundary-7-height/2-stackOffset;
  }
  const y=finite(candidate?.y);
  return y+direction*(20+height/2+stackOffset);
}

function clampedFallback(candidate,bounds,occupied,stackIndex=0) {
  for(const compressed of [true,false]){
    const sample=markerRect(candidate,finite(candidate.x),finite(candidate.y),compressed);
    const direction=String(candidate.position)==="below"?1:-1;
    const baseTop=preferredTop(candidate,sample.height,stackIndex);
    for(const outward of [0,8,16,26,38,52,68,86,104]){
      for(const dx of [0,12,-12,24,-24,36,-36,48,-48,60,-60,72,-72]){
        const left=Math.max(bounds.left+sample.width/2,Math.min(bounds.right-sample.width/2,finite(candidate.x)+dx));
        const top=Math.max(bounds.top+sample.height/2,Math.min(bounds.bottom-sample.height/2,baseTop+direction*outward));
        const rect=markerRect(candidate,left,top,compressed);
        if(!inside(rect,bounds))continue;
        if(!outsideEnvelope(rect,candidate,4))continue;
        if(occupied.some((other)=>intersects(rect,other,compressed?1:2)))continue;
        return {...candidate,left,top,rect,compact:false,compressed};
      }
    }
  }

  // Never hide a normal visible event merely because the viewport is crowded.
  // Last-resort placement stays deterministic and outside the Bollinger envelope
  // when that geometry exists, even if a rare dense viewport must tolerate overlap.
  const compressed=true;
  const sample=markerRect(candidate,finite(candidate.x),finite(candidate.y),compressed);
  const position=String(candidate.position)==="below"?"below":"above";
  const direction=position==="below"?1:-1;
  const boundary=envelopeBoundary(candidate,position);
  let top=preferredTop(candidate,sample.height,stackIndex);
  if(boundary!==null){
    top=position==="below"
      ? Math.max(top,boundary+4+sample.height/2)
      : Math.min(top,boundary-4-sample.height/2);
  }
  top=Math.max(bounds.top+sample.height/2,Math.min(bounds.bottom-sample.height/2,top));
  const left=Math.max(bounds.left+sample.width/2,Math.min(bounds.right-sample.width/2,finite(candidate.x)));
  const rect=markerRect(candidate,left,top,compressed);
  return {...candidate,left,top,rect,compact:false,compressed,collisionFallback:true};
}

export function eventPriority(row) {
  const kind=String(row?.kind||"").toLowerCase();
  const base=kind==="entry"?300:kind==="tp"?220:kind==="cashflow"?100:150;
  const notional=Math.abs(finite(row?.notionalUsd))+Math.abs(finite(row?.realizedPnlUsd))*25;
  return base+Math.min(25,Math.log10(1+notional)*5);
}


function referenceMarkerScore(row) {
  const count=Math.max(1,Math.floor(finite(row?.eventCount,1)));
  const pnl=Math.abs(finite(row?.realizedPnlUsd));
  const priority=finite(row?.priority,eventPriority(row));
  return count*1000+Math.min(500,pnl*25)+priority;
}

function pickReferenceSpread(rows,cap) {
  const limit=Math.max(0,Math.floor(finite(cap)));
  const clean=(Array.isArray(rows)?rows:[])
    .filter((row)=>row&&Number.isFinite(Number(row.time)))
    .slice()
    .sort((a,b)=>finite(a.time)-finite(b.time)||finite(a.x)-finite(b.x));
  if(limit<=0)return [];
  if(clean.length<=limit)return clean;
  const picked=[];
  for(let bucket=0;bucket<limit;bucket+=1){
    const start=Math.floor(bucket*clean.length/limit);
    const end=Math.max(start+1,Math.floor((bucket+1)*clean.length/limit));
    const segment=clean.slice(start,Math.min(clean.length,end));
    const best=segment.reduce((winner,row)=>{
      if(!winner)return row;
      const delta=referenceMarkerScore(row)-referenceMarkerScore(winner);
      if(delta!==0)return delta>0?row:winner;
      return finite(row.time)>=finite(winner.time)?row:winner;
    },null);
    if(best)picked.push(best);
  }
  return picked.sort((a,b)=>finite(a.time)-finite(b.time)||finite(a.x)-finite(b.x));
}

export function selectPortfolioKoersReferenceCandidates(candidates,{tp=3,long=2,short=2,cashflow=1,other=1}={}) {
  const rows=(Array.isArray(candidates)?candidates:[]).filter((row)=>row&&Number.isFinite(Number(row.x))&&Number.isFinite(Number(row.y)));
  const groups={
    tp:rows.filter((row)=>String(row.tone)==="tp"),
    long:rows.filter((row)=>String(row.tone)==="long"),
    short:rows.filter((row)=>String(row.tone)==="short"),
    cashflow:rows.filter((row)=>String(row.tone)==="cashflow"),
    other:rows.filter((row)=>!["tp","long","short","cashflow"].includes(String(row.tone))),
  };
  return [
    ...pickReferenceSpread(groups.tp,tp),
    ...pickReferenceSpread(groups.long,long),
    ...pickReferenceSpread(groups.short,short),
    ...pickReferenceSpread(groups.cashflow,cashflow),
    ...pickReferenceSpread(groups.other,other),
  ].sort((a,b)=>finite(a.time)-finite(b.time)||finite(b.priority)-finite(a.priority));
}

export function layoutPortfolioKoersMarkers(candidates,viewport,{priceAxisWidth=48,safetyCap=EVENT_MARKER_SAFETY_CAP}={}) {
  const width=Math.max(1,finite(viewport?.width,1));
  const height=Math.max(1,finite(viewport?.height,1));
  const bounds={left:14,right:Math.max(15,width-priceAxisWidth-3),top:8,bottom:height-12};
  const clean=(Array.isArray(candidates)?candidates:[])
    .filter((row)=>row&&Number.isFinite(Number(row.x))&&Number.isFinite(Number(row.y)))
    .map((row,index)=>({...row,index,priority:finite(row.priority,eventPriority(row)),time:finite(row.time)}))
    .sort((a,b)=>a.time-b.time || b.priority-a.priority || a.index-b.index)
    .slice(0,Math.max(1,Math.floor(finite(safetyCap,EVENT_MARKER_SAFETY_CAP))));

  const groups=new Map();
  for(const candidate of clean){
    const key=String(candidate.time);
    if(!groups.has(key))groups.set(key,[]);
    groups.get(key).push(candidate);
  }

  const placed=[];
  const occupied=[];
  for(const rows of groups.values()){
    rows.sort((a,b)=>b.priority-a.priority || a.index-b.index);
    const aboveRows=rows.filter((row)=>String(row.position)!=="below");
    const belowRows=rows.filter((row)=>String(row.position)==="below");
    for(const sideRows of [aboveRows,belowRows]){
      for(let stackIndex=0;stackIndex<sideRows.length;stackIndex+=1){
        const candidate=sideRows[stackIndex];
        const label=clampedFallback(candidate,bounds,occupied,stackIndex);
        placed.push(label);
        occupied.push(label.rect);
      }
    }
  }

  return {
    full:placed,
    compact:[],
    all:placed,
    visibleEventCount:clean.length,
    safetyCapApplied:clean.length<(Array.isArray(candidates)?candidates.length:0),
  };
}

export function markerRectsOverlap(labels) {
  const rows=(Array.isArray(labels)?labels:[]).filter((row)=>row?.rect);
  for(let i=0;i<rows.length;i+=1){
    for(let j=i+1;j<rows.length;j+=1){
      if(intersects(rows[i].rect,rows[j].rect,0))return true;
    }
  }
  return false;
}

export function markerRectInsideBollinger(label,gap=0) {
  if(!label?.rect)return false;
  const top=maybeFinite(label.bandTop),bottom=maybeFinite(label.bandBottom);
  if(top===null||bottom===null)return false;
  return !(label.rect.bottom<=top-gap || label.rect.top>=bottom+gap);
}

export function layoutPortfolioKoersZoneRegions(zoneCoordinates,height) {
  const limit=Math.max(1,finite(height,1));
  const ordered=(Array.isArray(zoneCoordinates)?zoneCoordinates:[])
    .filter((row)=>row&&Number.isFinite(Number(row.centerY)))
    .map((row)=>({...row,centerY:finite(row.centerY),upperY:finite(row.upperY,row.centerY),lowerY:finite(row.lowerY,row.centerY)}))
    .sort((a,b)=>a.centerY-b.centerY);
  const total=ordered.length;
  if(!total)return [];
  return ordered.map((row,index)=>{
    const previous=ordered[index-1],next=ordered[index+1];
    const ownTop=Math.min(row.upperY,row.lowerY,row.centerY);
    const ownBottom=Math.max(row.upperY,row.lowerY,row.centerY);
    const top=index===0?Math.max(0,ownTop):Math.max(0,(previous.centerY+row.centerY)/2);
    const bottom=index===total-1?Math.min(limit,ownBottom):Math.min(limit,(row.centerY+next.centerY)/2);
    return {
      ...row,
      top,
      height:Math.max(2,bottom-top),
      tone:zoneToneForRank(index,total),
      regionSource:"confirmed-zone-centers",
    };
  }).filter((row)=>row.height>1&&row.top<limit);
}

export function zoneToneForRank(rank,total) {
  const count=Math.max(1,Math.floor(finite(total,1)));
  const position=count===1?.5:Math.max(0,Math.min(1,finite(rank)/(count-1)));
  if(position<.25)return "red";
  if(position<.5)return "amber";
  if(position<.75)return "green";
  return "blue";
}
