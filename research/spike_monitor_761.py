#!/usr/bin/env python3
"""Read-only historical Aster spike study. No credentials, orders or account data."""
import argparse,csv,json,math,os,statistics,time,urllib.parse,urllib.request
from collections import defaultdict
from datetime import datetime,timezone
PERIODS=(20,50,70,80)
MULTIPLIERS=(2,3,4,5)
HORIZONS=(5,15,60,720)
URL=os.environ.get("ASTER_PUBLIC_FAPI_BASE","https://fapi.asterdex.com").rstrip("/")
def get(path,params):
    url=URL+path+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"User-Agent":"AmarSpikeResearch/1.0"})
    with urllib.request.urlopen(req,timeout=16) as resp:
        return json.load(resp)
def candles(symbol,interval,limit):
    rows=get("/fapi/v1/klines",{"symbol":symbol,"interval":interval,"limit":limit})
    return [(int(r[0]),float(r[1]),float(r[2]),float(r[3]),float(r[4]),int(r[6])) for r in rows]
def analyze(symbol,tf,rows,now):
    events=[]
    states={(n,k,s):False for n in PERIODS for k in MULTIPLIERS for s in ("LONG","SHORT")}
    minutes={"1m":1,"5m":5,"15m":15}[tf]
    for i in range(max(PERIODS),len(rows)-1):
        t,o,hi,lo,c,close_time=rows[i]
        if close_time >= now:break
        for n in PERIODS:
            hist=[x[4] for x in rows[i-n:i]]
            mean=sum(hist)/n
            dev=math.sqrt(sum((p-mean)**2 for p in hist)/n)
            if dev<=0:continue
            for k in MULTIPLIERS:
                lower,upper=mean-k*dev,mean+k*dev
                for side,broken,overshoot in (("LONG",lo<lower,(lower-lo)/lower if lower>0 else 0),("SHORT",hi>upper,(hi-upper)/upper if upper>0 else 0)):
                    key=(n,k,side)
                    if not broken:
                        states[key]=False
                        continue
                    if states[key]:continue
                    states[key]=True
                    entry=rows[i+1][1]
                    if entry<=0:continue
                    target=entry*(1.005 if side=="LONG" else .995)
                    hit=None
                    adverse=0.0
                    for j in range(i+1,len(rows)):
                        jt,jo,jh,jl,jc,jend=rows[j]
                        if jend>=now:break
                        adverse=max(adverse, (entry-jl)/entry if side=="SHORT" else (jh-entry)/entry)
                        good=(jh>=target if side=="LONG" else jl<=target)
                        if good:
                            hit=(j-i)*minutes
                            break
                    events.append({"symbol":symbol,"timeframe":tf,"period":n,"sigma":k,"side":side,"spike_utc":datetime.fromtimestamp(t/1000,timezone.utc).isoformat(),"overshoot_pct":round(overshoot*100,5),"entry":entry,"target":target,"tp_minutes":hit,"observed_minutes":max(0,(now-rows[i+1][0])/60000),"max_adverse_pct":round(adverse*100,4)})
    return events
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--symbols",default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,DOGEUSDT")
    p.add_argument("--timeframes",default="1m,5m,15m")
    p.add_argument("--limit",type=int,default=900)
    p.add_argument("--out",default="spike-results")
    a=p.parse_args()
    os.makedirs(a.out,exist_ok=True)
    now=int(time.time()*1000)
    all_events=[];errors=[]
    for symbol in a.symbols.split(","):
        for tf in a.timeframes.split(","):
            try:all_events+=analyze(symbol.strip(),tf,candles(symbol.strip(),tf,a.limit),now)
            except Exception as exc:errors.append({"symbol":symbol,"timeframe":tf,"error":type(exc).__name__})
    with open(a.out+"/events.csv","w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["symbol","timeframe","period","sigma","side","spike_utc","overshoot_pct","entry","target","tp_minutes","observed_minutes","max_adverse_pct"])
        w.writeheader();w.writerows(all_events)
    report=[]
    for tf in a.timeframes.split(","):
        for n in PERIODS:
            for k in MULTIPLIERS:
                sample=[x for x in all_events if x["timeframe"]==tf and x["period"]==n and x["sigma"]==k]
                row={"tf":tf,"bollinger":f"{n}-{k}","spikes":len(sample),"tp_eventually_observed":sum(x["tp_minutes"] is not None for x in sample)}
                for h in HORIZONS:
                    row[f"tp_{h}m"]=sum(x["tp_minutes"] is not None and x["tp_minutes"]<=h for x in sample)
                    row[f"matured_{h}m"]=sum(x["observed_minutes"]>=h for x in sample)
                tp=[x["tp_minutes"] for x in sample if x["tp_minutes"] is not None]
                row["median_tp_minutes"]=statistics.median(tp) if tp else None
                report.append(row)
    out={"generated_utc":datetime.now(timezone.utc).isoformat(),"mode":"HISTORICAL_READ_ONLY","data_note":"OHLC next-bar open assumed; price TP gross, not fills; intrabar TP coarse; spike event keyed by time and BB variant; excludes ongoing candle; sample bounded by limit; events overlap across variants","symbols":a.symbols.split(","),"errors":errors,"events":len(all_events),"table":report}
    with open(a.out+"/summary.json","w") as f:json.dump(out,f,indent=2)
    print(json.dumps({"events":len(all_events),"errors":errors,"out":a.out}))
if __name__=="__main__":main()
