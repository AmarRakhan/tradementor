export const MAX_FULL_EVENT_LABELS = 3;
export const MAX_COMPACT_EVENT_CLUSTERS = 2;

function finite(value, fallback=0) {
  const number=Number(value);
  return Number.isFinite(number)?number:fallback;
}

function intersects(a,b,padding=4) {
  return !(a.right+padding<=b.left || b.right+padding<=a.left || a.bottom+padding<=b.top || b.bottom+padding<=a.top);
}

function fullRect(candidate,left,top) {
  const width=Math.max(58,Math.min(90,finite(candidate.width,76)));
  const height=Math.max(26,Math.min(40,finite(candidate.height,32)));
  return {left:left-width/2,right:left+width/2,top:top-height/2,bottom:top+height/2,width,height};
}

function inside(rect,bounds) {
  return rect.left>=bounds.left && rect.right<=bounds.right && rect.top>=bounds.top && rect.bottom<=bounds.bottom;
}

export function eventPriority(row) {
  const kind=String(row?.kind||"").toLowerCase();
  const base=kind==="entry"?300:kind==="tp"?200:kind==="cashflow"?100:150;
  const notional=Math.abs(finite(row?.notionalUsd))+Math.abs(finite(row?.realizedPnlUsd))*25;
  return base+Math.min(25,Math.log10(1+notional)*5);
}

export function layoutPortfolioKoersMarkers(candidates,viewport,{maxFull=MAX_FULL_EVENT_LABELS,maxCompact=MAX_COMPACT_EVENT_CLUSTERS,priceAxisWidth=70}={}) {
  const width=Math.max(1,finite(viewport?.width,1));
  const height=Math.max(1,finite(viewport?.height,1));
  const bounds={left:42,right:Math.max(43,width-priceAxisWidth-4),top:12,bottom:height-14};
  const ordered=(Array.isArray(candidates)?candidates:[])
    .filter((row)=>row&&Number.isFinite(Number(row.x))&&Number.isFinite(Number(row.y)))
    .map((row,index)=>({...row,index,priority:finite(row.priority,eventPriority(row)),time:finite(row.time)}))
    .sort((a,b)=>b.priority-a.priority || b.time-a.time || b.index-a.index);

  const full=[];
  const compactPool=[];
  const occupied=[];
  const offsets=[[0,0],[0,-18],[0,18],[20,0],[-20,0],[18,-14],[-18,14],[28,0],[-28,0]];

  for(const candidate of ordered){
    if(full.length>=Math.max(0,maxFull)){compactPool.push(candidate);continue}
    const direction=String(candidate.position)==="below"?1:-1;
    const anchorY=finite(candidate.y)+direction*25;
    let placed=null;
    for(const [dx,dy] of offsets){
      const left=finite(candidate.x)+dx;
      const top=anchorY+dy;
      const rect=fullRect(candidate,left,top);
      if(!inside(rect,bounds))continue;
      if(occupied.some((other)=>intersects(rect,other)))continue;
      placed={...candidate,left,top,rect,compact:false};
      break;
    }
    if(placed){full.push(placed);occupied.push(placed.rect)}
    else compactPool.push(candidate);
  }

  const clusterMap=new Map();
  for(const candidate of compactPool){
    const x=Math.max(bounds.left,Math.min(bounds.right,finite(candidate.x)));
    const y=Math.max(bounds.top+10,Math.min(bounds.bottom-10,finite(candidate.y)));
    const key=`${Math.round(x/96)}:${Math.round(y/72)}`;
    const existing=clusterMap.get(key)||{xTotal:0,yTotal:0,rows:[],eventCount:0,priority:0,latestTime:0};
    existing.xTotal+=x;
    existing.yTotal+=y;
    existing.rows.push(candidate);
    existing.eventCount+=Math.max(1,Math.floor(finite(candidate.eventCount,1)));
    existing.priority=Math.max(existing.priority,finite(candidate.priority,eventPriority(candidate)));
    existing.latestTime=Math.max(existing.latestTime,finite(candidate.time));
    clusterMap.set(key,existing);
  }

  const clusters=[...clusterMap.values()].sort((a,b)=>b.priority-a.priority||b.latestTime-a.latestTime);
  const kept=clusters.slice(0,Math.max(0,maxCompact));
  for(const overflow of clusters.slice(kept.length)){
    if(!kept.length){kept.push(overflow);continue}
    const overflowX=overflow.xTotal/Math.max(1,overflow.rows.length);
    let target=kept[0];
    let distance=Math.abs(target.xTotal/Math.max(1,target.rows.length)-overflowX);
    for(const candidate of kept.slice(1)){
      const nextDistance=Math.abs(candidate.xTotal/Math.max(1,candidate.rows.length)-overflowX);
      if(nextDistance<distance){target=candidate;distance=nextDistance}
    }
    target.xTotal+=overflow.xTotal;
    target.yTotal+=overflow.yTotal;
    target.rows.push(...overflow.rows);
    target.eventCount+=overflow.eventCount;
    target.priority=Math.max(target.priority,overflow.priority);
    target.latestTime=Math.max(target.latestTime,overflow.latestTime);
  }

  const compact=kept.map((cluster,index)=>{
    const count=Math.max(1,cluster.rows.length);
    return {
      id:`cluster-${index}-${cluster.rows.map((row)=>row.id).join("-")}`,
      left:cluster.xTotal/count,
      top:cluster.yTotal/count,
      compact:true,
      eventCount:cluster.eventCount,
      rows:cluster.rows,
      tone:"cluster",
      title:`+${cluster.eventCount} events`,
      value:"",
      position:"above",
    };
  });

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

export function zoneToneForRank(rank,total) {
  const count=Math.max(1,Math.floor(finite(total,1)));
  const position=count===1?.5:Math.max(0,Math.min(1,finite(rank)/(count-1)));
  if(position<.25)return "red";
  if(position<.5)return "amber";
  if(position<.75)return "green";
  return "blue";
}
