"""Publieke backtest-probe (geen sleutels, geen orders): Spike-instap per timeframe/niveau/min-afstand,
daarna op 1m-candles: TP (+0,25/+0,5 %) gehaald vóór welke tegenbeweging (MAE)?
Instap = triggerprijs = verste van BB(20,k) en gemiddelde -/+ d % (zoals de bot). Eén positie per munt per
instelling: na instap geen nieuwe tot TP; zonder TP blijft de munt bezet (gehedgede positie)."""
import json, math, sys, time, urllib.request
BASE = "https://fapi.asterdex.com"
TFMS = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000}
LEVELS = [2, 3, 4, 5, 6, 7]
DISTS = [0, 1, 2, 3]
TPS = [0.25, 0.5]
HEDGES = [0.5, 1, 1.5, 2, 3, 5, 100]   # tegenbeweging in % vóór TP; 100 = nooit hedgen
symbols = open(sys.argv[1]).read().split()
now = int(time.time() * 1000)
START = now - 24 * 3600000
def get(sym, tf, limit):
    with urllib.request.urlopen(f"{BASE}/fapi/v1/klines?symbol={sym}&interval={tf}&limit={limit}", timeout=20) as r:
        return [[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4])] for x in json.loads(r.read())]
data = {}
for sym in symbols:
    try:
        d = {"1m": get(sym, "1m", 1500)}
        time.sleep(0.1)
        for tf, ms in TFMS.items():
            if tf != "1m":
                d[tf] = get(sym, tf, int(24 * 3600000 / ms) + 25); time.sleep(0.1)
        data[sym] = d
    except Exception:
        time.sleep(0.5)
def key(tf, side, k, dist): return f"{tf}|{side}|{k}|{dist}"
agg = {}
for sym, d in data.items():
    m1 = d["1m"]
    idx = {row[0]: i for i, row in enumerate(m1)}
    for tf, ms in TFMS.items():
        rows = d[tf]; closes = [r[4] for r in rows]
        for side in ("LONG", "SHORT"):
            for k in LEVELS:
                for dist in DISTS:
                    a = agg.setdefault(key(tf, side, k, dist), {"entries": 0, "tp": {str(t): {str(h): 0 for h in HEDGES} for t in TPS},
                                                                 "mins": {str(t): [] for t in TPS}, "open": 0})
                    busy_until = 0
                    for i, r in enumerate(rows):
                        if i < 20 or r[0] < START or r[0] < busy_until:
                            continue
                        prev = closes[i - 20:i]; mean = sum(prev) / 20
                        dev = math.sqrt(sum((v - mean) ** 2 for v in prev) / 20)
                        if not dev > 0: continue
                        if side == "LONG":
                            trig = min(mean - k * dev, mean * (1 - dist / 100))
                            if not r[3] <= trig: continue
                        else:
                            trig = max(mean + k * dev, mean * (1 + dist / 100))
                            if not r[2] >= trig: continue
                        # eerste 1m-candle binnen deze candle die de trigger raakt
                        j = None
                        for t0 in range(r[0], r[0] + ms, 60000):
                            q = idx.get(t0)
                            if q is None: continue
                            c = m1[q]
                            if (side == "LONG" and c[3] <= trig) or (side == "SHORT" and c[2] >= trig):
                                j = q; break
                        if j is None: continue
                        a["entries"] += 1
                        mae = 0.0; done = {str(t): None for t in TPS}; end_ms = None
                        for q in range(j, len(m1)):
                            c = m1[q]
                            adverse = (trig - c[3]) / trig * 100 if side == "LONG" else (c[2] - trig) / trig * 100
                            mae = max(mae, adverse)
                            fav = (c[4] if q == j else c[2]) if side == "LONG" else (c[4] if q == j else c[3])
                            gain = (fav - trig) / trig * 100 if side == "LONG" else (trig - fav) / trig * 100
                            for t in TPS:
                                if done[str(t)] is None and gain >= t:
                                    done[str(t)] = (mae, (c[0] - m1[j][0]) / 60000)
                            if done["0.5"] is not None:
                                end_ms = c[0]; break
                        for t in TPS:
                            res = done[str(t)]
                            if res is None: continue
                            for h in HEDGES:
                                if res[0] < h: a["tp"][str(t)][str(h)] += 1
                            a["mins"][str(t)].append(res[1])
                        if end_ms is None: a["open"] += 1; busy_until = 10**15
                        else: busy_until = end_ms + 60000
out = {"startMs": START, "endMs": now, "symbols": len(data), "results": {}}
for kk, a in agg.items():
    m = {t: sorted(v) for t, v in a["mins"].items()}
    out["results"][kk] = {"entries": a["entries"], "tp": a["tp"], "noTp05": a["open"],
                          "medianMin": {t: (v[len(v)//2] if v else None) for t, v in m.items()}}
json.dump(out, open(sys.argv[2], "w")); print("ok", len(data))
