"""Publieke probe (geen sleutels, geen orders): verbeteringen van de Spike-LONG-trefkans testen op 3 dagen 1m-data.
Varianten: base, opveer-bevestiging (b %), markt-dump-filter (BTC / breedte), 1h-trendfilter, combinaties."""
import json, math, sys, time, urllib.request
BASE = "https://fapi.asterdex.com"
DAYS = 3
symbols = open(sys.argv[1]).read().split()
if "BTCUSDT" not in symbols: symbols.append("BTCUSDT")
now = int(time.time() * 1000) // 60000 * 60000
START = now - DAYS * 86400000
def get(sym, start, end):
    url = f"{BASE}/fapi/v1/klines?symbol={sym}&interval=1m&startTime={start}&endTime={end}&limit=1500"
    with urllib.request.urlopen(url, timeout=25) as r:
        return [[int(x[0]), float(x[2]), float(x[3]), float(x[4])] for x in json.loads(r.read())]
FETCH_START = START - 21 * 3600000   # 20 uur extra voor 1h-referentie
M1 = {}
for sym in symbols:
    rows, t = [], FETCH_START
    try:
        while t < now:
            part = get(sym, t, now)
            if not part: break
            rows += [p for p in part if not rows or p[0] > rows[-1][0]]
            t = part[-1][0] + 60000
            time.sleep(0.08)
            if len(part) < 1500: break
        if len(rows) > 2000: M1[sym] = rows
    except Exception:
        time.sleep(0.5)
def agg(rows, ms):
    out, cur = [], None
    for t, h, l, c in rows:
        b = t // ms * ms
        if cur is None or cur[0] != b:
            if cur: out.append(cur)
            cur = [b, h, l, c]
        else:
            cur[1] = max(cur[1], h); cur[2] = min(cur[2], l); cur[3] = c
    if cur: out.append(cur)
    return out
# markt: per minuut BTC-15m-rendement en breedte (aandeel munten met 15m-rendement < -1 %)
close_at = {s: {r[0]: r[3] for r in rows} for s, rows in M1.items()}
btc = close_at.get("BTCUSDT", {})
minutes = sorted({t for s in close_at for t in close_at[s] if t >= START - 60000})
breadth = {}
for t in minutes:
    down = tot = 0
    for s, cm in close_at.items():
        a, b = cm.get(t), cm.get(t - 900000)
        if a and b:
            tot += 1; down += (a / b - 1) < -0.01
    breadth[t] = down / tot if tot else 0
def btc15(t):
    a, b = btc.get(t), btc.get(t - 900000)
    return (a / b - 1) * 100 if a and b else 0
TFS = {"1m": 60000, "5m": 300000, "15m": 900000}
CONFIGS = [(tf, k, d) for tf in TFS for k in (2, 3, 4, 5, 6, 7) for d in (0, 1, 2, 3)]
VARIANTS = ["base", "b0.3", "b0.3+breadth"]
LOW_FEE = set(open(sys.argv[3]).read().split())
NETS = [0.05, 0.1, 0.15, 0.2, 0.3, 0.4]   # netto TP na fees
HEDGES = [1.25, 2.0, 3.0]
res = {f"{tf}|{k}|{d}|{v}|{n}": {"n": 0, "tp": {str(h): 0 for h in HEDGES}, "ever": 0, "net": 0.0, "mins": []}
       for tf, k, d in CONFIGS for v in VARIANTS for n in NETS}
for sym, m1 in M1.items():
    if sym == "BTCUSDT": continue
    idx = {r[0]: i for i, r in enumerate(m1)}
    h1 = agg(m1, 3600000); h1c = [r[3] for r in h1]; h1t = [r[0] for r in h1]
    import bisect
    def trend_ok(t):   # laatste afgesloten 1h-close boven SMA20(1h)
        i = bisect.bisect_right(h1t, t - 3600000) - 1
        if i < 19: return False
        sma = sum(h1c[i - 19:i + 1]) / 20
        return h1c[i] >= sma
    for tf, ms in TFS.items():
        rows = m1 if tf == "1m" else agg(m1, ms)
        closes = [r[3] for r in rows]
        stats = [None] * len(rows)
        for i in range(20, len(rows)):
            p = closes[i - 20:i]; mu = sum(p) / 20
            stats[i] = (mu, math.sqrt(sum((v - mu) ** 2 for v in p) / 20))
        for k in (2, 3, 4, 5, 6, 7):
            for d in (0, 1, 2, 3):
                trigs = []   # (tf-candle start, trigger price, first 1m index)
                for i in range(20, len(rows)):
                    r = rows[i]
                    if r[0] < START: continue
                    mu, dev = stats[i]
                    if not dev > 0: continue
                    trig = min(mu - k * dev, mu * (1 - d / 100))
                    if r[2] > trig: continue
                    for t0 in range(r[0], r[0] + ms, 60000):
                        q = idx.get(t0)
                        if q is not None and m1[q][2] <= trig:
                            trigs.append((r[0], trig, q)); break
                fee_rt = 0.025 if sym in LOW_FEE else 0.08
                for v in VARIANTS:
                  for net in NETS:
                    TP = net + fee_rt
                    r_ = res[f"{tf}|{k}|{d}|{v}|{net}"]
                    busy = 0
                    for start_ms, trig, j in trigs:
                        if m1[j][0] < busy: continue
                        if v.startswith("b0."):
                            b = float(v.split("+")[0][1:]) / 100
                            low, e = m1[j][2], None
                            for q in range(j, min(len(m1), j + 60)):
                                low = min(low, m1[q][2])
                                if m1[q][3] >= low * (1 + b): e = q; break
                            if e is None:
                                busy = m1[min(len(m1) - 1, j + 60)][0]; continue
                            ei, ep, first = e, m1[e][3], e + 1
                        else:
                            ei, ep, first = j, trig, j
                        te = m1[ei][0]
                        if "breadth" in v and breadth.get(te, 0) >= 0.15: busy = te + 60000; continue
                        r_["n"] += 1
                        mae, hit, q = 0.0, None, first
                        for q in range(first, len(m1)):
                            c = m1[q]
                            mae = max(mae, (ep - c[2]) / ep * 100)
                            fav = c[3] if q == j and first == j else c[1]
                            if (fav - ep) / ep * 100 >= TP:
                                hit = mae; break
                        if hit is not None:
                            r_["ever"] += 1
                            for h in HEDGES:
                                if hit < h: r_["tp"][str(h)] += 1
                            busy = m1[q][0] + 60000
                        else:
                            busy = 10 ** 15
out = {"startMs": START, "endMs": now, "symbols": len(M1), "results": {}}
for kk, a in res.items():
    out["results"][kk] = {"n": a["n"], "tp": a["tp"], "ever": a["ever"]}
json.dump(out, open(sys.argv[2], "w")); print("ok", len(M1))
