export const PORTFOLIO_ZONE_SEATS_PER_STEP = 5;
export const PORTFOLIO_ZONE_MAX_TOTAL_SLOTS = 100;

function count(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.round(number)) : null;
}

export function derivePortfolioZoneInstruction(input = {}) {
  const rawZone = input.zoneIndex;
  const zone = rawZone === null || rawZone === undefined || rawZone === "" ? null : Number.isInteger(Number(rawZone)) ? Number(rawZone) : null;
  const longSlots = count(input.longSlots);
  const shortSlots = count(input.shortSlots);
  const activeLong = count(input.activeLong);
  const activeShort = count(input.activeShort);
  const perStep = Math.max(1, count(input.seatsPerStep) ?? PORTFOLIO_ZONE_SEATS_PER_STEP);
  const maxTotal = Math.max(1, count(input.maxTotalSlots) ?? PORTFOLIO_ZONE_MAX_TOTAL_SLOTS);

  if (zone === null || longSlots === null || shortSlots === null || activeLong === null || activeShort === null) {
    return {
      status: "UNAVAILABLE",
      zoneIndex: zone,
      side: null,
      amount: 0,
      longSlots,
      shortSlots,
      activeLong,
      activeShort,
      targetLongSlots: longSlots,
      targetShortSlots: shortSlots,
      desiredLongSlots: longSlots,
      desiredShortSlots: shortSlots,
      requiredFreeSeats: 0,
      reason: "Live zone- of stoeldata ontbreekt.",
    };
  }

  const safeLongSlots = Math.max(longSlots, activeLong);
  const safeShortSlots = Math.max(shortSlots, activeShort);
  if (zone === 0) {
    return {
      status: "OK",
      zoneIndex: zone,
      side: null,
      amount: 0,
      longSlots: safeLongSlots,
      shortSlots: safeShortSlots,
      activeLong,
      activeShort,
      targetLongSlots: safeLongSlots,
      targetShortSlots: safeShortSlots,
      desiredLongSlots: safeLongSlots,
      desiredShortSlots: safeShortSlots,
      requiredFreeSeats: 0,
      reason: "Neutrale zone: huidige stoelverdeling behouden.",
    };
  }

  const side = zone > 0 ? "SHORT" : "LONG";
  const requiredFreeSeats = Math.min(15, Math.abs(zone) * perStep);
  const sideSlots = side === "LONG" ? safeLongSlots : safeShortSlots;
  const activeSide = side === "LONG" ? activeLong : activeShort;
  const freeSide = Math.max(0, sideSlots - activeSide);
  const desiredSideSlots = activeSide + requiredFreeSeats;
  const desiredLongSlots = side === "LONG" ? desiredSideSlots : safeLongSlots;
  const desiredShortSlots = side === "SHORT" ? desiredSideSlots : safeShortSlots;
  const delta = desiredSideSlots - sideSlots;

  if (delta === 0) {
    return {
      status: "OK",
      zoneIndex: zone,
      side,
      amount: 0,
      longSlots: safeLongSlots,
      shortSlots: safeShortSlots,
      activeLong,
      activeShort,
      targetLongSlots: safeLongSlots,
      targetShortSlots: safeShortSlots,
      desiredLongSlots,
      desiredShortSlots,
      requiredFreeSeats,
      reason: `${requiredFreeSeats} vrije ${side}-stoelen staan klaar voor deze zone.`,
    };
  }

  if (delta < 0) {
    const amount = Math.abs(delta);
    return {
      status: "REMOVE",
      zoneIndex: zone,
      side,
      amount,
      longSlots: safeLongSlots,
      shortSlots: safeShortSlots,
      activeLong,
      activeShort,
      targetLongSlots: side === "LONG" ? desiredSideSlots : safeLongSlots,
      targetShortSlots: side === "SHORT" ? desiredSideSlots : safeShortSlots,
      desiredLongSlots,
      desiredShortSlots,
      requiredFreeSeats,
      reason: `Deze zone vraagt ${requiredFreeSeats} vrije ${side}-stoelen; ${freeSide} zijn vrij.`,
    };
  }

  const currentTotal = safeLongSlots + safeShortSlots;
  const room = Math.max(0, maxTotal - currentTotal);
  const amount = Math.min(delta, room);
  if (amount <= 0) {
    return {
      status: "BLOCKED",
      zoneIndex: zone,
      side,
      amount: delta,
      longSlots: safeLongSlots,
      shortSlots: safeShortSlots,
      activeLong,
      activeShort,
      targetLongSlots: safeLongSlots,
      targetShortSlots: safeShortSlots,
      desiredLongSlots,
      desiredShortSlots,
      requiredFreeSeats,
      reason: `Deze zone vraagt ${delta} extra ${side}-stoelen, maar de limiet van ${maxTotal} totaal is bereikt.`,
    };
  }

  const targetLongSlots = side === "LONG" ? safeLongSlots + amount : safeLongSlots;
  const targetShortSlots = side === "SHORT" ? safeShortSlots + amount : safeShortSlots;
  return {
    status: amount === delta ? "ADD" : "PARTIAL_ADD",
    zoneIndex: zone,
    side,
    amount,
    remaining: Math.max(0, delta - amount),
    longSlots: safeLongSlots,
    shortSlots: safeShortSlots,
    activeLong,
    activeShort,
    targetLongSlots,
    targetShortSlots,
    desiredLongSlots,
    desiredShortSlots,
    requiredFreeSeats,
    reason: amount === delta
      ? `Deze zone vraagt ${requiredFreeSeats} vrije ${side}-stoelen; ${freeSide} zijn vrij.`
      : `Er is ruimte voor ${amount} van de ${delta} benodigde extra ${side}-stoelen.`,
  };
}


function finitePositive(value) {
  const number=Number(value);
  return Number.isFinite(number)&&number>0?number:null;
}

function median(values) {
  const rows=(Array.isArray(values)?values:[]).filter((value)=>Number.isFinite(value)&&value>0).sort((a,b)=>a-b);
  if(!rows.length)return null;
  const middle=Math.floor(rows.length/2);
  return rows.length%2?rows[middle]:(rows[middle-1]+rows[middle])/2;
}

export function zoneToneForSignedIndex(index) {
  const value=Number(index);
  if(!Number.isFinite(value))return "blue";
  if(value>=3)return "red";
  if(value>=1)return "amber";
  if(value===0)return "blue";
  return "green";
}

export function derivePortfolioZoneLadder(zones, options={}) {
  const minIndex=Number.isInteger(Number(options.minIndex))?Math.max(-12,Number(options.minIndex)):-3;
  const maxIndex=Number.isInteger(Number(options.maxIndex))?Math.min(12,Number(options.maxIndex)):3;
  const byIndex=new Map();
  for(const raw of Array.isArray(zones)?zones:[]){
    if(!raw||typeof raw!=="object")continue;
    const index=Number(raw.index),center=finitePositive(raw.center);
    if(!Number.isInteger(index)||center===null)continue;
    byIndex.set(index,{...raw,index,center,atr:finitePositive(raw.atr)});
  }
  const observed=[...byIndex.values()].sort((a,b)=>a.index-b.index);
  if(!observed.length)return {zones:[],step:null,anchor:null,source:"unavailable"};

  const stepCandidates=[];
  for(let index=1;index<observed.length;index+=1){
    const previous=observed[index-1],current=observed[index];
    const indexGap=current.index-previous.index;
    const priceGap=current.center-previous.center;
    if(indexGap>0&&priceGap>0)stepCandidates.push(priceGap/indexGap);
  }
  const observedStep=median(stepCandidates);
  const atrStep=median(observed.map((row)=>row.atr).filter(Boolean).map((value)=>value*1.5));
  const centerMedian=median(observed.map((row)=>row.center))||observed[0].center;
  const fallbackStep=Math.max(centerMedian*.02,atrStep||0);
  const step=observedStep||fallbackStep;
  if(!Number.isFinite(step)||step<=0)return {zones:[],step:null,anchor:null,source:"unavailable"};

  const anchorCandidates=observed.map((row)=>row.center-row.index*step).filter((value)=>Number.isFinite(value)&&value>0);
  const anchor=median(anchorCandidates)||observed[0].center-observed[0].index*step;
  if(!Number.isFinite(anchor)||anchor<=0)return {zones:[],step:null,anchor:null,source:"unavailable"};

  const centers=[];
  for(let index=minIndex;index<=maxIndex;index+=1){
    const observedRow=byIndex.get(index);
    const center=observedRow?.center??anchor+index*step;
    if(Number.isFinite(center)&&center>0)centers.push({index,center,source:observedRow?"confirmed":"extrapolated"});
  }
  let monotonic=true;
  for(let index=1;index<centers.length;index+=1){
    if(centers[index].center<=centers[index-1].center){monotonic=false;break}
  }
  const normalized=monotonic?centers:centers.map((row)=>({...row,center:anchor+row.index*step,source:"extrapolated"}));
  const output=normalized.map((row,index)=>{
    const previous=normalized[index-1],next=normalized[index+1];
    const lower=previous?(previous.center+row.center)/2:Number.NEGATIVE_INFINITY;
    const upper=next?(row.center+next.center)/2:Number.POSITIVE_INFINITY;
    return {
      index:row.index,
      label:row.index===0?"Zone 0":`Zone ${row.index>0?"+":""}${row.index}`,
      center:row.center,
      lower,
      upper,
      tone:zoneToneForSignedIndex(row.index),
      source:row.source,
    };
  });
  return {
    zones:output,
    step,
    anchor,
    source:observedStep?"confirmed-center-spacing":"atr-fallback-spacing",
  };
}

export function portfolioZoneFromLadder(ladder, price) {
  const value=finitePositive(price);
  const rows=Array.isArray(ladder?.zones)?ladder.zones:[];
  if(value===null||!rows.length)return null;
  const inside=rows.find((row)=>Number(row.lower)<=value&&value<Number(row.upper));
  if(inside)return Number(inside.index);
  const nearest=rows.reduce((best,row)=>Math.abs(Number(row.center)-value)<Math.abs(Number(best.center)-value)?row:best);
  return Number.isInteger(Number(nearest.index))?Number(nearest.index):null;
}
