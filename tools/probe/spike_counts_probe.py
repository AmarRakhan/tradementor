"""Publieke probe: tel spikes per timeframe, BB(20,k)-niveau en minimale afstand (%). Geen sleutels, geen orders.
Per candle sinds START: gemiddelde/sigma van de 20 vorige closes; LONG = low eronder, SHORT = high erboven."""
import json, math, sys, time, urllib.request
BASE = "https://fapi.asterdex.com"
START = int(sys.argv[3])
TF = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000, "4h": 14400000, "1d": 86400000}
LEVELS = [2, 3, 4, 5, 6, 7]
DISTS = [0, 1, 2, 3]
symbols = open(sys.argv[1]).read().split()
now = int(time.time() * 1000)
res = {"startMs": START, "endMs": now, "symbols": len(symbols), "errors": {}, "tf": {}}
for tf, ms in TF.items():
    need = (now - START) // ms + 25
    cnt = {s: {str(d): {str(k): 0 for k in LEVELS} for d in DISTS} for s in ("LONG", "SHORT")}
    coins = {s: {str(d): set() for d in DISTS} for s in ("LONG", "SHORT")}
    ex = []
    candles = 0
    for sym in symbols:
        try:
            with urllib.request.urlopen(f"{BASE}/fapi/v1/klines?symbol={sym}&interval={tf}&limit={min(1500, need)}", timeout=20) as r:
                rows = json.loads(r.read())
        except Exception as exc:
            res["errors"][f"{sym}/{tf}"] = str(exc)[:120]
            time.sleep(0.3)
            continue
        closes = [float(x[4]) for x in rows]
        for i, x in enumerate(rows):
            if int(x[0]) + ms <= START or i < 20:
                continue
            prev = closes[i - 20:i]
            mean = sum(prev) / 20
            dev = math.sqrt(sum((v - mean) ** 2 for v in prev) / 20)
            if not dev > 0:
                continue
            candles += 1
            for side, wick in (("LONG", float(x[3])), ("SHORT", float(x[2]))):
                sig = (mean - wick) / dev if side == "LONG" else (wick - mean) / dev
                dist = (mean - wick) / mean * 100 if side == "LONG" else (wick - mean) / mean * 100
                for d in DISTS:
                    if dist < d:
                        continue
                    hit = False
                    for k in LEVELS:
                        if sig >= k:
                            cnt[side][str(d)][str(k)] += 1
                            hit = True
                    if hit:
                        coins[side][str(d)].add(sym)
                if sig >= 2 and dist >= 2 and len(ex) < 40:
                    ex.append([sym, side, int(x[0]), round(sig, 1), round(dist, 2)])
        time.sleep(0.12)
    res["tf"][tf] = {"candles": candles, "counts": cnt,
                     "coins": {s: {d: len(v) for d, v in coins[s].items()} for s in coins}, "examples": ex}
json.dump(res, open(sys.argv[2], "w"))
print("ok", len(res["errors"]))
