export const MAX_FULL_EVENT_LABELS = 3;
export const MAX_COMPACT_EVENT_CLUSTERS = 2;

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

function fullRect(candidate,left,top) {
  const width=Math.max(24,Math.min(52,finite(candidate.width,36)));
  const height=Math.max(18,Math.min(26,finite(candidate.height,22)));
  return {left:left-width/2,right:left+width/2,top:top-height/2,bottom:top+height/2,width,height};
}

function compactRect(left,top,eventCount=1) {
  const width=Math.max(28,Math.min(48,24+String(Math.max(1,eventCount)).length*6));
  const height=18;
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

function preferredTop(candidate,height) {
  const position=String(candidate?.position)==="below"?"below":"above";
  const boundary=envelopeBoundary(candidate,position);
  if(boundary!==null){
    return position==="below"
      ? boundary+8+height/2
      : boundary-8-height/2;
  }
  const y=finite(candidate?.y);
  return y+(position==="below"?1:-1)*(22+height/2);
}

export function eventPriority(row) {
  const kind=String(row?.kind||"").toLowerCase();
  const base=kind==="entry"?300:kind==="tp"?220:kind==="cashflow"?100:150;
  const notional=Math.abs(finite(row?.notionalUsd))+Math.abs(finite(row?.realizedPnlUsd))*25;
  return base+Math.min(25,Math.log10(1+notional)*5);
}

export function layoutPortfolioKoersMarkers(candidates,viewport,{maxFull=MAX_FULL_EVENT_LABELS,maxCompact=MAX_COMPACT_EVENT_CLUSTERS,priceAxisWidth=48}={}) {
  const width=Math.max(1,finite(viewport?.width,1));
  const height=Math.max(1,finite(viewport?.height,1));
  const bounds={left:14,right:Math.max(15,width-priceAxisWidth-3),top:8,bottom:height-12};
  const ordered=(Array.isArray(candidates)?candidates:[])
    .filter((row)=>row&&Number.isFinite(Number(row.x))&&Number.isFinite(Number(row.y)))
    .map((row,index)=>({...row,index,priority:finite(row.priority,eventPriority(row)),time:finite(row.time)}))
    .sort((a,b)=>b.priority-a.priority || b.time-a.time || b.index-a.index);

  const full=[];
  const compactPool=[];
  const occupied=[];
  const horizontalOffsets=[0,18,-18,32,-32];
  const outwardOffsets=[0,10,20,32];

  for(const candidate of ordered){
    if(full.length>=Math.max(0,maxFull)){compactPool.push(candidate);continue}
    const sampleRect=fullRect(candidate,finite(candidate.x),finite(candidate.y));
    const baseTop=preferredTop(candidate,sampleRect.height);
    const direction=String(candidate.position)==="below"?1:-1;
    let placed=null;
    for(const outward of outwardOffsets){
      for(const dx of horizontalOffsets){
        const left=finite(candidate.x)+dx;
        const top=baseTop+direction*outward;
        const rect=fullRect(candidate,left,top);
        if(!inside(rect,bounds))continue;
        if(!outsideEnvelope(rect,candidate,5))continue;
        if(occupied.some((other)=>intersects(rect,other,3)))continue;
        placed={...candidate,left,top,rect,compact:false};
        break;
      }
      if(placed)break;
    }
    if(placed){full.push(placed);occupied.push(placed.rect)}
    else compactPool.push(candidate);
  }

  const clusterMap=new Map();
  for(const candidate of compactPool){
    const position=String(candidate.position)==="below"?"below":"above";
    const x=Math.max(bounds.left,Math.min(bounds.right,finite(candidate.x)));
    const boundary=envelopeBoundary(candidate,position);
    const y=boundary===null
      ? Math.max(bounds.top+10,Math.min(bounds.bottom-10,finite(candidate.y)))
      : boundary+(position==="below"?14:-14);
    const key=`${position}:${Math.round(x/92)}:${Math.round(y/66)}`;
    const existing=clusterMap.get(key)||{
      xTotal:0,yTotal:0,rows:[],eventCount:0,priority:0,latestTime:0,position,
      bandTop:position==="above"?Infinity:null,
      bandBottom:position==="below"?-Infinity:null,
    };
    existing.xTotal+=x;
    existing.yTotal+=y;
    existing.rows.push(candidate);
    existing.eventCount+=Math.max(1,Math.floor(finite(candidate.eventCount,1)));
    existing.priority=Math.max(existing.priority,finite(candidate.priority,eventPriority(candidate)));
    existing.latestTime=Math.max(existing.latestTime,finite(candidate.time));
    const top=maybeFinite(candidate.bandTop),bottom=maybeFinite(candidate.bandBottom);
    if(position==="above"&&top!==null)existing.bandTop=Math.min(existing.bandTop,top);
    if(position==="below"&&bottom!==null)existing.bandBottom=Math.max(existing.bandBottom,bottom);
    clusterMap.set(key,existing);
  }

  const clusters=[...clusterMap.values()].sort((a,b)=>b.priority-a.priority||b.latestTime-a.latestTime);
  const kept=clusters.slice(0,Math.max(0,maxCompact));
  for(const overflow of clusters.slice(kept.length)){
    if(!kept.length){kept.push(overflow);continue}
    const sameSide=kept.filter((row)=>row.position===overflow.position);
    const targets=sameSide.length?sameSide:kept;
    const overflowX=overflow.xTotal/Math.max(1,overflow.rows.length);
    let target=targets[0];
    let distance=Math.abs(target.xTotal/Math.max(1,target.rows.length)-overflowX);
    for(const candidate of targets.slice(1)){
      const nextDistance=Math.abs(candidate.xTotal/Math.max(1,candidate.rows.length)-overflowX);
      if(nextDistance<distance){target=candidate;distance=nextDistance}
    }
    target.xTotal+=overflow.xTotal;
    target.yTotal+=overflow.yTotal;
    target.rows.push(...overflow.rows);
    target.eventCount+=overflow.eventCount;
    target.priority=Math.max(target.priority,overflow.priority);
    target.latestTime=Math.max(target.latestTime,overflow.latestTime);
    if(target.position==="above"&&Number.isFinite(overflow.bandTop))target.bandTop=Math.min(target.bandTop,overflow.bandTop);
    if(target.position==="below"&&Number.isFinite(overflow.bandBottom))target.bandBottom=Math.max(target.bandBottom,overflow.bandBottom);
  }

  const compact=[];
  for(let index=0;index<kept.length;index+=1){
    const cluster=kept[index];
    const count=Math.max(1,cluster.rows.length);
    const baseLeft=cluster.xTotal/count;
    const direction=cluster.position==="below"?1:-1;
    const boundary=cluster.position==="below"&&Number.isFinite(cluster.bandBottom)
      ? cluster.bandBottom
      : cluster.position==="above"&&Number.isFinite(cluster.bandTop)
        ? cluster.bandTop
        : null;
    const baseTop=boundary===null
      ? cluster.yTotal/count
      : boundary+direction*15;
    let placed=null;
    for(const outward of [0,10,20]){
      for(const dx of [0,20,-20,34,-34]){
        const left=Math.max(bounds.left,Math.min(bounds.right,baseLeft+dx));
        const top=Math.max(bounds.top+9,Math.min(bounds.bottom-9,baseTop+direction*outward));
        const rect=compactRect(left,top,cluster.eventCount);
        const envelopeCandidate={position:cluster.position,bandTop:cluster.bandTop,bandBottom:cluster.bandBottom};
        if(!inside(rect,bounds))continue;
        if(!outsideEnvelope(rect,envelopeCandidate,4))continue;
        if(occupied.some((other)=>intersects(rect,other,2)))continue;
        placed={left,top,rect};
        break;
      }
      if(placed)break;
    }
    if(!placed)continue;
    occupied.push(placed.rect);
    compact.push({
      id:`cluster-${index}-${cluster.rows.map((row)=>row.id).join("-")}`,
      left:placed.left,top:placed.top,rect:placed.rect,compact:true,
      eventCount:cluster.eventCount,rows:cluster.rows,tone:"cluster",
      glyph:"",multiplier:`+${cluster.eventCount}`,title:`+${cluster.eventCount} events`,
      value:"",position:cluster.position,
    });
  }

  return {full,compact,all:[...full,...compact]};
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

export function zoneToneForRank(rank,total) {
  const count=Math.max(1,Math.floor(finite(total,1)));
  const position=count===1?.5:Math.max(0,Math.min(1,finite(rank)/(count-1)));
  if(position<.25)return "red";
  if(position<.5)return "amber";
  if(position<.75)return "green";
  return "blue";
}
