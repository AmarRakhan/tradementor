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
                        adverse=max(adverse, (jh-entry)/entry if side=="SHORT" else (entry-jl)/entry)
                        good=(jh>=target if side=="LONG" else jl<=target)
                        if good:
                            hit=(j-i)*minutes
                            break
                    events.append({"symbol":symbol,"timeframe":tf,"period":n,"sigma":k,"side":side,"wick_extreme":lo if side=="LONG" else hi,"band_at_signal":lower if side=="LONG" else upper,"band_mean":mean,"band_stddev":dev,"spike_utc":datetime.fromtimestamp(t/1000,timezone.utc).isoformat(),"overshoot_pct":round(overshoot*100,5),"entry":entry,"target":target,"tp_minutes":hit,"observed_minutes":max(0,(now-rows[i+1][0])/60000),"max_adverse_pct":round(adverse*100,4)})
    return events
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--symbols",default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,DOGEUSDT")
    p.add_argument("--top",type=int,default=0,help="Discover top N Aster USDT perpetual contracts by 24h quote volume")
    p.add_argument("--pause",type=float,default=0.10,help="Seconds between public kline requests")
    p.add_argument("--timeframes",default="1m,5m,15m")
    p.add_argument("--limit",type=int,default=900)
    p.add_argument("--out",default="spike-results")
    a=p.parse_args()
    os.makedirs(a.out,exist_ok=True)
    now=int(time.time()*1000)
    all_events=[];errors=[]
    symbols=[sym.strip() for sym in a.symbols.split(",") if sym.strip()]
    if a.top:
        try:
            info=get("/fapi/v1/exchangeInfo",{})
            eligible={str(x.get("symbol","")) for x in info.get("symbols",[]) if x.get("quoteAsset")=="USDT" and x.get("contractType")=="PERPETUAL" and x.get("status")=="TRADING"}
            tickers=get("/fapi/v1/ticker/24hr",{})
            if not isinstance(tickers,list):raise ValueError("ticker format")
            ranked=sorted((x for x in tickers if x.get("symbol") in eligible),key=lambda x:float(x.get("quoteVolume") or 0),reverse=True)
            symbols=[x["symbol"] for x in ranked[:a.top]]
            if not symbols:raise ValueError("No eligible symbols in exchangeInfo/ticker overlap")
        except Exception as exc:
            raise RuntimeError("Top-N market discovery failed closed: "+type(exc).__name__) from exc
    for symbol in symbols:
        for tf in a.timeframes.split(","):
            try:
                all_events+=analyze(symbol,tf,candles(symbol,tf,a.limit),now)
                time.sleep(a.pause)
            except Exception as exc:errors.append({"symbol":symbol,"timeframe":tf,"error":type(exc).__name__})
    with open(a.out+"/events.csv","w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["symbol","timeframe","period","sigma","side","wick_extreme","band_at_signal","band_mean","band_stddev","spike_utc","overshoot_pct","entry","target","tp_minutes","observed_minutes","max_adverse_pct"])
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
    out={"generated_utc":datetime.now(timezone.utc).isoformat(),"mode":"HISTORICAL_READ_ONLY","data_note":"OHLC next-bar open assumed; price TP gross, not fills; intrabar TP coarse; spike event keyed by time and BB variant; excludes ongoing candle; sample bounded by limit; events overlap across variants","symbols":symbols,"requested_top":a.top,"errors":errors,"events":len(all_events),"table":report}
    with open(a.out+"/summary.json","w") as f:json.dump(out,f,indent=2)
    print(json.dumps({"events":len(all_events),"errors":errors,"out":a.out}))
if __name__=="__main__":main()
