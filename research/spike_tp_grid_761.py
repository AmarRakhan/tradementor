#!/usr/bin/env python3
"""Read-only one-event-per-20-2-breach TP grid. Candles from public Aster API."""
import argparse,csv,json,math,os,statistics,time,urllib.parse,urllib.request
from datetime import datetime,timezone
BASE=os.environ.get("ASTER_PUBLIC_FAPI_BASE","https://fapi.asterdex.com").rstrip("/")
TP=(0.2,0.3,0.5,0.75,1.0,1.5)
HORIZONS=(5,15,30,60,240)
def fetch(path,query):
    req=urllib.request.Request(BASE+path+"?"+urllib.parse.urlencode(query),headers={"User-Agent":"AmarSpikeResearch/1.1"})
    with urllib.request.urlopen(req,timeout=20) as response:return json.load(response)
def run_market(symbol,tf,limit,now):
    raw=fetch("/fapi/v1/klines",{"symbol":symbol,"interval":tf,"limit":limit})
    rows=[(int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4]),int(x[6])) for x in raw]
    mins={"1m":1,"5m":5,"15m":15}[tf];out=[]
    active={"LONG":False,"SHORT":False}
    for i in range(20,len(rows)-1):
        t,o,high,low,close,end=rows[i]
        if end>=now:break
        hist=[x[4] for x in rows[i-20:i]]
        mean=sum(hist)/20
        sigma=math.sqrt(sum((v-mean)**2 for v in hist)/20)
        if sigma<=0:continue
        for side,extreme in (("LONG",low),("SHORT",high)):
            score=((mean-extreme)/sigma if side=="LONG" else (extreme-mean)/sigma)
            breach=score>2
            if not breach:active[side]=False;continue
            if active[side]:continue
            active[side]=True
            band=mean+(-2 if side=="LONG" else 2)*sigma
            if band<=0:continue
            entry=rows[i+1][1]
            if entry<=0:continue
            observed=int((now-rows[i+1][0])/60000)
            later=[x for x in rows[i+1:] if x[5]<now]
            results={}
            for target_pct in TP:
                target=entry*(1+target_pct/100 if side=="LONG" else 1-target_pct/100)
                hit=next(((j+1)*mins for j,x in enumerate(later) if (x[2]>=target if side=="LONG" else x[3]<=target)),None)
                results[f"tp_{str(target_pct).replace('.','_')}_minutes"]=hit if hit is not None else ""
            adverse=max((((x[2]-entry)/entry if side=="SHORT" else (entry-x[3])/entry)*100 for x in later),default=0)
            out.append({"symbol":symbol,"tf":tf,"side":side,"time_utc":datetime.fromtimestamp(t/1000,timezone.utc).isoformat(),"score_sigma":round(score,3),"score_bin":f"{int(score)}-{int(score)+1}" if score<7 else "7+","wick_extreme":extreme,"bb20_2":band,"overshoot_pct":round(100*(band-extreme)/band if side=="LONG" else 100*(extreme-band)/band,5),"entry_next_open":entry,"observed_minutes":observed,"max_adverse_pct":round(max(0,adverse),3),**results})
    return out
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--symbols",default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,DOGEUSDT")
    p.add_argument("--timeframes",default="1m,5m,15m")
    p.add_argument("--limit",type=int,default=900)
    p.add_argument("--out",default="spike-results")
    args=p.parse_args();os.makedirs(args.out,exist_ok=True);now=int(time.time()*1000)
    events=[];errors=[]
    for sym in args.symbols.split(","):
        for tf in args.timeframes.split(","):
            try:events.extend(run_market(sym,tf,args.limit,now))
            except Exception as exc:errors.append({"symbol":sym,"timeframe":tf,"error":type(exc).__name__})
    if not events and errors:raise RuntimeError("All market reads failed")
    fields=list(events[0].keys()) if events else ["symbol","tf","side","time_utc","score_sigma","score_bin","wick_extreme","bb20_2","overshoot_pct","entry_next_open","observed_minutes","max_adverse_pct"]+[f"tp_{str(p).replace('.','_')}_minutes" for p in TP]
    with open(args.out+"/spikes_tp_grid.csv","w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(events)
    result=[]
    for tf in args.timeframes.split(","):
        for group in ("2-3","3-4","4-5","5-6","6-7","7+"):
            subset=[e for e in events if e["tf"]==tf and e["score_bin"]==group]
            for pval in TP:
                field=f"tp_{str(pval).replace('.','_')}_minutes"
                for h in HORIZONS:
                    mature=[e for e in subset if e["observed_minutes"]>=h]
                    hits=sum(bool(e[field]) and e[field]<=h for e in mature)
                    result.append({"tf":tf,"sigma_bin":group,"tp_pct":pval,"horizon_min":h,"spike_count":len(subset),"mature_count":len(mature),"tp_hits":hits,"winrate_pct":round(100*hits/len(mature),2) if mature else None})
    data={"generated_utc":datetime.now(timezone.utc).isoformat(),"events":len(events),"errors":errors,"method":"20 prior completed closes, first wick crossing 2 sigma, next-bar open, TP from OHLC highs/lows, no real fills, exclude insufficient follow-up by horizon, no stop or fees","results":result}
    with open(args.out+"/tp_grid.json","w") as f:json.dump(data,f,indent=2)
    print(json.dumps({"events":len(events),"errors":errors,"tp_grid_rows":len(result)}))
if __name__=="__main__":main()
