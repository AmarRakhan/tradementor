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
    ? Math.max(28,Math.min(42,finite(candidate.width,36)-8))
    : Math.max(34,Math.min(58,finite(candidate.width,46)));
  const height=compressed
    ? Math.max(26,Math.min(34,finite(candidate.height,44)-12))
    : Math.max(38,Math.min(50,finite(candidate.height,44)));
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
